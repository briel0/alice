"""Lado do Telegram do filtro: alertas, resumos das 12h e 19h, botões 👍/👎 e balanço do modo sombra.

Tudo sai direto pela API do bot e nada passa por src.history: o agente com ferramentas nunca vê o texto dos
e-mails, nem quando o usuário responde a um alerta. Todo texto vindo de e-mail é escapado para HTML.
"""
import asyncio
import html
import logging
import time
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, constants
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.config import ALLOWED_TELEGRAM_USER_ID, NOTIF_GMAIL_TOKEN_PATH, NOTIF_SOMBRA
from src.notificacoes import db, pipeline, regras
from src.notificacoes.gmail import Gmail, TokenRevogado

logger = logging.getLogger(__name__)

CICLO_SEGUNDOS = 30
GMAIL_SEGUNDOS = 300
ITENS_POR_MENSAGEM = 15
SILENCIADOS_MAX = 25
# Domínios de e-mail pessoal: propor regra para o domínio inteiro não faz sentido
WEBMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com", "yahoo.com.br",
           "icloud.com", "me.com", "bol.com.br", "uol.com.br", "proton.me", "protonmail.com"}
NOME_NIVEL = {"agora": "na hora", "resumo": "no resumo", "silencio": "em silêncio"}
ABAIXO = {"agora": "resumo", "resumo": "silencio"}


def esc(texto: str) -> str:
    return html.escape(texto or "", quote=False)


def prefixo() -> str:
    return "🧪 " if NOTIF_SOMBRA else ""


# --- Mensagens ---

def texto_alerta(it: dict) -> str:
    return (f"{prefixo()}📧 <b>URGENTE</b> · {esc(it['remetente'])} &lt;{esc(it['endereco'])}&gt;\n"
            f"<b>{esc(it['assunto'])}</b>\n{esc(it['resumo'])}\n<i>{esc(it['motivo'])}</i>")


def botoes_alerta(it: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👍 importante", callback_data=f"ntf:up:{it['id']}"),
         InlineKeyboardButton("👎 ruído", callback_data=f"ntf:dn:{it['id']}")],
        [InlineKeyboardButton("Abrir no Gmail", url=it["link"])],
    ])


def mensagens_resumo(itens: list[dict], silenciados: list[dict], desde: str, ate: str) -> list[tuple[str, InlineKeyboardMarkup | None]]:
    """O resumo em uma ou mais mensagens: agrupado por remetente, 👍/👎 por item, silenciados no rodapé."""
    grupos: dict[str, list[dict]] = {}
    for it in itens:
        grupos.setdefault(it["endereco"] or it["remetente"], []).append(it)
    ordenados = [it for grupo in grupos.values() for it in grupo]

    partes = []
    for inicio in range(0, max(len(ordenados), 1), ITENS_POR_MENSAGEM):
        pedaco = ordenados[inicio:inicio + ITENS_POR_MENSAGEM]
        linhas, botoes, anterior = [], [], None
        if inicio == 0:
            linhas.append(f"{prefixo()}📬 <b>Resumo · {len(itens)} e-mail{'s' if len(itens) != 1 else ''}</b>")
        for n, it in enumerate(pedaco, inicio + 1):
            chave = it["endereco"] or it["remetente"]
            if chave != anterior:
                qtd = len(grupos[chave])
                linhas.append(f"\n<b>{esc(it['remetente'])}</b>" + (f" ({qtd})" if qtd > 1 else ""))
                anterior = chave
            linhas.append(f"{n}. {esc(it['resumo'])} · <a href=\"{esc(it['link'])}\">abrir</a>")
            botoes += [InlineKeyboardButton(f"{n} 👍", callback_data=f"ntf:up:{it['id']}"),
                       InlineKeyboardButton(f"{n} 👎", callback_data=f"ntf:dn:{it['id']}")]
        teclado = [botoes[i:i + 4] for i in range(0, len(botoes), 4)]
        partes.append((linhas, teclado))

    linhas, teclado = partes[-1]
    if silenciados:
        por_cat: dict[str, int] = {}
        for it in silenciados:
            nome = pipeline.SILENCIO_CATEGORIAS.get(it["categoria"], "regras e Gemini")
            por_cat[nome] = por_cat.get(nome, 0) + 1
        detalhe = ", ".join(f"{k} {v}" for k, v in sorted(por_cat.items(), key=lambda kv: -kv[1]))
        linhas.append(f"\n<i>{len(silenciados)} em silêncio: {detalhe}</i>")
        de, a = int(datetime.fromisoformat(desde).timestamp()), int(datetime.fromisoformat(ate).timestamp())
        teclado.append([InlineKeyboardButton("ver silenciados", callback_data=f"ntf:sil:{de}:{a}")])
    if not itens:
        linhas.insert(0, f"{prefixo()}📬 <b>Resumo · nada para ver</b>")
    return [("\n".join(l).strip(), InlineKeyboardMarkup(t) if t else None) for l, t in partes]


def texto_balanco(desde: str) -> str:
    b = db.balanco(desde)
    return (f"{prefixo()}📊 <b>Balanço do filtro</b> desde {datetime.fromisoformat(desde):%d/%m}\n"
            f"• na hora: {b['agora']['total']} (👎 alarme falso: {b['agora']['down']})\n"
            f"• no resumo: {b['resumo']['total']} (👍 deveria ter avisado: {b['resumo']['up']}, "
            f"👎 ruído: {b['resumo']['down']})\n"
            f"• em silêncio: {b['silencio']['total']} (👍 escapou: {b['silencio']['up']})\n\n"
            "Se estiver bom: desligue as notificações do Gmail no celular e ponha <code>NOTIF_SOMBRA=0</code> "
            "no alice.env (reinicie a ALICE). Se não, continue apertando 👍/👎.")


# --- Loop ---

def _token_mtime() -> str:
    try:
        return str(NOTIF_GMAIL_TOKEN_PATH.stat().st_mtime_ns)
    except OSError:
        return "ausente"


async def _enviar(bot, texto: str, teclado=None) -> Message:
    return await bot.send_message(chat_id=ALLOWED_TELEGRAM_USER_ID, text=texto, parse_mode=constants.ParseMode.HTML,
                                  reply_markup=teclado, disable_web_page_preview=True)


async def _buscar_gmail(bot, gmail: Gmail) -> None:
    mtime = _token_mtime()
    if db.get_estado("gmail_revogado") == mtime:
        return  # avisado uma vez; volta a tentar quando o arquivo do token mudar
    try:
        n = await asyncio.to_thread(pipeline.rodada, gmail)
        if n:
            logger.info("Filtro: %d e-mail(s) novo(s)", n)
    except (TokenRevogado, FileNotFoundError) as e:
        db.set_estado("gmail_revogado", mtime)
        motivo = "o Google recusou a autorização" if isinstance(e, TokenRevogado) else "o arquivo do token não existe"
        await _enviar(bot, f"⚠️ Filtro de e-mails parado: {motivo}. Rode de novo o "
                           "<code>scripts/gmail_autorizar.py</code> no PC e copie o token para a VPS.")


async def _enviar_alertas(bot) -> None:
    for it in await asyncio.to_thread(db.alertas_pendentes):
        await _enviar(bot, texto_alerta(it), botoes_alerta(it))
        await asyncio.to_thread(db.marcar, "alertado_em", [it["id"]])


async def _enviar_resumo(bot, at: datetime) -> None:
    slot = await asyncio.to_thread(pipeline.resumo_devido, at)
    if slot is None:
        return
    desde = db.get_estado("resumo_ate") or slot.isoformat()
    ate = at.isoformat(timespec="seconds")
    itens = await asyncio.to_thread(db.resumo_pendente)
    silenciados = await asyncio.to_thread(db.silenciados, desde, ate)
    # Dia vazio não manda nada; no modo sombra, só silenciados ainda saem (para conferir o filtro)
    if itens or (NOTIF_SOMBRA and silenciados):
        for texto, teclado in mensagens_resumo(itens, silenciados, desde, ate):
            await _enviar(bot, texto, teclado)
        await asyncio.to_thread(db.marcar, "resumido_em", [it["id"] for it in itens])
    db.set_estado("resumo_slot", slot.isoformat())
    db.set_estado("resumo_ate", ate)


async def _enviar_balanco(bot, at: datetime) -> None:
    inicio = await asyncio.to_thread(pipeline.balanco_devido, at, NOTIF_SOMBRA)
    if inicio:
        await _enviar(bot, texto_balanco(inicio))
        db.set_estado("sombra_balanco", at.isoformat(timespec="seconds"))


async def loop(bot) -> None:
    gmail = Gmail()
    ultima_busca = 0.0
    while True:
        try:
            if time.monotonic() - ultima_busca >= GMAIL_SEGUNDOS:
                ultima_busca = time.monotonic()
                await _buscar_gmail(bot, gmail)
            await _enviar_alertas(bot)
            at = db.now()
            await _enviar_resumo(bot, at)
            await _enviar_balanco(bot, at)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no filtro de notificações")
        await asyncio.sleep(CICLO_SEGUNDOS)


# --- Botões e comando ---

async def _tirar_botoes(query, item_id: int, nota: str) -> None:
    """Tira da mensagem os botões desse item e anota o que aconteceu (como nos lembretes)."""
    message = query.message
    if not isinstance(message, Message) or not message.reply_markup:
        return
    rotulo, linhas = "", []
    for linha in message.reply_markup.inline_keyboard:
        mantidos = []
        for b in linha:
            if b.callback_data and b.callback_data.split(":")[2:3] == [str(item_id)] and b.callback_data[4:6] in ("up", "dn"):
                primeiro = b.text.split()[0]
                rotulo = f"{primeiro}: " if primeiro.isdigit() else ""
            else:
                mantidos.append(b)
        if mantidos:
            linhas.append(mantidos)
    try:
        await query.edit_message_text(f"{message.text_html}\n— {rotulo}{nota}", parse_mode=constants.ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(linhas) if linhas else None,
                                      disable_web_page_preview=True)
    except BadRequest as e:
        logger.warning(f"Não consegui editar a mensagem do filtro: {e}")


async def _propor_regra(query, it: dict, alvo: str) -> None:
    dominio = it["endereco"].rsplit("@", 1)[-1]
    linha = [InlineKeyboardButton(f"✅ só {it['endereco']}"[:60], callback_data=f"ntf:ok:{it['id']}:{alvo}:e")]
    if dominio and dominio not in WEBMAIL:
        linha.append(InlineKeyboardButton(f"✅ todo @{dominio}"[:60], callback_data=f"ntf:ok:{it['id']}:{alvo}:d"))
    teclado = InlineKeyboardMarkup([linha, [InlineKeyboardButton("✖️ não", callback_data=f"ntf:no:{it['id']}")]])
    await query.message.reply_text(
        f"Gravar regra? E-mails de <b>{esc(it['remetente'])}</b> &lt;{esc(it['endereco'])}&gt; "
        f"passam a ir <b>{NOME_NIVEL[alvo]}</b>, sem passar pelo Gemini.",
        parse_mode=constants.ParseMode.HTML, reply_markup=teclado)


async def botao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ALLOWED_TELEGRAM_USER_ID:
        await query.answer("⛔ Acesso restrito.")
        return
    partes = query.data.split(":")
    acao = partes[1]

    if acao == "sil":
        de, a = (datetime.fromtimestamp(int(x), db.TZ).isoformat(timespec="seconds") for x in partes[2:4])
        itens = (await asyncio.to_thread(db.silenciados, de, a))[:SILENCIADOS_MAX]
        await query.answer()
        if not itens:
            await query.message.reply_text("Nenhum silenciado nesse intervalo (ou já foram apagados).")
            return
        linhas = [f"{n}. {esc(it["remetente"][:40])} · {esc(it["assunto"][:80])}" for n, it in enumerate(itens, 1)]
        botoes = [InlineKeyboardButton(f"{n} 👍", callback_data=f"ntf:up:{it['id']}") for n, it in enumerate(itens, 1)]
        await query.message.reply_text("🔇 <b>Silenciados</b>\n" + "\n".join(linhas), parse_mode=constants.ParseMode.HTML,
                                       reply_markup=InlineKeyboardMarkup([botoes[i:i + 5] for i in range(0, len(botoes), 5)]))
        return

    item_id = int(partes[2])
    it = await asyncio.to_thread(db.item, item_id)
    if not it:
        await query.answer("Esse e-mail já saiu do histórico (30 dias).")
        return

    if acao in ("up", "dn"):
        await asyncio.to_thread(db.set_feedback, item_id, acao.replace("dn", "down"))
        alvo = "agora" if acao == "up" else ABAIXO.get(it["nivel"])
        if alvo == it["nivel"] or alvo is None:
            await query.answer("Anotado.")
        else:
            await query.answer("Anotado. Quer gravar uma regra?")
            await _propor_regra(query, it, alvo)
        await _tirar_botoes(query, item_id, "👍 importante" if acao == "up" else "👎 ruído")
    elif acao == "ok":
        alvo, escopo = partes[3], partes[4]
        regra = it["endereco"] if escopo == "e" else "@" + it["endereco"].rsplit("@", 1)[-1]
        resultado = await asyncio.to_thread(regras.adicionar, regra, alvo)
        await query.answer(resultado)
        await query.edit_message_text(esc(resultado), parse_mode=constants.ParseMode.HTML)
    elif acao == "no":
        await query.answer("Sem regra.")
        await query.edit_message_text("Sem regra nova; só anotei o 👍/👎 para o balanço.")


async def filtro_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ALLOWED_TELEGRAM_USER_ID:
        return
    desde = db.get_estado("sombra_inicio") or db.now().replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    estado = "parado (autorização recusada)" if db.get_estado("gmail_revogado") == _token_mtime() else "lendo"
    texto = (texto_balanco(desde) + f"\n\nGmail: {estado} · Gemini hoje: {db.chamadas_hoje()} chamada(s)"
             + (" · modo sombra" if NOTIF_SOMBRA else ""))
    await update.message.reply_text(texto, parse_mode=constants.ParseMode.HTML)
