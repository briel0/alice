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

def test_regras_assunto_vence_remetente_e_nivel_mais_alto_desempata():
    regras.NOTIF_RULES_FILE.write_text(
        "## Avisar na hora\n- chefe@empresa.com\n- banco@x.com | compra NÃO reconhecida\n\n"
        "## Resumo diário\n- banco@x.com\n\n"
        "## Silêncio\n- banco@x.com | Pix   foi enviado\n- banco@x.com | pix foi\n- @dominio.com\n"
        "\n## Critérios\n- isto@nao.com é texto\n", encoding="utf-8")
    fixas, criterios = regras.ler()
    assert regras.nivel_por_regra("Chefe@Empresa.com", "Oi", fixas) == ("agora", "chefe@empresa.com")
    assert regras.nivel_por_regra("banco@x.com", "Seu PIX foi enviado: R$ 10", fixas) == \
        ("silencio", "banco@x.com | pix foi enviado")  # o trecho mais longo desempata no mesmo nível
    assert regras.nivel_por_regra("banco@x.com", "Pix foi enviado? Compra não reconhecida", fixas)[0] == "agora"
    assert regras.nivel_por_regra("banco@x.com", "Sua fatura fechou", fixas) == ("resumo", "banco@x.com")
    assert regras.nivel_por_regra("rh@dominio.com", "Oi", fixas) is None  # regra por domínio não existe mais
    assert ("isto@nao.com", "") not in fixas and "texto" in criterios


def test_adicionar_regra_move_de_secao(isolado):
    regras.NOTIF_RULES_FILE.write_text(
        "## Avisar na hora\n\n## Silêncio\n- loja@x.com\n- loja@x.com | Pedido enviado\n\n"
        "## Critérios\n- loja@x.com | pedido enviado (texto, não regra)\n", encoding="utf-8")
    assert "gravada" in regras.adicionar("loja@x.com", "", "agora")
    assert "gravada" in regras.adicionar("Loja@X.com", "  pedido   ENVIADO ", "resumo")
    fixas, criterios = regras.ler()
    assert fixas == {("loja@x.com", ""): "agora", ("loja@x.com", "pedido enviado"): "resumo"}
    assert "(texto, não regra)" in criterios  # a seção de critérios nunca é mexida
    assert "- loja@x.com | pedido ENVIADO" in regras.NOTIF_RULES_FILE.read_text(encoding="utf-8")
    assert len(isolado) == 2 and "loja@x.com" in isolado[0]
    assert regras.adicionar("não é endereço", "", "agora") == "Regra inválida."
    assert regras.adicionar("@x.com", "", "agora") == "Regra inválida."
    assert regras.adicionar("loja@x.com", "a|b c", "agora") == "Regra inválida."


def test_adicionar_criterio_no_fim_dos_criterios(isolado):
    regras.NOTIF_RULES_FILE.write_text("## Silêncio\n\n## Critérios\n\nAvisar na hora:\n- prazo\n\n\n## Outra\nx\n",
                                       encoding="utf-8")
    assert "gravado" in regras.adicionar_criterio("Comprovante de Pix feito pelo próprio usuário", "silencio")
    assert "gravado" in regras.adicionar_criterio("Débito automático já agendado", "resumo")
    texto = regras.NOTIF_RULES_FILE.read_text(encoding="utf-8")
    assert texto.index(regras.CORRECOES) < texto.index("Pix feito") < texto.index("Débito") < texto.index("## Outra")
    assert texto.count(regras.CORRECOES) == 1
    _, criterios = regras.ler()
    assert "- Comprovante de Pix feito pelo próprio usuário → Silêncio" in criterios
    assert "- Débito automático já agendado → Resumo diário" in criterios
    assert regras.adicionar_criterio("curta", "agora") == "Critério inválido."
    assert regras.adicionar_criterio("x" * 200, "agora") == "Critério inválido."
    assert len(isolado) == 2


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


def test_validar_proposta_confere_trecho_no_assunto():
    assunto = "Seu Pix foi enviado: R$ 86,34"
    ok = classificador.validar_proposta(json.dumps({"criterio": "Comprovante de Pix feito pelo usuário",
                                                    "trecho": "pix  foi enviado"}), assunto)
    assert ok == {"criterio": "Comprovante de Pix feito pelo usuário", "trecho": "pix foi enviado"}
    inventado = classificador.validar_proposta(json.dumps({"criterio": "x" * 300, "trecho": "Pix recebido"}), assunto)
    assert inventado == {"criterio": "", "trecho": ""}
    assert classificador.validar_proposta("[]", assunto) is None
    assert classificador.validar_proposta("não é json", assunto) is None


def test_propor_sem_ferramentas(monkeypatch):
    capturado = {}

    class Falso:
        def __init__(self, **kw):
            self.models = self

        def generate_content(self, model, contents, config):
            capturado["config"] = config
            return type("R", (), {"text": json.dumps({"criterio": "Recibo de compra feita", "trecho": "Oi"})})()

    monkeypatch.setattr(classificador.genai, "Client", Falso)
    it = email() | {"nivel": "agora"}
    assert classificador.propor(it, "silencio") == {"criterio": "Recibo de compra feita", "trecho": ""}  # curto
    assert not capturado["config"].tools
    assert "avisar na hora" in capturado["config"].system_instruction


def test_entrada_corta_cada_item():
    longo = email(assunto="x" * 2000)
    linha = json.loads(classificador.entrada([longo]))
    assert len(linha["email"]) == classificador.TEXTO_MAX


# --- Pipeline ---

def test_decidir_regra_categoria_e_gemini(monkeypatch):
    regras.NOTIF_RULES_FILE.write_text("## Avisar na hora\n- x@promo.com\n", encoding="utf-8")
    chamados = []

    def falso(itens, criterios, at=None):
        chamados.append([i["ext_id"] for i in itens])
        return [{"nivel": "agora", "resumo": "r", "motivo": "m"} for _ in itens]

    monkeypatch.setattr(classificador, "classificar", falso)
    itens = pipeline.decidir([
        email("a", "x@promo.com", "promocoes"),   # regra vence a categoria
        email("b", "y@loja.com", "promocoes"),    # categoria → silêncio, sem Gemini
        email("c", "z@site.com", "atualizacoes"),  # Gemini
    ], AGORA)
    assert [i["nivel"] for i in itens] == ["agora", "silencio", "agora"]
    assert itens[0]["motivo"] == "regra: x@promo.com" and itens[2]["motivo"] == "Gemini: m"
    assert chamados == [["c"]] and db.chamadas_hoje(AGORA) == 1


def test_decidir_sem_cota_ou_com_falha_vai_para_resumo(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c, at=None: None)
    [it] = pipeline.decidir([email()], AGORA)
    assert it["nivel"] == "resumo" and it["motivo"] == "classificador indisponível"

    monkeypatch.setattr(pipeline, "NOTIF_GEMINI_LIMITE_DIA", 1)
    [it] = pipeline.decidir([email("m2")], AGORA)
    assert it["nivel"] == "resumo" and "cota" in it["motivo"]


def test_decidir_lotes_de_30(monkeypatch):
    tamanhos = []
    monkeypatch.setattr(classificador, "classificar",
                        lambda itens, c, at=None: tamanhos.append(len(itens)) or [{"nivel": "resumo", "resumo": "", "motivo": ""}] * len(itens))
    pipeline.decidir([email(str(i)) for i in range(65)], AGORA)
    assert tamanhos == [30, 30, 5]


def test_releitura_nao_alerta(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c, at=None: [{"nivel": "agora", "resumo": "", "motivo": "m"}])
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
    monkeypatch.setattr(classificador, "classificar", lambda itens, c, at=None: [{"nivel": "agora", "resumo": "", "motivo": ""}] * len(itens))
    assert pipeline.rodada(GmailFalso(["a"]), AGORA) == 0  # primeira: só guarda o historyId
    assert db.get_estado("gmail_history_id") == "900"
    assert pipeline.rodada(GmailFalso(["a", "b"]), AGORA) == 2
    assert pipeline.rodada(GmailFalso(["a", "b"]), AGORA) == 0
    assert db.get_estado("gmail_history_id") == "200"
    assert len(db.alertas_pendentes()) == 2


def test_rodada_com_historico_expirado_rele_sem_alerta(monkeypatch):
    monkeypatch.setattr(classificador, "classificar", lambda itens, c, at=None: [{"nivel": "agora", "resumo": "", "motivo": ""}] * len(itens))
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


# --- Correções ---

def _gravado(nivel="agora", i="m1", **kw):
    [item_id] = db.inserir([email(i, **kw) | {"nivel": nivel, "resumo": "r", "motivo": "m"}], AGORA)
    return db.item(item_id)


def test_corrigir_anota_e_guarda_proposta(monkeypatch):
    pedidos = []
    monkeypatch.setattr(classificador, "propor",
                        lambda it, certo: pedidos.append(certo) or {"criterio": "Recibo qualquer", "trecho": "Oi"})
    it = _gravado("agora")
    prop = pipeline.corrigir(it, "silencio", AGORA)
    assert prop["criterio"] == "Recibo qualquer" and pedidos == ["silencio"]
    assert db.item(it["id"])["feedback"] == "silencio" and db.chamadas_hoje(AGORA) == 1
    guardada = db.proposta(prop["id"])
    assert guardada["nivel"] == "silencio" and guardada["item_id"] == it["id"]
    assert db.apagar_proposta(prop["id"]) and not db.apagar_proposta(prop["id"])


def test_corrigir_sem_cota_nao_chama_gemini(monkeypatch):
    monkeypatch.setattr(pipeline, "NOTIF_GEMINI_LIMITE_DIA", 0)
    monkeypatch.setattr(classificador, "propor", lambda it, certo: pytest.fail("não devia chamar o Gemini"))
    prop = pipeline.corrigir(_gravado("resumo"), "agora", AGORA)
    assert prop["criterio"] == "" and prop["trecho"] == ""


def test_balanco_conta_correcoes_por_destino():
    a, b, c = _gravado("agora", "a"), _gravado("resumo", "b"), _gravado("resumo", "c")
    db.set_feedback(a["id"], "resumo")
    db.set_feedback(b["id"], "silencio")
    db.set_feedback(c["id"], "resumo")  # igual ao nível: não conta como correção
    bal = db.balanco((AGORA - timedelta(days=1)).isoformat())
    assert bal["agora"] == {"total": 1, "corrigidos": 1, "para": {"resumo": 1}}
    assert bal["resumo"] == {"total": 2, "corrigidos": 1, "para": {"silencio": 1}}
    assert bal["silencio"]["total"] == 0


def test_botoes_mostram_so_os_outros_niveis():
    from src.notificacoes import telegram as tg
    it = _gravado("agora")
    dados = [b.callback_data for linha in tg.botoes_alerta(it).inline_keyboard for b in linha if b.callback_data]
    assert dados == [f"ntf:mv:{it['id']}:resumo", f"ntf:mv:{it['id']}:silencio"]

    r = _gravado("resumo", "r")
    [(texto, teclado, ids)] = tg.mensagens_resumo([r], [], AGORA.isoformat(), AGORA.isoformat())
    assert ids == [r["id"]]
    dados = [b.callback_data for linha in teclado.inline_keyboard for b in linha]
    assert dados == [f"ntf:mv:{r['id']}:agora", f"ntf:mv:{r['id']}:silencio"] and "Corrigir" in texto
    assert all(len(d.encode()) <= 64 for d in dados)


def test_proposta_mostra_o_que_seria_gravado():
    from src.notificacoes import telegram as tg
    it = _gravado("resumo")
    texto, teclado = tg.texto_proposta(it, "silencio", {"id": 7, "criterio": "Recibo <b>", "trecho": "Oi"})
    assert "Recibo &lt;b&gt;" in texto and "“Oi”" in texto
    assert [l[0].callback_data for l in teclado.inline_keyboard] == ["ntf:pc:7", "ntf:pt:7", "ntf:pe:7", "ntf:px:7"]
    _, teclado = tg.texto_proposta(it, "silencio", {"id": 8, "criterio": "", "trecho": ""})
    assert [l[0].callback_data for l in teclado.inline_keyboard] == ["ntf:pe:8", "ntf:px:8"]


# --- Data para o classificador, links e resumo longo ---

def test_classificador_recebe_data_de_agora_e_de_chegada(monkeypatch):
    capturado = {}

    class Falso:
        def __init__(self, **kw):
            self.models = self

        def generate_content(self, model, contents, config):
            capturado["instrucao"], capturado["conteudo"] = config.system_instruction, contents
            return type("R", (), {"text": json.dumps([{"id": 0, "nivel": "resumo", "resumo": "x", "motivo": "y"}])})()

    monkeypatch.setattr(classificador.genai, "Client", Falso)
    # Recebido em UTC: aparece no fuso do usuário
    it = email() | {"recebido_em": "2026-11-18T12:30:00+00:00"}
    classificador.classificar([it], "", AGORA)
    assert "sex 20/11/2026 14:00" in capturado["instrucao"]
    assert "Recebido: qua 18/11/2026 09:30" in json.loads(capturado["conteudo"])["email"]


def test_pipeline_passa_o_horario_ao_classificador(monkeypatch):
    vistos = []
    monkeypatch.setattr(classificador, "classificar",
                        lambda itens, c, at=None: vistos.append(at) or [{"nivel": "resumo", "resumo": "", "motivo": ""}])
    pipeline.decidir([email()], AGORA)
    assert vistos == [AGORA]


def test_links_do_email_nao_ficam_clicaveis():
    from src.notificacoes import telegram as tg
    it = _gravado("agora") | {"assunto": "Acesse https://banco-falso.com/login já", "resumo": "Veja em site.com.br",
                              "motivo": "m", "remetente": "Loja.com"}
    texto = tg.texto_alerta(it)
    for dominio in ("banco-falso.com", "site.com.br", "Loja.com", "https://"):
        assert dominio not in texto
    assert "banco-falso․com/login" in texto and "R$ 86,34" in tg.esc("R$ 86,34")


def test_resumo_longo_quebra_por_tamanho_e_repete_o_remetente():
    from src.notificacoes import telegram as tg
    itens = [_gravado("resumo", f"r{i}") | {"remetente": f"Remetente {i} " + "n" * 70, "endereco": f"a{i}@x.com",
                                           "resumo": "r" * 120} for i in range(14)]
    itens += [_gravado("resumo", f"s{i}") | {"remetente": "Mesmo", "endereco": "mesmo@x.com", "resumo": "s"}
              for i in range(20)]
    partes = tg.mensagens_resumo(itens, [], AGORA.isoformat(), AGORA.isoformat())
    assert all(len(t) <= tg.TEXTO_MAX_MENSAGEM for t, _, _ in partes)
    assert all(len(ids) <= tg.ITENS_POR_MENSAGEM for _, _, ids in partes)
    assert [i for _, _, ids in partes for i in ids] == [it["id"] for it in itens]
    # Toda mensagem depois da primeira começa com o nome de um remetente
    assert all(t.startswith("<b>") for t, _, _ in partes[1:])


def test_resumo_vazio_so_com_silenciados():
    from src.notificacoes import telegram as tg
    s = _gravado("silencio", "q")
    [(texto, teclado, ids)] = tg.mensagens_resumo([], [s], AGORA.isoformat(), (AGORA + timedelta(hours=1)).isoformat())
    assert texto.startswith("🧪 📬 <b>Resumo · nada para ver</b>") or texto.startswith("📬 <b>Resumo · nada para ver</b>")
    assert "0 e-mail" not in texto and ids == [] and "ver silenciados" in str(teclado)

