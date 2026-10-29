"""CLI interativa da ALICE (Chefe de Gabinete).

Uso:
  uv run python -m src.cli                  -> chat interativo no terminal
  uv run python -m src.cli "sua mensagem"   -> pergunta única e sai
"""

import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

# Suprime avisos de bibliotecas
warnings.filterwarnings("ignore")

# Garante suporte a UTF-8 no Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Adiciona o diretório raiz ao path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from rich.console import Console
from rich.markdown import Heading, Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.theme import Theme

from src.agent import MEMORIES_FILE, process_user_message
from src.config import USER_NAME
from src.storage import read_tasks_markdown
from src.history import clear_history
from src.guardrails import get_usage_summary

# Uma cor de destaque (a da ALICE); as demais só carregam significado.
# Cores ANSI básicas para respeitar a paleta do terminal, claro ou escuro.
theme = Theme({
    "accent": "bold magenta",
    "muted": "dim",
    "ok": "green",
    "warn": "yellow",
    "error": "bold red",
    "markdown.h1": "bold magenta",
    "markdown.h2": "bold",
    "markdown.h3": "bold",
    "markdown.h4": "bold dim",
    "markdown.code": "magenta",
    "markdown.item.bullet": "magenta",
    "markdown.item.number": "magenta",
    "markdown.link": "underline",
})

console = Console(theme=theme, highlight=False)

INDENT = 2
GOODBYE = f"Até logo, {escape(USER_NAME)}." if USER_NAME else "Até logo."
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
ITEM_RE = re.compile(r"^\s*[-*] \[([ xX])\]\s*(.*?)\s*$")
EXIT_WORDS = {"sair", "exit", "quit", ":q", "q", "/sair"}


class LeftHeading(Heading):
    """Títulos alinhados à esquerda (o rich centraliza o h1 por padrão)."""

    LEVEL_ALIGN = {tag: "left" for tag in Heading.LEVEL_ALIGN}


class AliceMarkdown(Markdown):
    elements = {**Markdown.elements, "heading_open": LeftHeading}


# --- Leitura do estado (tarefas e memórias) ---

def read_memories() -> str:
    if MEMORIES_FILE.exists():
        return MEMORIES_FILE.read_text(encoding="utf-8")
    return ""


def parse_items(markdown: str) -> dict[str, bool]:
    """Mapeia o texto de cada checkbox (`- [ ] ...`) para concluído ou não."""
    items = {}
    for line in markdown.splitlines():
        match = ITEM_RE.match(line)
        if match and match.group(2):
            items[match.group(2)] = match.group(1) != " "
    return items


def inbox_items(markdown: str) -> list[str]:
    """Itens abertos da seção INBOX."""
    items, inside = [], False
    for line in markdown.splitlines():
        if line.startswith("## "):
            inside = "INBOX" in line.upper()
            continue
        match = ITEM_RE.match(line)
        if inside and match and match.group(2) and match.group(1) == " ":
            items.append(match.group(2))
    return items


def count_memories() -> int:
    return sum(1 for line in read_memories().splitlines() if line.startswith("- "))


# --- Renderização ---

def pt_date(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} · {now:%H:%M}"


def print_banner():
    inbox = len(inbox_items(read_tasks_markdown()))
    console.print()
    console.print("[accent]●[/accent] [bold]ALICE[/bold]  [muted]chefe de gabinete[/muted]")
    console.print(
        f"  [muted]{pt_date(datetime.now())}   inbox {inbox} · memórias {count_memories()}[/muted]"
    )
    console.print("  [muted]/tarefas  /inbox  /reset  /ajuda  · sair ou Ctrl+C[/muted]")
    console.print()


def print_help():
    rows = [
        ("/tarefas", "mostra o tarefas.md inteiro"),
        ("/inbox", "só os itens abertos do INBOX"),
        ("/reset", "esquece a conversa recente (tarefas e memórias ficam)"),
        ("/ajuda", "esta lista"),
        ("sair", "encerra (ou Ctrl+C / Ctrl+D)"),
    ]
    console.print()
    for command, description in rows:
        console.print(f"  [accent]{command:<10}[/accent] [muted]{description}[/muted]")
    console.print()


def print_markdown(text: str):
    console.print(Padding(AliceMarkdown(text), (0, 0, 0, INDENT)))


def describe_changes(tasks_before: str, tasks_after: str, memories_before: str, memories_after: str) -> list[str]:
    """Traduz o que mudou nos arquivos em linhas curtas para o usuário."""
    changes = []

    before, after = parse_items(tasks_before), parse_items(tasks_after)
    for text in after.keys() - before.keys():
        changes.append(f"[ok]+[/ok] {escape(text)}")
    for text in before.keys() & after.keys():
        if after[text] and not before[text]:
            changes.append(f"[ok]✓[/ok] concluída: {escape(text)}")
    for text in before.keys() - after.keys():
        changes.append(f"[warn]−[/warn] removida: {escape(text)}")
    if not changes and tasks_before != tasks_after:
        changes.append("[ok]✓[/ok] tarefas.md reorganizado")

    new_memories = memories_after[len(memories_before):] if memories_after.startswith(memories_before) else memories_after
    for line in new_memories.splitlines():
        if line.strip():
            changes.append(f"[ok]◆[/ok] memória: {escape(line.lstrip('- ').strip())}")

    return changes


def print_changes(changes: list[str], limit: int = 6):
    if not changes:
        return
    console.print()
    for line in changes[:limit]:
        console.print(" " * INDENT + line)
    if len(changes) > limit:
        console.print(f"  [muted]… e mais {len(changes) - limit}[/muted]")


def print_error(error: Exception):
    message = str(error) or type(error).__name__
    hint = ""
    if "GEMINI_API_KEY" in message:
        hint = "Coloque a chave no arquivo .env (veja .env.example)."
    elif any(word in message.lower() for word in ("connect", "timeout", "network", "getaddrinfo")):
        hint = "Parece problema de conexão. Confira a internet e tente de novo."
    elif "429" in message or "quota" in message.lower() or "resource_exhausted" in message.lower():
        hint = "Limite de uso do Gemini atingido. Espere um pouco ou troque o GEMINI_MODEL."

    first_line = message.strip().splitlines()[0][:200]
    console.print()
    console.print(f"  [error]✗[/error] [red]{escape(first_line)}[/red]")
    if hint:
        console.print(f"  [muted]{hint}[/muted]")
    console.print()


# --- Conversa ---

def ask_alice(message: str):
    """Envia uma mensagem, mostra a resposta e o que ela alterou nos arquivos."""
    tasks_before, memories_before = read_tasks_markdown(), read_memories()
    started = time.monotonic()

    with console.status("[muted]pensando…[/muted]", spinner="dots", spinner_style="magenta"):
        reply = process_user_message(user_text=message, user_id=0)

    elapsed = time.monotonic() - started
    changes = describe_changes(tasks_before, read_tasks_markdown(), memories_before, read_memories())

    console.print()
    console.print("[accent]●[/accent] [bold]ALICE[/bold]")
    print_markdown(reply)
    print_changes(changes)
    seconds = f"{elapsed:.1f}".replace(".", ",")
    console.print(f"  [muted]{seconds}s[/muted]")
    console.print()


def handle_command(command: str) -> bool:
    """Executa um comando local. Devolve False se o texto não for um comando."""
    if command in ("/tarefas", "tarefas"):
        console.print()
        print_markdown(read_tasks_markdown())
        console.print()
    elif command in ("/inbox", "inbox"):
        items = inbox_items(read_tasks_markdown())
        console.print()
        if items:
            for item in items:
                console.print(f"  [accent]○[/accent] {escape(item)}")
        else:
            console.print("  [muted]INBOX vazio.[/muted]")
        console.print()
    elif command in ("/reset", "reset"):
        clear_history()
        console.print("\n  [ok]✓[/ok] conversa recente esquecida [muted](tarefas e memórias continuam)[/muted]\n")
    elif command in ("/consumo", "/gastos", "consumo"):
        console.print()
        console.print(get_usage_summary())
        console.print()
    elif command in ("/ajuda", "/help", "ajuda"):
        print_help()
    elif command.startswith("/"):
        console.print(f"\n  [warn]?[/warn] comando desconhecido: {escape(command)}  [muted]veja /ajuda[/muted]\n")
    else:
        return False
    return True


def run_interactive():
    print_banner()
    while True:
        try:
            user_input = console.input("[accent]❯[/accent] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n\n  [muted]{GOODBYE}[/muted]\n")
            break

        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            console.print(f"\n  [muted]{GOODBYE}[/muted]\n")
            break
        if handle_command(user_input.lower()):
            continue

        try:
            ask_alice(user_input)
        except KeyboardInterrupt:
            console.print("\n  [warn]cancelado[/warn]\n")
        except Exception as e:
            print_error(e)


def run_one_shot(message: str):
    try:
        ask_alice(message)
    except KeyboardInterrupt:
        console.print("\n  [warn]cancelado[/warn]\n")
    except Exception as e:
        print_error(e)
        sys.exit(1)


def main():
    if len(sys.argv) > 1:
        run_one_shot(" ".join(sys.argv[1:]))
    else:
        run_interactive()


if __name__ == "__main__":
    main()
