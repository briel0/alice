# 🔌 Como conectar o servidor MCP da ALICE

O servidor fica em `src/mcp_server.py` e fala MCP por stdio. Qualquer cliente compatível (Claude Desktop, Claude Code, Cline, Cursor, Antigravity) pode usá-lo.

## 1. Dados no mesmo computador

### Claude Code
```bash
claude mcp add alice -s user -- uv --directory "/caminho/para/alice" run python -m src.mcp_server
```

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "alice": {
      "command": "uv",
      "args": ["--directory", "/caminho/para/alice", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

## 2. Dados numa VM (fonte única da verdade)

Se o bot roda numa VM, rode o MCP **lá** por SSH, em vez de sincronizar arquivos. O cliente continua vendo um servidor stdio comum.

1. Crie um alias em `~/.ssh/config` (ex.: `Host alice-vm`, com `HostName`, `User` e `IdentityFile`).
2. Na VM, um wrapper que entra na pasta e roda o servidor como o usuário dono dos dados:
   ```sh
   #!/bin/sh
   cd /opt/alice/app && exec /opt/alice/app/.venv/bin/python -m src.mcp_server
   ```
3. Registre no cliente:
   ```bash
   claude mcp add alice -s user -- ssh -T -o BatchMode=yes alice-vm sudo -n -u alice /opt/alice/bin/alice-mcp
   ```

## 3. O que os modelos ganham

- **Recursos:** `alice://tasks`, `alice://profile`, `alice://blueprint`
- **Ferramentas:**
  - `get_tasks()`: lê o `tarefas.md` completo.
  - `add_task(text, section)`, `complete_task(item)`, `move_task(item, section)`, `remove_task(item)`: edições de uma linha.
  - `add_to_inbox(item_text)`: captura rápida no INBOX.
  - `update_tasks(new_markdown_content, reason)`: reescreve o arquivo inteiro; só para reorganizações grandes.
  - `get_profile()`, `add_memory(fact, category)`, `get_memories()`.
  - `create_card(title, category, description)`: cria um cartão no Planner. Só aparece com `PLANNER_API_URL` configurado.
