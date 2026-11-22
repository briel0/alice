"""Item 22 do backlog: a ALICE não pode confirmar uma gravação que não aconteceu."""
import pytest
from google.genai import types

from src import agent


def texto(t: str):
    """Resposta do modelo só com texto."""
    content = types.Content(role="model", parts=[types.Part.from_text(text=t)])
    return type("R", (), {"function_calls": None, "text": t, "candidates": [type("C", (), {"content": content})()]})()


def chamada(nome: str, **args):
    """Resposta do modelo que chama uma ferramenta."""
    fc = types.FunctionCall(name=nome, args=args)
    content = types.Content(role="model", parts=[types.Part(function_call=fc)])
    return type("R", (), {"function_calls": [fc], "text": None, "candidates": [type("C", (), {"content": content})()]})()


@pytest.fixture
def gemini(monkeypatch):
    """Gemini falso que devolve as respostas da fila, na ordem, e guarda o que recebeu."""
    estado = {"fila": [], "pedidos": [], "ferramentas": []}

    class Falso:
        def __init__(self, **kw):
            self.models = self

        def generate_content(self, model, contents, config):
            estado["pedidos"].append(list(contents))
            return estado["fila"].pop(0)

    monkeypatch.setattr(agent.genai, "Client", Falso)
    monkeypatch.setattr(agent, "available_tools", lambda: [])
    monkeypatch.setattr(agent, "execute_tool",
                        lambda nome, args: estado["ferramentas"].append(nome) or f"{nome} ok: agora tem 4 séries")
    return estado


def rodar() -> str:
    return agent._process_with_gemini("leg press 160kg 8 reps", None, "", "sistema", [])


def test_confirmacao_sem_ferramenta_volta_ao_modelo_e_ele_grava(gemini):
    gemini["fila"] = [texto("Registrei mais 1 série de Leg press (total de 4 séries)."),
                      chamada("log_exercise", exercise="leg press"),
                      texto("Registrei 1 série de Leg press 45°: agora são 4.")]
    assert rodar() == "Registrei 1 série de Leg press 45°: agora são 4."
    assert gemini["ferramentas"] == ["log_exercise"]
    aviso = gemini["pedidos"][1][-1].parts[0].text
    assert aviso == agent.NO_WRITE_NUDGE


def test_confirmacao_falsa_insistente_vira_aviso(gemini):
    gemini["fila"] = [texto("Registrei mais 1 série."), texto("Anotei a série, total de 4.")]
    assert rodar() == agent.NO_WRITE_WARNING
    assert gemini["ferramentas"] == []


def test_confirmacao_depois_da_ferramenta_passa_direto(gemini):
    gemini["fila"] = [chamada("log_exercise", exercise="leg press"), texto("Registrei 1 série de Leg press.")]
    assert rodar() == "Registrei 1 série de Leg press."
    assert len(gemini["pedidos"]) == 2


def test_resposta_sem_afirmar_gravacao_passa_direto(gemini):
    gemini["fila"] = [texto("Qual foi a carga?")]
    assert rodar() == "Qual foi a carga?"
    assert len(gemini["pedidos"]) == 1


def test_ferramenta_de_leitura_nao_vale_como_gravacao(gemini):
    gemini["fila"] = [chamada("get_current_tasks"), texto("Anotei no INBOX."), texto("Anotei, pode deixar.")]
    assert rodar() == agent.NO_WRITE_WARNING


def test_rodadas_esgotadas_mostram_o_que_foi_gravado(gemini, monkeypatch):
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 2)
    gemini["fila"] = [chamada("log_exercise", exercise="a"), chamada("log_exercise", exercise="b")]
    resposta = rodar()
    assert resposta.count("log_exercise ok") == 2 and "Feito" not in resposta


@pytest.mark.parametrize("frase, afirma", [
    ("Registrei 1 série.", True),
    ("Anotei a arara na lista de compras.", True),
    ("Incluí no INBOX.", True),
    ("Não registrei nada: a API recusou.", False),
    ("Nada foi registrado.", False),
    ("Qual exercício você fez?", False),
])
def test_detecta_afirmacao_de_gravacao(frase, afirma):
    assert agent.claims_write(frase) is afirma
