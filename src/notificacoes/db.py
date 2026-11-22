"""SQLite do filtro (fora de data/: o texto dos e-mails não vai para o Git nem para o backup).

Tabelas:
- itens: um por e-mail (ou, no futuro, notificação), com o nível decidido e o que já foi enviado
- estado: chave/valor (historyId do Gmail, último resumo enviado, início do modo sombra, avisos já dados)
- uso: chamadas ao Gemini por dia, para nunca passar do limite
- propostas: ajuste sugerido depois de uma correção (critério e trecho do assunto), esperando o "sim" do usuário;
  fica aqui porque o texto não cabe nos 64 bytes de um botão do Telegram

A coluna feedback guarda o nível em que o usuário disse que o item devia ter caído (agora/resumo/silencio).

Itens com mais de KEEP_DAYS dias são apagados. Cada função abre e fecha a própria conexão: o bot chama
daqui por asyncio.to_thread, e uma conexão do sqlite3 não deve ser usada em threads diferentes.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import NOTIF_DB_PATH

TZ = ZoneInfo("America/Sao_Paulo")
KEEP_DAYS = 30
NIVEIS = ("agora", "resumo", "silencio")

SCHEMA = """
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL,
    ext_id TEXT NOT NULL,
    remetente TEXT NOT NULL,
    endereco TEXT NOT NULL,
    assunto TEXT NOT NULL,
    categoria TEXT NOT NULL,
    trecho TEXT NOT NULL,
    link TEXT NOT NULL,
    nivel TEXT NOT NULL,
    resumo TEXT NOT NULL,
    motivo TEXT NOT NULL,
    recebido_em TEXT NOT NULL,
    processado_em TEXT NOT NULL,
    alertado_em TEXT,
    resumido_em TEXT,
    feedback TEXT,
    UNIQUE (fonte, ext_id)
);
CREATE INDEX IF NOT EXISTS itens_processado ON itens (processado_em);
CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS uso (dia TEXT PRIMARY KEY, chamadas INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS propostas (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    nivel TEXT NOT NULL,
    criterio TEXT NOT NULL,
    trecho TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(TZ)


@contextmanager
def conectar():
    NOTIF_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(NOTIF_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        with con:
            yield con
    finally:
        con.close()


# --- Estado ---

def get_estado(chave: str) -> str | None:
    with conectar() as con:
        row = con.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
        return row["valor"] if row else None


def set_estado(chave: str, valor: str) -> None:
    with conectar() as con:
        con.execute("INSERT INTO estado (chave, valor) VALUES (?, ?) "
                    "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (chave, valor))


# --- Uso do Gemini ---

def chamadas_hoje(at: datetime | None = None) -> int:
    dia = (at or now()).astimezone(TZ).date().isoformat()
    with conectar() as con:
        row = con.execute("SELECT chamadas FROM uso WHERE dia = ?", (dia,)).fetchone()
        return row["chamadas"] if row else 0


def contar_chamada(at: datetime | None = None) -> None:
    dia = (at or now()).astimezone(TZ).date().isoformat()
    with conectar() as con:
        con.execute("INSERT INTO uso (dia, chamadas) VALUES (?, 1) "
                    "ON CONFLICT (dia) DO UPDATE SET chamadas = chamadas + 1", (dia,))


# --- Itens ---

def ja_visto(fonte: str, ext_ids: list[str]) -> set[str]:
    if not ext_ids:
        return set()
    with conectar() as con:
        marks = ",".join("?" * len(ext_ids))
        rows = con.execute(f"SELECT ext_id FROM itens WHERE fonte = ? AND ext_id IN ({marks})", (fonte, *ext_ids))
        return {r["ext_id"] for r in rows}


def inserir(itens: list[dict], at: datetime | None = None) -> list[int]:
    """Grava os itens classificados e devolve os ids novos (repetidos são ignorados)."""
    at = at or now()
    ids = []
    with conectar() as con:
        for it in itens:
            cur = con.execute(
                "INSERT OR IGNORE INTO itens (fonte, ext_id, remetente, endereco, assunto, categoria, trecho, link,"
                " nivel, resumo, motivo, recebido_em, processado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (it["fonte"], it["ext_id"], it["remetente"], it["endereco"], it["assunto"], it["categoria"],
                 it["trecho"], it["link"], it["nivel"], it["resumo"], it["motivo"], it["recebido_em"],
                 at.isoformat(timespec="seconds")),
            )
            if cur.rowcount:
                ids.append(cur.lastrowid)
        limite = (at - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        con.execute("DELETE FROM itens WHERE processado_em < ?", (limite,))
        con.execute("DELETE FROM propostas WHERE criado_em < ?", (limite,))
    return ids


def item(item_id: int) -> dict | None:
    with conectar() as con:
        row = con.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def alertas_pendentes() -> list[dict]:
    with conectar() as con:
        rows = con.execute("SELECT * FROM itens WHERE nivel = 'agora' AND alertado_em IS NULL ORDER BY id")
        return [dict(r) for r in rows]


def marcar(coluna: str, ids: list[int], at: datetime | None = None) -> None:
    assert coluna in ("alertado_em", "resumido_em")
    if not ids:
        return
    valor = (at or now()).isoformat(timespec="seconds")
    with conectar() as con:
        con.executemany(f"UPDATE itens SET {coluna} = ? WHERE id = ?", [(valor, i) for i in ids])


def resumo_pendente() -> list[dict]:
    with conectar() as con:
        rows = con.execute("SELECT * FROM itens WHERE nivel = 'resumo' AND resumido_em IS NULL ORDER BY id")
        return [dict(r) for r in rows]


def silenciados(desde: str, ate: str) -> list[dict]:
    with conectar() as con:
        rows = con.execute("SELECT * FROM itens WHERE nivel = 'silencio' AND processado_em > ? AND processado_em <= ?"
                           " ORDER BY id", (desde, ate))
        return [dict(r) for r in rows]


def set_feedback(item_id: int, nivel: str) -> None:
    """Nível em que o item devia ter caído, segundo o usuário."""
    assert nivel in NIVEIS
    with conectar() as con:
        con.execute("UPDATE itens SET feedback = ? WHERE id = ?", (nivel, item_id))


def balanco(desde: str) -> dict:
    """Contagens para o balanço: quantos por nível e, dos corrigidos, para onde o usuário disse que iam."""
    with conectar() as con:
        rows = con.execute("SELECT nivel, feedback, COUNT(*) AS n FROM itens WHERE processado_em >= ?"
                           " GROUP BY nivel, feedback", (desde,))
        out = {n: {"total": 0, "corrigidos": 0, "para": {}} for n in NIVEIS}
        for r in rows:
            out[r["nivel"]]["total"] += r["n"]
            if r["feedback"] in NIVEIS and r["feedback"] != r["nivel"]:
                out[r["nivel"]]["corrigidos"] += r["n"]
                out[r["nivel"]]["para"][r["feedback"]] = r["n"]
        return out


# --- Propostas ---

def nova_proposta(item_id: int, nivel: str, criterio: str, trecho: str, at: datetime | None = None) -> int:
    with conectar() as con:
        cur = con.execute("INSERT INTO propostas (item_id, nivel, criterio, trecho, criado_em) VALUES (?,?,?,?,?)",
                          (item_id, nivel, criterio, trecho, (at or now()).isoformat(timespec="seconds")))
        return cur.lastrowid


def proposta(proposta_id: int) -> dict | None:
    with conectar() as con:
        row = con.execute("SELECT * FROM propostas WHERE id = ?", (proposta_id,)).fetchone()
        return dict(row) if row else None


def apagar_proposta(proposta_id: int) -> bool:
    """Apaga e diz se ela existia (um segundo toque no mesmo botão não grava duas vezes)."""
    with conectar() as con:
        return con.execute("DELETE FROM propostas WHERE id = ?", (proposta_id,)).rowcount > 0
