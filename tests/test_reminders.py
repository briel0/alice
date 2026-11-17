from datetime import datetime, timedelta

import pytest

from src import reminders
from src.reminders import TZ

AGORA = datetime(2026, 11, 17, 14, 0, tzinfo=TZ)  # uma terça


@pytest.fixture(autouse=True)
def arquivos_temporarios(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders, "REMINDERS_FILE", tmp_path / "lembretes.json")
    monkeypatch.setattr(reminders, "LOCK_FILE", tmp_path / "lembretes.lock")
    commits = []
    monkeypatch.setattr(reminders, "commit_data_file", lambda path, msg: commits.append(msg))
    return commits


def criar(texto="Ligar pro banco", quando="2026-11-18T09:00-03:00", at=AGORA):
    msg = reminders.create(texto, quando, "telegram", at=at)
    assert msg.startswith("Lembrete "), msg
    return msg.split()[1]


def test_cria_e_lista_com_data_absoluta():
    msg = reminders.create("Ligar  pro banco", "2026-11-18T09:00-03:00", "telegram", at=AGORA)
    assert "qua 18/11 09:00" in msg
    [r] = reminders.pending()
    assert r["texto"] == "Ligar pro banco"
    assert r["origem"] == "telegram"
    assert r["enviado_em"] is None and r["repetir"] is None


def test_commita_na_criacao_e_no_cancelamento(arquivos_temporarios):
    rid = criar()
    reminders.cancel(rid, at=AGORA)
    assert len(arquivos_temporarios) == 2


@pytest.mark.parametrize("quando, erro", [
    ("amanhã 9h", "inválida"),
    ("2026-11-18T09:00", "sem fuso"),
    ("2026-11-17T13:59-03:00", "já passou"),
])
def test_recusa_data_invalida(quando, erro):
    assert erro in reminders.create("x", quando, "mcp", at=AGORA)
    assert reminders.pending() == []


def test_converte_outro_fuso_para_sao_paulo():
    criar(quando="2026-11-18T12:00+00:00")
    assert reminders.pending()[0]["quando"] == "2026-11-18T09:00-03:00"


def test_vencidos_respeitam_o_horario_na_fronteira():
    criar(quando="2026-11-17T15:00-03:00")
    assert reminders.due(at=AGORA.replace(hour=14, minute=59)) == []
    assert len(reminders.due(at=AGORA.replace(hour=15))) == 1


def test_marcar_enviado_tira_dos_vencidos_e_dos_pendentes():
    rid = criar(quando="2026-11-17T15:00-03:00")
    depois = AGORA.replace(hour=15, minute=1)
    reminders.mark_sent([rid], at=depois)
    assert reminders.due(at=depois) == []
    assert reminders.pending() == []


def test_atrasado():
    rid = criar(quando="2026-11-17T15:00-03:00")
    [r] = reminders.due(at=AGORA.replace(hour=15, minute=1))
    assert not reminders.is_late(r, AGORA.replace(hour=15, minute=1))
    assert reminders.is_late(r, AGORA.replace(hour=18))


def test_adiar_volta_para_a_fila():
    rid = criar(quando="2026-11-17T15:00-03:00")
    envio = AGORA.replace(hour=15)
    reminders.mark_sent([rid], at=envio)
    alvo = reminders.snooze_target("1h", at=envio.replace(minute=7, second=30))
    assert alvo == AGORA.replace(hour=16, minute=7)
    reminders.snooze(rid, alvo, at=envio)
    assert [r["id"] for r in reminders.due(at=alvo)] == [rid]


def test_adiar_para_amanha_as_9h():
    noite = datetime(2026, 11, 30, 23, 30, tzinfo=TZ)
    assert reminders.snooze_target("amanha", at=noite) == datetime(2026, 12, 1, 9, 0, tzinfo=TZ)


def test_adiar_lembrete_inexistente():
    assert reminders.snooze("abc123", AGORA + timedelta(hours=1), at=AGORA) is None


def test_cancelar():
    rid = criar()
    assert "cancelado" in reminders.cancel(f"#{rid.upper()}", at=AGORA)
    assert reminders.pending() == []
    assert "Nenhum lembrete pendente" in reminders.cancel(rid, at=AGORA)


def test_apaga_enviados_antigos():
    velho = criar(quando="2026-11-17T15:00-03:00")
    reminders.mark_sent([velho], at=AGORA.replace(hour=15))
    # Qualquer escrita 31 dias depois limpa o enviado antigo
    criar(quando="2026-12-20T09:00-03:00", at=AGORA + timedelta(days=31))
    assert reminders.snooze(velho, AGORA + timedelta(days=32), at=AGORA + timedelta(days=31)) is None


def test_lista_ordenada_e_formatada():
    criar("Segundo", "2026-11-19T10:00-03:00")
    criar("Primeiro", "2026-11-18T09:00-03:00")
    linhas = reminders.list_text().splitlines()
    assert "Primeiro" in linhas[0] and "qua 18/11 09:00" in linhas[0]
    assert "Segundo" in linhas[1]
