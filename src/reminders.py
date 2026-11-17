"""Lembretes avulsos ("me lembra amanhã às 9h"), guardados em data/lembretes.json.

O bot (que envia os vencidos) e o servidor MCP (outro processo) leem e escrevem o mesmo arquivo, então toda
operação segura uma trava de arquivo e grava de forma atômica. Quem chama só usa as funções públicas daqui:
se um dia o armazenamento for para SQLite, só este módulo muda.

Cada lembrete: {id, texto, quando, criado_em, origem, enviado_em, repetir}. Datas em ISO 8601 com fuso.
`repetir` fica sempre null por enquanto (reservado para lembretes recorrentes).
"""
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import BASE_DIR, DATA_DIR
from src.storage import commit_data_file

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# Fuso explícito: o processo do MCP não necessariamente roda com TZ configurado
TZ = ZoneInfo("America/Sao_Paulo")

REMINDERS_FILE = DATA_DIR / "lembretes.json"
# Fora de data/, para o backup (git add -A) não levar a trava
LOCK_FILE = BASE_DIR / ".cache" / "lembretes.lock"

KEEP_SENT_DAYS = 30           # enviados há mais tempo que isso são apagados
LATE_AFTER = timedelta(minutes=2)  # a partir daqui o envio é marcado como atrasado

WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def now() -> datetime:
    return datetime.now(TZ)


def fmt_when(dt: datetime) -> str:
    """Ex.: 'qua 18/11 09:00'."""
    dt = dt.astimezone(TZ)
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d/%m %H:%M}"


def when_of(reminder: dict) -> datetime:
    return datetime.fromisoformat(reminder["quando"])


def is_late(reminder: dict, at: datetime) -> bool:
    return at - when_of(reminder) > LATE_AFTER


# --- Arquivo, trava e escrita atômica ---

@contextmanager
def _locked():
    """Trava exclusiva entre processos (bot e MCP) enquanto lê e escreve o arquivo."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a+b") as f:
        if os.name == "nt":
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def _load() -> list[dict]:
    if not REMINDERS_FILE.exists():
        return []
    return json.loads(REMINDERS_FILE.read_text(encoding="utf-8")).get("lembretes", [])


def _save(items: list[dict], at: datetime) -> None:
    limit = at - timedelta(days=KEEP_SENT_DAYS)
    items = [r for r in items if not r["enviado_em"] or datetime.fromisoformat(r["enviado_em"]) > limit]
    items.sort(key=when_of)
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REMINDERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"lembretes": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REMINDERS_FILE)


def _find(items: list[dict], reminder_id: str) -> dict | None:
    reminder_id = reminder_id.strip().lstrip("#").lower()
    return next((r for r in items if r["id"] == reminder_id), None)


# --- Operações ---

def parse_when(when: str, at: datetime | None = None) -> datetime | str:
    """Data ISO 8601 com fuso e no futuro, ou mensagem de erro para quem chamou corrigir."""
    at = at or now()
    try:
        dt = datetime.fromisoformat(when.strip())
    except ValueError:
        return f"Data inválida: '{when}'. Use ISO 8601 com fuso, ex.: 2026-11-18T09:00-03:00."
    if dt.tzinfo is None:
        return f"Data sem fuso: '{when}'. Inclua o fuso, ex.: 2026-11-18T09:00-03:00."
    if dt <= at:
        return f"A data {fmt_when(dt)} já passou (agora é {fmt_when(at)}). Escolha um horário no futuro."
    return dt.astimezone(TZ)


def create(text: str, when: str, origin: str, at: datetime | None = None) -> str:
    at = at or now()
    text = " ".join(text.split())
    if not text:
        return "Texto do lembrete vazio."
    dt = parse_when(when, at)
    if isinstance(dt, str):
        return dt
    with _locked():
        items = _load()
        ids = {r["id"] for r in items}
        new_id = secrets.token_hex(3)
        while new_id in ids:
            new_id = secrets.token_hex(3)
        items.append({
            "id": new_id,
            "texto": text,
            "quando": dt.isoformat(timespec="minutes"),
            "criado_em": at.isoformat(timespec="seconds"),
            "origem": origin,
            "enviado_em": None,
            "repetir": None,
        })
        _save(items, at)
    commit_data_file(REMINDERS_FILE, f"feat(lembretes): {text} -> {dt:%Y-%m-%d %H:%M}")
    return f"Lembrete {new_id} criado para {fmt_when(dt)}: {text}"


def pending() -> list[dict]:
    """Lembretes ainda não enviados, do mais próximo ao mais distante."""
    with _locked():
        return [r for r in _load() if not r["enviado_em"]]


def list_text() -> str:
    items = pending()
    if not items:
        return "Nenhum lembrete pendente."
    return "\n".join(f"- {r['id']} · {fmt_when(when_of(r))} · {r['texto']}" for r in items)


def cancel(reminder_id: str, at: datetime | None = None) -> str:
    at = at or now()
    with _locked():
        items = _load()
        reminder = _find(items, reminder_id)
        if not reminder or reminder["enviado_em"]:
            return f"Nenhum lembrete pendente com id '{reminder_id}'."
        items.remove(reminder)
        _save(items, at)
    commit_data_file(REMINDERS_FILE, f"chore(lembretes): cancelado {reminder['texto']}")
    return f"Lembrete cancelado: {reminder['texto']} ({fmt_when(when_of(reminder))})"


def due(at: datetime | None = None) -> list[dict]:
    """Lembretes não enviados cujo horário já chegou, incluindo os atrasados."""
    at = at or now()
    with _locked():
        return [r for r in _load() if not r["enviado_em"] and when_of(r) <= at]


def mark_sent(ids: list[str], at: datetime | None = None) -> None:
    at = at or now()
    with _locked():
        items = _load()
        for r in items:
            if r["id"] in ids:
                r["enviado_em"] = at.isoformat(timespec="seconds")
        _save(items, at)


def snooze(reminder_id: str, until: datetime, at: datetime | None = None) -> dict | None:
    """Volta o lembrete para a fila com um novo horário. None se ele não existe mais."""
    at = at or now()
    with _locked():
        items = _load()
        reminder = _find(items, reminder_id)
        if not reminder:
            return None
        reminder["quando"] = until.astimezone(TZ).isoformat(timespec="minutes")
        reminder["enviado_em"] = None
        _save(items, at)
    return reminder


def snooze_target(option: str, at: datetime | None = None) -> datetime:
    """Novo horário dos botões de adiar: '1h' (daqui a uma hora) ou 'amanha' (amanhã às 9h)."""
    at = (at or now()).astimezone(TZ)
    if option == "1h":
        return (at + timedelta(hours=1)).replace(second=0, microsecond=0)
    return (at + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
