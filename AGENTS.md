# AGENTS.md

Instruções para agentes de IA (Claude Code, Codex, Antigravity etc.) trabalhando neste repositório.

## O que é

**ALICE**: bot de Telegram que atua como **chefe de gabinete** pessoal. Recebe texto/áudio, raciocina com Gemini e mantém tarefas em Markdown. Também expõe o mesmo estado por um servidor MCP.

## Repositório público + dados privados (regra principal)

Este repositório é **público** e contém só código genérico. Tudo que é pessoal vive em `data/`, que é ignorada pelo git e tem seu próprio repositório **privado**.

- **Nunca** coloque dado pessoal no código, nos docs, nos testes ou em mensagens de commit: nomes de pessoas, empresas, faculdade, rotina, tarefas reais, IPs, IDs de Telegram, caminhos da máquina do dono.
- O que é específico do dono vai em arquivos de `data/` (`perfil.md`, `diretrizes.md`, `blueprint.md`), nunca em constantes do código. O código se refere a ele como "o usuário"; o nome vem de `USER_NAME`.
- Exemplos genéricos desses arquivos ficam em `examples/`. Se mudar o formato de um arquivo de `data/`, atualize o exemplo.
- Nunca rode `git add -f` em nada de `data/`.
- Antes de commitar, confira o diff procurando dados pessoais.

## Stack e comandos

- Python >= 3.14, gerenciado com `uv` (venv em `.venv/`)
- `python-telegram-bot` (async), `google-genai`, `python-dotenv`, `mcp`, `rich`
- Instalar deps: `uv sync`
- Rodar o bot: `uv run python main.py` (requer `.env`, ver `.env.example`)
- CLI: `uv run python -m src.cli` · MCP: `uv run python -m src.mcp_server`
- Checagem rápida de imports: `uv run python -c "import src.bot, src.mcp_server"`
- Não há testes Python nem linter configurados ainda. O `claude-mod/` tem testes próprios (`claude plugin test claude-mod`).

## Estrutura

```
main.py            ponto de entrada (chama src.bot.run_bot)
src/config.py      variáveis de ambiente e paths
src/bot.py         handlers do Telegram (texto, voz, comandos)
src/agent.py       prompt genérico, chamadas ao Gemini e ferramentas
src/storage.py     tarefas.md: leitura, edições de uma linha e auto-commit em data/.git
src/mcp_server.py  servidor MCP (stdio)
src/cli.py         CLI no terminal
src/guardrails.py  limites diários de uso
src/history.py     histórico da conversa (data/historico.jsonl)
examples/          modelos genéricos dos arquivos de data/
deploy/            serviço systemd, wrappers e backup para rodar numa VM
claude-mod/        identidade visual da ALICE dentro do Claude Code
```


## Convenções

- Código e comentários em português, como o código existente. Mensagens de commit no estilo Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`).
- Imports absolutos a partir de `src` (`from src.config import ...`).
- Mantenha simples. Não adicione frameworks, camadas ou features que não foram pedidas.
- Configuração nova vai em `src/config.py` lida do `.env`, e a chave correspondente vai em `.env.example`.
- O agente do Telegram só edita tarefas linha a linha (`add_task`, `complete_task`, `move_task`, `remove_task`). Não devolva ao Gemini uma ferramenta que reescreva o arquivo inteiro; reescrita completa só existe no MCP (`update_tasks`).

## Segurança

- Nunca commite `.env`, tokens, chaves ou `.pem`. Nunca leia nem exiba o conteúdo do `.env`.
- Não edite `data/tarefas.md` manualmente sem pedido explícito: é o estado do bot.

## Trabalho com vários agentes ao mesmo tempo

Mais de um agente pode estar operando neste diretório simultaneamente.

- Antes de editar, rode `git status` e confira se o arquivo não tem mudanças não commitadas de outro agente.
- Evite editar o mesmo arquivo que outro agente; se precisar, avise o dono do repositório.
- Faça commits pequenos e focados, só quando o dono pedir, adicionando arquivos específicos (`git add <arquivo>`), nunca `git add -A`/`git add .`.

## Skills do projeto

Skills ficam em `.agents/skills/` (fonte única; `.claude/skills/` só aponta para lá). Se sua ferramenta não as descobrir sozinha, leia o `SKILL.md` correspondente quando a tarefa casar:

- `project-health` — checagem do estado do projeto, problemas de arquitetura e próximos passos. Use quando pedirem avaliação, health check, "o que falta" ou próximos passos.

## Problemas conhecidos (backlog técnico)

1. Se `ALLOWED_TELEGRAM_USER_ID` não estiver definido, o bot aceita qualquer usuário (`is_authorized` em `src/bot.py`).
2. Chamada síncrona ao Gemini dentro de handler async bloqueia o event loop (usar `client.aio`).
3. `/tarefas` quebra se o arquivo passar de 4096 caracteres; `/hoje` é igual a `/tarefas`.
4. `guardrails.py` só conta uso do Claude; o caminho do Claude em `agent.py` usa um modelo aposentado e não é usado.
5. Melhoria futura: registrar em cada mensagem de `data/historico.jsonl` o canal de origem (`telegram` ou `cli`).
6. Interface de voz — primeiro objetivo: conversar com a ALICE pelo microfone e alto-falante do PC, com respostas faladas e acesso às tarefas e memórias. Não implementar nesta etapa.
7. Ideia futura, após validar a voz no PC: Echo Dot ou hardware próprio como interface de voz (Alexa Skill, privacidade, custos, backend 24/7). Não implementar nesta etapa.
