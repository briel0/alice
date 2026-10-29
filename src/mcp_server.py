"""Servidor MCP da ALICE.

Pode ser consumido por:
- Claude Desktop
- Claude Code / Cline
- Antigravity
- Cursor / Neovim
- E pelo cliente interno do Telegram Bot
"""

from pathlib import Path
from mcp.server.mcpserver import MCPServer
from src.config import DATA_DIR
from src.storage import (
    add_task,
    complete_task,
    move_task,
    read_tasks_markdown,
    remove_task,
    save_tasks_markdown,
)

PROFILE_FILE = DATA_DIR / "perfil.md"
MEMORIES_FILE = DATA_DIR / "memorias_vivas.md"
BLUEPRINT_FILE = DATA_DIR / "blueprint.md"

server = MCPServer(
    name="alice",
    version="1.0.0",
    description="Servidor MCP da ALICE, assistente pessoal"
)

# --- RECURSOS (Resources) ---

@server.resource("alice://tasks")
def resource_tasks() -> str:
    """Conteúdo completo do arquivo de tarefas ativas e backlog."""
    return read_tasks_markdown()

@server.resource("alice://profile")
def resource_profile() -> str:
    """Perfil, frentes de vida, riscos e princípios do usuário."""
    if PROFILE_FILE.exists():
        return PROFILE_FILE.read_text(encoding="utf-8")
    return "Perfil não encontrado."

@server.resource("alice://blueprint")
def resource_blueprint() -> str:
    """Diretrizes operacionais e protocolos da assistente pessoal."""
    if BLUEPRINT_FILE.exists():
        return BLUEPRINT_FILE.read_text(encoding="utf-8")
    return "Blueprint não encontrado."

# --- FERRAMENTAS (Tools) ---

@server.tool(name="get_tasks", description="Retorna o arquivo tarefas.md completo com todas as seções (Inbox, Próximas Ações, Rotinas, Aguardando, Algum Dia).")
def tool_get_tasks() -> str:
    return read_tasks_markdown()

@server.tool(name="update_tasks", description="Reescreve o tarefas.md inteiro. Só para reorganizações grandes; para mudar itens, prefira add_task, complete_task, move_task e remove_task.")
def tool_update_tasks(new_markdown_content: str, reason: str = "atualização de tarefas") -> str:
    save_tasks_markdown(new_markdown_content, commit_message=f"chore: {reason}")
    return f"Tarefas atualizadas com sucesso. Motivo: {reason}"

@server.tool(name="add_to_inbox", description="Adiciona um item ou ideia rapidamente na seção INBOX do tarefas.md sem alterar o restante.")
def tool_add_to_inbox(item_text: str) -> str:
    return add_task(item_text, "INBOX")

@server.tool(name="add_task", description="Adiciona um item aberto ao fim de uma seção do tarefas.md. section é parte do título, ex.: INBOX, Estudos, AGUARDANDO.")
def tool_add_task(text: str, section: str = "INBOX") -> str:
    return add_task(text, section)

@server.tool(name="complete_task", description="Marca como concluído o item aberto cujo texto contém `item`.")
def tool_complete_task(item: str) -> str:
    return complete_task(item)

@server.tool(name="move_task", description="Move o item cujo texto contém `item` para o fim da seção indicada.")
def tool_move_task(item: str, section: str) -> str:
    return move_task(item, section)

@server.tool(name="remove_task", description="Apaga o item cujo texto contém `item`.")
def tool_remove_task(item: str) -> str:
    return remove_task(item)

@server.tool(name="get_profile", description="Retorna as regras de conduta, frentes ativas e limitações do usuário.")
def tool_get_profile() -> str:
    if PROFILE_FILE.exists():
        return PROFILE_FILE.read_text(encoding="utf-8")
    return "Perfil não configurado."

@server.tool(name="add_memory", description="Salva uma memória viva, fato aprendido, preferência ou mudança de rotina sobre o usuário.")
def tool_add_memory(fact: str, category: str = "geral") -> str:
    MEMORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORIES_FILE, "a", encoding="utf-8") as f:
        f.write(f"- [{category.upper()}] {fact}\n")
    return f"Memória registrada: [{category}] {fact}"

@server.tool(name="get_memories", description="Retorna todas as memórias vivas aprendidas sobre o usuário.")
def tool_get_memories() -> str:
    if MEMORIES_FILE.exists():
        return MEMORIES_FILE.read_text(encoding="utf-8")
    return "Nenhuma memória viva registrada ainda."

if __name__ == "__main__":
    # Quando executado diretamente (ex: via Claude Desktop ou terminal), roda em modo stdio
    server.run(transport="stdio")
