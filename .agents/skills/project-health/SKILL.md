---
name: project-health
description: Checagem do estado atual do projeto ALICE — encontra problemas de arquitetura, bugs, riscos de segurança e divergências com a documentação, e sugere no máximo 3 próximos passos. Use quando o dono do projeto pedir "checagem", "avaliação", "health check", "estado do projeto", "o que falta" ou "próximos passos".
---

# Project Health — ALICE

Checagem **somente leitura** do projeto. Não edite código, não commite e não altere `data/` durante a checagem. Mudanças só depois, se o dono do projeto pedir.

## 1. Estado do repositório

- `git status`, `git log --oneline -10` e `git diff --stat`.
- Mudanças não commitadas podem ser de **outro agente** trabalhando em paralelo: reporte-as, não mexa nelas.
- Anote o que mudou desde a última checagem (commits novos, arquivos novos).

## 2. Smoke check

- `uv run python -c "import src.bot"` — o projeto importa?
- Existe `.env`? (só verifique a existência, **nunca** leia ou exiba o conteúdo)
- Chaves usadas em `src/config.py` estão todas em `.env.example`?

## 3. Leitura do código

Leia `src/*.py` e `main.py` inteiros (o projeto é pequeno). Procure:

- **Correção:** fluxos que falham silenciosamente, respostas que afirmam algo que não aconteceu, casos de borda do Telegram (limite de 4096 caracteres, mensagens sem texto, voz vs. áudio).
- **Arquitetura:** responsabilidades misturadas entre `bot.py` / `agent.py` / `storage.py`, I/O bloqueante em código async, estado global, acoplamento com git.
- **Integração com o LLM:** loop de tool calls completo, contexto igual para texto e áudio, risco de o modelo truncar ou apagar dados ao salvar.
- **Segurança e privacidade:** autorização fail-closed, segredos fora do git, dados de `data/` não vazando para logs, mensagens de erro ou serviços além do Gemini.

## 4. Documentação vs. realidade

Compare o código com `AGENTS.md`, `README.md` e, se existir, `data/blueprint.md` (privado):

- Arquivos, comandos ou features citados que não existem (ou o contrário).
- Itens da seção "Problemas conhecidos" do `AGENTS.md` que já foram resolvidos ou que ainda estão abertos.

## 5. Filtro de complexidade

Um risco declarado do projeto é "criar sistemas complexos demais e abandoná-los". Antes de sugerir qualquer coisa, pergunte: isso faz o bot ser **usado** no dia a dia, ou só deixa o sistema maior? Prefira consertar e estabilizar a adicionar features.

## Formato do relatório

Responda em português, direto, sem elogios genéricos:

```
ESTADO GERAL
1–3 frases. O bot roda? Está sendo usado? O que mudou desde a última vez?

PROBLEMAS
Ordenados por gravidade. Cada um com arquivo:linha, o que acontece e o cenário concreto em que quebra.
Separe "corrigir antes de usar" de "menores".

DOCUMENTAÇÃO DESATUALIZADA
Só se houver.

PRÓXIMOS PASSOS
AGORA     — no máximo 3 itens, os que destravam uso real
DEPOIS    — o que vale fazer quando o AGORA estiver estável
NÃO AGORA — ideias tentadoras que devem esperar, e por quê
```

No final, ofereça (sem executar): corrigir os itens do AGORA e atualizar a seção "Problemas conhecidos" do `AGENTS.md`.
