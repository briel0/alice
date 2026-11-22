"""Lado do Telegram do filtro: alertas, resumos das 12h e 19h, botões de correção e balanço do modo sombra.

Cada e-mail mostra os níveis para onde ele poderia ter ido; apertar um quer dizer "devia ter ido para cá", e
não apertar nada quer dizer que o filtro acertou. Depois da correção, a ALICE propõe um ajuste (frase de
critério, regra remetente + assunto ou regra só por remetente), que só é gravado depois do ✅ do usuário.

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
NOME_NIVEL = {"agora": "na hora", "resumo": "no resumo", "silencio": "em silêncio"}
ROTULO = {"agora": "agora", "resumo": "resumo", "silencio": "silêncio"}
ICONE = {"agora": "🔔", "resumo": "📬", "silencio": "🔇"}
LEGENDA = {"agora": "🔔 devia avisar na hora", "resumo": "📬 devia ir para o resumo",
           "silencio": "🔇 nem precisava ver"}


def botao_nivel(item_id: int, nivel: str, n: int | None = None) -> InlineKeyboardButton:
    """Botão "devia ter ido para `nivel`"; com n, a versão curta numerada das listas."""
    texto = f"{n} {ICONE[nivel]}" if n is not None else f"{ICONE[nivel]} {ROTULO[nivel]}"
    return InlineKeyboardButton(texto, callback_data=f"ntf:mv:{item_id}:{nivel}")


def legenda(*niveis: str) -> str:
    return "<i>Corrigir: " + " · ".join(LEGENDA[n] for n in niveis) + "</i>"


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
        [botao_nivel(it["id"], "resumo"), botao_nivel(it["id"], "silencio")],
        [InlineKeyboardButton("Abrir no Gmail", url=it["link"])],
    ])


def mensagens_resumo(itens: list[dict], silenciados: list[dict], desde: str, ate: str) -> list[tuple[str, InlineKeyboardMarkup | None]]:
    """O resumo em uma ou mais mensagens: agrupado por remetente, correção por item, silenciados no rodapé."""
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
            if itens:
                linhas.append(legenda("agora", "silencio"))
        for n, it in enumerate(pedaco, inicio + 1):
            chave = it["endereco"] or it["remetente"]
            if chave != anterior:
                qtd = len(grupos[chave])
                linhas.append(f"\n<b>{esc(it['remetente'])}</b>" + (f" ({qtd})" if qtd > 1 else ""))
                anterior = chave
            linhas.append(f"{n}. {esc(it['resumo'])} · <a href=\"{esc(it['link'])}\">abrir</a>")
            botoes += [botao_nivel(it["id"], "agora", n), botao_nivel(it["id"], "silencio", n)]
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
    linhas = [f"{prefixo()}📊 <b>Balanço do filtro</b> desde {datetime.fromisoformat(desde):%d/%m}"]
    for nivel, dados in b.items():
        linha = f"• {NOME_NIVEL[nivel]}: {dados['total']} · corrigidos: {dados['corrigidos']}"
        if dados["para"]:
            linha += " (" + ", ".join(f"→ {ROTULO[d]} {n}" for d, n in dados["para"].items()) + ")"
        linhas.append(linha)
    linhas.append("\nSe estiver bom: desligue as notificações do Gmail no celular e ponha <code>NOTIF_SOMBRA=0</code> "
                  "no alice.env (reinicie a ALICE). Se não, continue corrigindo pelos botões.")
    return "\n".join(linhas)


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
    """Tira da mensagem os botões de correção desse item e anota o que aconteceu (como nos lembretes)."""
    message = query.message
    if not isinstance(message, Message) or not message.reply_markup:
        return
    rotulo, linhas = "", []
    for linha in message.reply_markup.inline_keyboard:
        mantidos = []
        for b in linha:
            if (b.callback_data or "").startswith(f"ntf:mv:{item_id}:"):
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


def texto_proposta(it: dict, certo: str, prop: dict) -> tuple[str, InlineKeyboardMarkup]:
    """A proposta de ajuste depois de uma correção: o texto mostra por inteiro o que seria gravado."""
    endereco = esc(it["endereco"])
    linhas = [f"✏️ Corrigido: <b>{esc(it['remetente'])}</b> · {esc(it['assunto'][:80])} → <b>{NOME_NIVEL[certo]}</b>.",
              "Gravar um ajuste? Nada muda sem o ✅.", ""]
    botoes = []
    if prop["criterio"]:
        linhas.append(f"• <b>Critério</b> (vai para o Gemini, vale para qualquer remetente): "
                      f"“{esc(prop['criterio'])}” → {ROTULO[certo]}")
        botoes.append([InlineKeyboardButton("✅ critério", callback_data=f"ntf:pc:{prop['id']}")])
    if prop["trecho"]:
        linhas.append(f"• <b>Remetente + assunto</b> (sem Gemini): <code>{endereco}</code> com "
                      f"“{esc(prop['trecho'])}” no assunto")
        botoes.append([InlineKeyboardButton("✅ remetente + assunto", callback_data=f"ntf:pt:{prop['id']}")])
    linhas.append(f"• <b>Só remetente</b> (sem Gemini): tudo de <code>{endereco}</code>")
    botoes.append([InlineKeyboardButton("✅ só remetente", callback_data=f"ntf:pe:{prop['id']}")])
    if not prop["criterio"] and not prop["trecho"]:
        linhas.append("\n<i>Sem sugestão de critério nem de trecho (Gemini indisponível, sem cota ou sem um trecho "
                      "fixo no assunto).</i>")
    botoes.append([InlineKeyboardButton("✖️ não", callback_data=f"ntf:px:{prop['id']}")])
    return "\n".join(linhas), InlineKeyboardMarkup(botoes)


async def _corrigir(query, it: dict, certo: str) -> None:
    await query.answer("Anotado.")
    await _tirar_botoes(query, it["id"], f"{ICONE[certo]} devia ir {NOME_NIVEL[certo]}")
    prop = await asyncio.to_thread(pipeline.corrigir, it, certo)
    texto, teclado = texto_proposta(it, certo, prop)
    await query.message.reply_text(texto, parse_mode=constants.ParseMode.HTML, reply_markup=teclado)


async def _aplicar(query, acao: str, proposta_id: int) -> None:
    prop = await asyncio.to_thread(db.proposta, proposta_id)
    it = prop and await asyncio.to_thread(db.item, prop["item_id"])
    # Apagar antes de gravar: um segundo toque no mesmo botão não grava duas vezes
    if not prop or not await asyncio.to_thread(db.apagar_proposta, proposta_id):
        await query.answer("Essa proposta já foi usada ou expirou.")
        return
    if acao == "px" or not it:
        resultado = "Sem ajuste; a correção ficou anotada para o balanço."
    elif acao == "pc":
        resultado = await asyncio.to_thread(regras.adicionar_criterio, prop["criterio"], prop["nivel"])
    else:
        trecho = prop["trecho"] if acao == "pt" else ""
        resultado = await asyncio.to_thread(regras.adicionar, it["endereco"], trecho, prop["nivel"])
    await query.answer(resultado[:200])
    await query.edit_message_text(esc(resultado), parse_mode=constants.ParseMode.HTML)


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
        botoes = [b for n, it in enumerate(itens, 1) for b in (botao_nivel(it["id"], "agora", n),
                                                               botao_nivel(it["id"], "resumo", n))]
        await query.message.reply_text(
            "🔇 <b>Silenciados</b>\n" + legenda("agora", "resumo") + "\n\n" + "\n".join(linhas),
            parse_mode=constants.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([botoes[i:i + 4] for i in range(0, len(botoes), 4)]))
        return

    if acao == "mv" and len(partes) == 4 and partes[3] in db.NIVEIS:
        it = await asyncio.to_thread(db.item, int(partes[2]))
        if not it:
            await query.answer("Esse e-mail já saiu do histórico (30 dias).")
        elif partes[3] == it["nivel"]:
            await query.answer("Ele já está nesse nível.")
        else:
            await _corrigir(query, it, partes[3])
    elif acao in ("pc", "pt", "pe", "px"):
        await _aplicar(query, acao, int(partes[2]))
    else:
        # Botões 👍/👎 do formato anterior, em mensagens antigas
        await query.answer("Botão de um formato antigo; use os das mensagens novas.")


async def filtro_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ALLOWED_TELEGRAM_USER_ID:
        return
    desde = db.get_estado("sombra_inicio") or db.now().replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    estado = "parado (autorização recusada)" if db.get_estado("gmail_revogado") == _token_mtime() else "lendo"
    texto = (texto_balanco(desde) + f"\n\nGmail: {estado} · Gemini hoje: {db.chamadas_hoje()} chamada(s)"
             + (" · modo sombra" if NOTIF_SOMBRA else ""))
    await update.message.reply_text(texto, parse_mode=constants.ParseMode.HTML)
