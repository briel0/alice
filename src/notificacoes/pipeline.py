"""Uma rodada do filtro: Gmail → regras → categorias → classificador → SQLite. Sem Telegram aqui.

Ordem de decisão de cada e-mail:
1. regra fixa do arquivo (remetente ou domínio), que vence tudo;
2. categoria do Gmail: Promoções, Social e Fóruns vão para silêncio sem Gemini;
3. Principal e Atualizações vão para o classificador, em lotes de até 30.
Sem cota do Gemini no dia, ou com o classificador falhando, o item vai para o resumo (nunca some).
"""
import logging
from datetime import datetime, timedelta

from src.config import NOTIF_GEMINI_LIMITE_DIA
from src.notificacoes import classificador, db, regras
from src.notificacoes.gmail import Gmail, HistoricoExpirado

logger = logging.getLogger(__name__)

SILENCIO_CATEGORIAS = {"promocoes": "Promoções", "social": "Social", "foruns": "Fóruns"}
HORAS_RESUMO = (12, 19)
SOMBRA_DIAS = 7
RELEITURA_DIAS = 2


def decidir(itens: list[dict], at: datetime | None = None, releitura: bool = False) -> list[dict]:
    """Preenche nivel, resumo e motivo de cada item (muda os dicts e devolve a mesma lista)."""
    fixas, criterios = regras.ler()
    para_gemini = []
    for it in itens:
        casou = regras.nivel_por_regra(it["endereco"], it["assunto"], fixas)
        if casou:
            it["nivel"], it["motivo"] = casou[0], f"regra: {casou[1]}"
        elif it["categoria"] in SILENCIO_CATEGORIAS:
            it["nivel"], it["motivo"] = "silencio", f"categoria {SILENCIO_CATEGORIAS[it['categoria']]}"
        else:
            para_gemini.append(it)
            continue
        it["resumo"] = it["assunto"][:classificador.RESUMO_MAX]

    for i in range(0, len(para_gemini), classificador.LOTE_MAX):
        lote = para_gemini[i:i + classificador.LOTE_MAX]
        resultado, motivo = None, "cota do classificador esgotada hoje"
        if db.chamadas_hoje(at) < NOTIF_GEMINI_LIMITE_DIA:
            db.contar_chamada(at)
            resultado = classificador.classificar(lote, criterios)
            motivo = "classificador indisponível"
        for j, it in enumerate(lote):
            if resultado:
                it.update(resultado[j])
                it["motivo"] = f"Gemini: {it['motivo']}"
            else:
                it["nivel"], it["resumo"], it["motivo"] = "resumo", it["assunto"][:classificador.RESUMO_MAX], motivo

    if releitura:
        # E-mails relidos depois de muito tempo fora do ar não disparam alerta: vão para o resumo
        for it in itens:
            if it["nivel"] == "agora":
                it["nivel"], it["motivo"] = "resumo", it["motivo"] + " (relido depois de um tempo fora do ar)"
    return itens


def corrigir(it: dict, certo: str, at: datetime | None = None) -> dict:
    """Anota a correção do usuário e prepara a proposta de ajuste (ainda sem gravar nada no arquivo de regras).
    Devolve {"id", "criterio", "trecho"}; criterio e trecho vêm vazios sem cota ou com o Gemini falhando."""
    db.set_feedback(it["id"], certo)
    sugestao = None
    if db.chamadas_hoje(at) < NOTIF_GEMINI_LIMITE_DIA:
        db.contar_chamada(at)
        sugestao = classificador.propor(it, certo)
    sugestao = sugestao or {"criterio": "", "trecho": ""}
    pid = db.nova_proposta(it["id"], certo, sugestao["criterio"], sugestao["trecho"], at)
    return {"id": pid, **sugestao}


def rodada(gmail: Gmail, at: datetime | None = None) -> int:
    """Busca o que chegou desde a última rodada e grava classificado. Devolve quantos itens novos entraram.
    Pode levantar gmail.TokenRevogado (quem chama avisa o usuário e para)."""
    at = at or db.now()
    history_id = db.get_estado("gmail_history_id")
    if history_id is None:
        # Primeira rodada: começa de agora, sem varrer a caixa antiga
        db.set_estado("gmail_history_id", gmail.history_id_atual())
        return 0

    releitura = False
    try:
        ids, novo_id = gmail.novos_desde(history_id)
    except HistoricoExpirado:
        logger.warning("historyId expirado: relendo os últimos %d dias sem alertas", RELEITURA_DIAS)
        novo_id = gmail.history_id_atual()
        ids, releitura = gmail.recentes(RELEITURA_DIAS), True

    vistos = db.ja_visto("gmail", ids)
    itens = [m for m in (gmail.mensagem(i) for i in ids if i not in vistos) if m]
    if itens:
        decidir(itens, at, releitura)
        db.inserir(itens, at)
    # Só avança depois de gravar: se algo falhar no meio, a próxima rodada pega de novo (repetidos são ignorados)
    db.set_estado("gmail_history_id", novo_id)
    return len(itens)


def ultimo_horario_resumo(at: datetime) -> datetime:
    """O horário de resumo mais recente que já chegou (12h ou 19h, hoje ou ontem)."""
    at = at.astimezone(db.TZ)
    for dia in (at, at - timedelta(days=1)):
        for hora in sorted(HORAS_RESUMO, reverse=True):
            slot = dia.replace(hour=hora, minute=0, second=0, microsecond=0)
            if slot <= at:
                return slot
    raise AssertionError("inalcançável")


def resumo_devido(at: datetime) -> datetime | None:
    """O horário de resumo que ainda não saiu, ou None. Na primeira vez só marca o horário atual."""
    slot = ultimo_horario_resumo(at)
    feito = db.get_estado("resumo_slot")
    if feito is None:
        db.set_estado("resumo_slot", slot.isoformat())
        db.set_estado("resumo_ate", at.isoformat(timespec="seconds"))
        return None
    return slot if datetime.fromisoformat(feito) < slot else None


def balanco_devido(at: datetime, sombra: bool) -> str | None:
    """Data de início do modo sombra quando o balanço da semana deve sair agora; None caso contrário."""
    if not sombra:
        return None
    inicio = db.get_estado("sombra_inicio")
    if inicio is None:
        db.set_estado("sombra_inicio", at.isoformat(timespec="seconds"))
        return None
    if db.get_estado("sombra_balanco") is None and at - datetime.fromisoformat(inicio) >= timedelta(days=SOMBRA_DIAS):
        return inicio
    return None
