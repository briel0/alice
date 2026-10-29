# ALICE

**ALICE** (ALICE Lembra, Integra, Cobra e Executa) é uma assistente pessoal: um bot de Telegram que recebe texto e áudio, raciocina com o Gemini e mantém suas tarefas em Markdown. O mesmo estado fica disponível para outros agentes (Claude Code, Claude Desktop, Cursor etc.) por um servidor MCP.

## Como funciona

- **Telegram** (`main.py`): o agente de campo. Anota, conclui e move tarefas, salva memórias e responde com o contexto do seu perfil.
- **CLI** (`python -m src.cli`): a mesma conversa no terminal.
- **MCP** (`python -m src.mcp_server`): expõe tarefas, perfil e memórias como ferramentas para outros agentes.
- **Dados** (`data/`): arquivos Markdown simples. Ficam **fora** deste repositório; veja abaixo.

Opcional: com `PLANNER_API_URL`, a ALICE também cria cartões no [Planner](https://github.com/briel0/planner) (só cria; organizar fica no Planner).

O agente do Telegram nunca reescreve o arquivo de tarefas inteiro: ele só faz edições de uma linha (`add_task`, `complete_task`, `move_task`, `remove_task`), então um modelo pequeno não consegue apagar suas tarefas por engano.

## Instalação

Requer Python 3.14+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env          # preencha o token do bot, a chave do Gemini e seu ID do Telegram
mkdir -p data
cp examples/perfil.example.md data/perfil.md
cp examples/tarefas.example.md data/tarefas.md
cp examples/diretrizes.example.md data/diretrizes.md   # opcional
uv run python main.py
```

Sem `ALLOWED_TELEGRAM_USER_ID`, o bot responde a qualquer pessoa e mostra o ID de quem escreveu; defina-o antes de usar de verdade.

## Seus dados

`data/` é ignorada pelo git. Arquivos que a ALICE usa:

| Arquivo | Conteúdo |
|---|---|
| `perfil.md` | quem você é, frentes de vida, riscos, princípios |
| `diretrizes.md` | instruções pessoais que têm prioridade sobre o prompt genérico (opcional) |
| `tarefas.md` | suas tarefas, por seção |
| `memorias_vivas.md` | fatos que a ALICE aprende sobre você |
| `historico.jsonl` | histórico recente da conversa |
| `blueprint.md` | documento de visão, exposto pelo MCP (opcional) |

Recomendação: transforme `data/` em um repositório git **privado** separado. Se `data/.git` existir, a ALICE faz um commit a cada mudança nas tarefas.

## Deploy

`deploy/` tem um exemplo de serviço systemd para rodar 24/7 numa VM pequena (512 MB bastam), com backup diário de `data/`. Para conectar agentes do PC aos dados da VM, veja `mcp_config_guide.md`.
