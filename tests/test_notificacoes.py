import ast
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.notificacoes import classificador, db, pipeline, regras
from src.notificacoes.gmail import HistoricoExpirado, mascarar_codigos

TZ = db.TZ
AGORA = datetime(2026, 11, 20, 14, 0, tzinfo=TZ)
RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "NOTIF_DB_PATH", tmp_path / "notif.db")
    monkeypatch.setattr(regras, "NOTIF_RULES_FILE", tmp_path / "regras.md")
    commits = []
    monkeypatch.setattr(regras, "commit_data_file", lambda path, msg: commits.append(msg))
    return commits


def email(i="m1", endereco="alguem@exemplo.com", categoria="principal", assunto="Oi"):
    return {"fonte": "gmail", "ext_id": i, "remetente": "Alguém", "endereco": endereco, "assunto": assunto,
            "categoria": categoria, "trecho": "trecho", "link": f"https://mail.google.com/mail/u/0/#all/{i}",
            "recebido_em": AGORA.isoformat()}


# --- Fronteira (regra inegociável do item 14) ---

def _imports(arquivo: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
            nomes |= {f"{no.module}.{a.name}" for a in no.names}
    return nomes


def test_pacote_nao_importa_o_agente():
    proibidos = ("src.agent", "src.history", "src.mcp_server", "src.cli", "src.bot")
    for arquivo in (RAIZ / "src" / "notificacoes").glob("*.py"):
        ruins = {n for n in _imports(arquivo) if n.startswith(proibidos)}
        assert not ruins, f"{arquivo.name} importa {ruins}"


def test_agente_nao_importa_o_pacote():
    for nome in ("agent.py", "history.py", "mcp_server.py", "cli.py"):
        ruins = {n for n in _imports(RAIZ / "src" / nome) if n.startswith("src.notificacoes")}
        assert not ruins, f"{nome} importa {ruins}"


def test_classificador_sem_ferramentas(monkeypatch):
    capturado = {}

    class Falso:
        def __init__(self, **kw):
            self.models = self

        def generate_content(self, model, contents, config):
            capturado["config"] = config
            return type("R", (), {"text": json.dumps([{"id": 0, "nivel": "resumo", "resumo": "x", "motivo": "y"}])})()

    monkeypatch.setattr(classificador.genai, "Client", Falso)
    assert classificador.classificar([email()], "") == [{"nivel": "resumo", "resumo": "x", "motivo": "y"}]
    assert not capturado["config"].tools


# --- Regras ---

def test_regras_endereco_vence_dominio_e_nivel_mais_alto_desempata():
    regras.NOTIF_RULES_FILE.write_text(
        "## Avisar na hora\n- chefe@empresa.com\n- @banco.com\n\n## Silêncio\n- @empresa.com\n- @banco.com\n"
        "\n## Critérios\n- isto@nao.com é texto\n", encoding="utf-8")
    fixas, criterios = regras.ler()
    assert regras.nivel_por_regra("Chefe@Empresa.com", fixas) == ("agora", "chefe@empresa.com")
    assert regras.nivel_por_regra("rh@empresa.com", fixas) == ("silencio", "@empresa.com")
    assert regras.nivel_por_regra("x@avisos.banco.com", fixas) == ("agora", "@banco.com")
    assert regras.nivel_por_regra("x@outrobanco.com", fixas) is None
    assert "isto@nao.com" not in fixas and "texto" in criterios


def test_adicionar_regra_move_de_secao(isolado):
    regras.NOTIF_RULES_FILE.write_text("## Avisar na hora\n\n## Silêncio\n- loja@x.com\n\n## Critérios\nc\n",
                                       encoding="utf-8")
    assert "gravada" in regras.adicionar("loja@x.com", "agora")
    fixas, criterios = regras.ler()
    assert fixas == {"loja@x.com": "agora"} and criterios == "c"
    assert isolado and "loja@x.com" in isolado[0]
    assert regras.adicionar("não é endereço", "agora") == "Regra inválida."


def test_sem_arquivo_usa_exemplo():
    fixas, criterios = regras.ler()
    assert fixas == {} and "Segurança da conta" in criterios


# --- Gmail ---

def test_mascara_codigos_so_com_contexto():
    assert mascarar_codigos("Seu código é 482913") == "Seu código é ••••"
    assert mascarar_codigos("Your verification code: G-123456") == "Your verification code: ••••"
    assert mascarar_codigos("Pedido 482913 enviado") == "Pedido 482913 enviado"


# --- Classificador ---

def test_validar_aceita_so_o_formato_exato():
    ok = json.dumps([{"id": 1, "nivel": "agora", "resumo": "a" * 300, "motivo": "m"},
                     {"id": 0, "nivel": "silencio", "resumo": "b", "motivo": "m"}])
    [r0, r1] = classificador.validar(ok, 2)
    assert r0["nivel"] == "silencio" and len(r1["resumo"]) == classificador.RESUMO_MAX
    assert classificador.validar(ok, 3) is None
    assert classificador.validar("não é json", 1) is None
    assert classificador.validar(json.dumps([{"id": 0, "nivel": "urgente", "resumo": "", "motivo": ""}]), 1) is None
    assert classificador.validar(json.dumps([{"id": 0, "nivel": "agora", "resumo": "", "motivo": ""}] * 2), 2) is None


def test_entrada_corta_cada_item():
    longo = email(assunto="x" * 2000)
    linha = json.loads(classificador.entrada([longo]))
    assert len(linha["email"]) == classificador.TEXTO_MAX


# --- Pipeline ---

def test_decidir_regra_categoria_e_gemini(monkeypatch):
    regras.NOTIF_RULES_FILE.write_text("## Avisar na hora\n- @promo.com\n", encoding="utf-8")
    chamados = []

    def falso(itens, criterios):
        chamados.append([i["ext_id"] for i in itens])
        return [{"nivel": "agora", "resumo": "r", "motivo": "m"} for _ in itens]

    monkeypatch.setattr(classificador, "classificar", falso)
    itens = pipeline.decidir([
        email("a", "x@promo.com", "promocoes"),   # regra vence a categoria
        email("b", "y@loja.com", "promocoes"),    # categoria → silêncio, sem Gemini
        email("c", "z@site.com", "atualizacoes"),  # Gemini
    ], AGORA)
    assert [i["nivel"] for i in itens] == ["agora", "silencio", "agora"]
    assert itens[0]["motivo"] == "regra: @promo.com" and itens[2]["motivo"] == "Gemini: m"
    assert chamados == [["c"]] and db.chamadas_hoje(AGORA) == 1


def test_decidir_sem_cota_ou_com_falha_vai_para_resumo(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c: None)
    [it] = pipeline.decidir([email()], AGORA)
    assert it["nivel"] == "resumo" and it["motivo"] == "classificador indisponível"

    monkeypatch.setattr(pipeline, "NOTIF_GEMINI_LIMITE_DIA", 1)
    [it] = pipeline.decidir([email("m2")], AGORA)
    assert it["nivel"] == "resumo" and "cota" in it["motivo"]


def test_decidir_lotes_de_30(monkeypatch):
    tamanhos = []
    monkeypatch.setattr(classificador, "classificar",
                        lambda itens, c: tamanhos.append(len(itens)) or [{"nivel": "resumo", "resumo": "", "motivo": ""}] * len(itens))
    pipeline.decidir([email(str(i)) for i in range(65)], AGORA)
    assert tamanhos == [30, 30, 5]


def test_releitura_nao_alerta(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c: [{"nivel": "agora", "resumo": "", "motivo": "m"}])
    [it] = pipeline.decidir([email()], AGORA, releitura=True)
    assert it["nivel"] == "resumo" and "relido" in it["motivo"]


class GmailFalso:
    def __init__(self, ids=(), expirado=False):
        self.ids, self.expirado = list(ids), expirado

    def history_id_atual(self):
        return "900"

    def novos_desde(self, hid):
        if self.expirado:
            raise HistoricoExpirado()
        return self.ids, "200"

    def recentes(self, dias):
        return self.ids

    def mensagem(self, i):
        return email(i)


def test_rodada_comeca_de_agora_e_ignora_repetidos(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c: [{"nivel": "agora", "resumo": "", "motivo": ""}] * len(itens))
    assert pipeline.rodada(GmailFalso(["a"]), AGORA) == 0  # primeira: só guarda o historyId
    assert db.get_estado("gmail_history_id") == "900"
    assert pipeline.rodada(GmailFalso(["a", "b"]), AGORA) == 2
    assert pipeline.rodada(GmailFalso(["a", "b"]), AGORA) == 0
    assert db.get_estado("gmail_history_id") == "200"
    assert len(db.alertas_pendentes()) == 2


def test_rodada_com_historico_expirado_rele_sem_alerta(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c: [{"nivel": "agora", "resumo": "", "motivo": ""}] * len(itens))
    db.set_estado("gmail_history_id", "1")
    assert pipeline.rodada(GmailFalso(["a"], expirado=True), AGORA) == 1
    assert db.alertas_pendentes() == [] and len(db.resumo_pendente()) == 1
    assert db.get_estado("gmail_history_id") == "900"


def test_horarios_de_resumo():
    assert pipeline.ultimo_horario_resumo(AGORA).hour == 12
    assert pipeline.ultimo_horario_resumo(AGORA.replace(hour=19, minute=5)).hour == 19
    cedo = pipeline.ultimo_horario_resumo(AGORA.replace(hour=8))
    assert (cedo.day, cedo.hour) == (19, 19)

    assert pipeline.resumo_devido(AGORA) is None  # primeira vez só marca
    assert pipeline.resumo_devido(AGORA + timedelta(hours=2)) is None
    slot = pipeline.resumo_devido(AGORA + timedelta(hours=6))
    assert slot.hour == 19


def test_balanco_sai_uma_vez_depois_de_7_dias():
    assert pipeline.balanco_devido(AGORA, sombra=True) is None
    assert pipeline.balanco_devido(AGORA + timedelta(days=6), sombra=True) is None
    assert pipeline.balanco_devido(AGORA + timedelta(days=7), sombra=True) == AGORA.isoformat(timespec="seconds")
    assert pipeline.balanco_devido(AGORA + timedelta(days=7), sombra=False) is None


def test_itens_velhos_sao_apagados():
    extra = {"nivel": "resumo", "resumo": "", "motivo": ""}
    db.inserir([email("velho") | extra], AGORA - timedelta(days=31))
    db.inserir([email("novo") | extra], AGORA)
    assert db.ja_visto("gmail", ["velho", "novo"]) == {"novo"}
