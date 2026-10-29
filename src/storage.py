import re
import subprocess
import unicodedata
from pathlib import Path
from src.config import TASKS_FILE, DATA_DIR

# Linha de tarefa: "- [ ] texto" ou "- [x] texto"
ITEM_RE = re.compile(r"^\s*[-*] \[( |x|X)\] (.+?)\s*$")
HEADING_RE = re.compile(r"^#{2,} ")

def read_tasks_markdown() -> str:
    """Lê o arquivo de tarefas em Markdown."""
    if not TASKS_FILE.exists():
        return "# 📋 Minhas Tarefas\n\n## 🎯 Prioridades de Hoje\n\n## ⏳ Em Andamento / Esta Semana\n\n## 💡 Backlog / Ideias\n\n## ✅ Concluídas Recentemente\n"
    return TASKS_FILE.read_text(encoding="utf-8")

def save_tasks_markdown(content: str, commit_message: str = "chore: update tasks via telegram agent") -> None:
    """Salva o novo conteúdo no arquivo de tarefas e opcionalmente cria commit local."""
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(content.strip() + "\n", encoding="utf-8")
    
    # Auto-commit silencioso no repositório próprio de data/ (privado, separado do código).
    # Sem data/.git não faz nada: nunca commita no repositório do código.
    if not (DATA_DIR / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "add", TASKS_FILE.name],
            cwd=DATA_DIR,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=DATA_DIR,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


# --- Edições pequenas no tarefas.md ---
# Cada operação mexe em uma única linha e devolve uma mensagem para o agente.
# Assim um modelo nunca precisa reescrever o arquivo inteiro (e não consegue apagá-lo).

def _normalize(text: str) -> str:
    """Minúsculas, sem acentos e sem emojis, para comparar textos com tolerância."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if c.isascii() and not unicodedata.combining(c))
    return " ".join(text.lower().split())

def list_sections() -> list[str]:
    """Títulos das seções (## e ###) do tarefas.md, sem os marcadores #."""
    lines = read_tasks_markdown().splitlines()
    return [line.lstrip("#").strip() for line in lines if HEADING_RE.match(line)]

def _find_section(lines: list[str], section: str) -> int | str:
    """Índice da linha do título da seção, ou mensagem de erro."""
    wanted = _normalize(section)
    matches = [i for i, line in enumerate(lines) if HEADING_RE.match(line) and wanted in _normalize(line)]
    if len(matches) == 1:
        return matches[0]
    sections = ", ".join(list_sections())
    if not matches:
        return f"Seção '{section}' não encontrada. Seções existentes: {sections}"
    options = "; ".join(lines[i].lstrip("#").strip() for i in matches)
    return f"Mais de uma seção casa com '{section}': {options}. Use um nome mais específico."

def _find_item(lines: list[str], item: str, only_open: bool) -> int | str:
    """Índice da linha do item, ou mensagem de erro (não achou / ambíguo)."""
    wanted = _normalize(item)
    candidates = []
    for i, line in enumerate(lines):
        match = ITEM_RE.match(line)
        if match and not (only_open and match.group(1) != " "):
            candidates.append((i, _normalize(match.group(2))))

    exact = [i for i, text in candidates if text == wanted]
    partial = [i for i, text in candidates if wanted and wanted in text]
    matches = exact or partial
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return f"Nenhum item {'aberto ' if only_open else ''}encontrado com '{item}'."
    options = "; ".join(ITEM_RE.match(lines[i]).group(2) for i in matches)
    return f"Mais de um item casa com '{item}': {options}. Pergunte ao usuário qual deles."

def _section_end(lines: list[str], heading_index: int) -> int:
    """Posição logo após a última linha não vazia da seção (antes do próximo título)."""
    end = heading_index + 1
    for i in range(heading_index + 1, len(lines)):
        if HEADING_RE.match(lines[i]):
            break
        if lines[i].strip():
            end = i + 1
    return end

def add_task(text: str, section: str = "INBOX") -> str:
    lines = read_tasks_markdown().splitlines()
    heading = _find_section(lines, section)
    if isinstance(heading, str):
        return heading
    text = " ".join(text.split())
    lines.insert(_section_end(lines, heading), f"- [ ] {text}")
    title = lines[heading].lstrip("#").strip()
    save_tasks_markdown("\n".join(lines), commit_message=f"feat(tarefas): {text} -> {title}")
    return f"Adicionado em {title}: {text}"

def complete_task(item: str) -> str:
    lines = read_tasks_markdown().splitlines()
    index = _find_item(lines, item, only_open=True)
    if isinstance(index, str):
        return index
    lines[index] = lines[index].replace("[ ]", "[x]", 1)
    text = ITEM_RE.match(lines[index]).group(2)
    save_tasks_markdown("\n".join(lines), commit_message=f"chore(tarefas): concluído {text}")
    return f"Concluído: {text}"

def move_task(item: str, section: str) -> str:
    lines = read_tasks_markdown().splitlines()
    index = _find_item(lines, item, only_open=False)
    if isinstance(index, str):
        return index
    line = lines.pop(index)
    heading = _find_section(lines, section)
    if isinstance(heading, str):
        return heading
    lines.insert(_section_end(lines, heading), line.strip())
    text = ITEM_RE.match(line).group(2)
    title = lines[heading].lstrip("#").strip()
    save_tasks_markdown("\n".join(lines), commit_message=f"chore(tarefas): {text} -> {title}")
    return f"Movido para {title}: {text}"

def remove_task(item: str) -> str:
    lines = read_tasks_markdown().splitlines()
    index = _find_item(lines, item, only_open=False)
    if isinstance(index, str):
        return index
    text = ITEM_RE.match(lines.pop(index)).group(2)
    save_tasks_markdown("\n".join(lines), commit_message=f"chore(tarefas): removido {text}")
    return f"Removido: {text}"
