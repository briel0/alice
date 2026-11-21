# AGENTS.md

Instruções para agentes de IA (Claude Code, Codex, Antigravity etc.) trabalhando neste repositório.

## O que é

**ALICE**: bot de Telegram que atua como **assistente pessoal**. Recebe texto/áudio, raciocina com Gemini e mantém tarefas em Markdown. Também expõe o mesmo estado por um servidor MCP.

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
- Testes: `uv run pytest` (`tests/test_reminders.py` e `tests/test_notificacoes.py`, que inclui o teste da fronteira do filtro). Não há linter. O `claude-mod/` tem testes próprios (`claude plugin test claude-mod`).

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
src/planner.py     cliente da API do Planner (opcional): só cria cartões
src/treinos.py     cliente da API do Treinos (opcional): registra e tira exercícios do treino do dia, grava peso
src/cfpick.py      sorteio de problemas do Codeforces para treino de ICPC (opcional, CF_HANDLE); estado em data/cfpick/, cache em .cache/
src/notificacoes/  filtro de e-mails (item 14): Gmail só leitura, regras, classificador sem ferramentas, alertas e resumos; nunca importa o agente
scripts/           utilitários de linha de comando (gmail_autorizar.py: OAuth do Gmail, uma vez no PC)
src/reminders.py   lembretes avulsos em data/lembretes.json (bot e MCP escrevem, com trava em .cache/); o bot envia os vencidos
tests/             testes pytest
examples/          modelos genéricos dos arquivos de data/
deploy/            serviço systemd, wrappers e backup para rodar numa VM
claude-mod/        identidade visual da ALICE dentro do Claude Code
```


## Convenções

- Código e comentários em português, como o código existente. Mensagens de commit no estilo Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`).
- Imports absolutos a partir de `src` (`from src.config import ...`).
- Mantenha simples. Não adicione frameworks, camadas ou features que não foram pedidas.
- Configuração nova vai em `src/config.py` lida do `.env`, e a chave correspondente vai em `.env.example`.
- Integrações opcionais (Planner, Treinos, Codeforces) só entram nas ferramentas e no prompt quando estão configuradas no `.env` (`PLANNER_API_URL`, `TREINOS_API_URL`, `CF_HANDLE`).
- O catálogo de gyms do Codeforces (`gym-discover`) só é montado pela linha de comando: é demorado e nunca vira ferramenta do Gemini.
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
2. Chamada síncrona ao Gemini: os handlers do Telegram já a rodam em outra thread (`asyncio.to_thread`), então o event loop e os lembretes não travam. Migrar para `client.aio` continua como melhoria. Os updates ainda são processados um por vez; só os botões dos lembretes (`block=False`) passam na frente.
3. `/tarefas` quebra se o arquivo passar de 4096 caracteres; `/hoje` é igual a `/tarefas`.
4. `guardrails.py` só conta uso do Claude; o caminho do Claude em `agent.py` usa um modelo aposentado e não é usado.
5. Melhoria futura: registrar em cada mensagem de `data/historico.jsonl` o canal de origem (`telegram` ou `cli`).
6. Interface de voz — primeiro objetivo: conversar com a ALICE pelo microfone e alto-falante do PC, com respostas faladas e acesso às tarefas e memórias. Não implementar nesta etapa.
7. Ideia futura, após validar a voz no PC: Echo Dot ou hardware próprio como interface de voz (Alexa Skill, privacidade, custos, backend 24/7). Não implementar nesta etapa.
8. Planner: hoje `src/planner.py` só cria cartões. Próxima ferramenta: ler os cartões que existem (por categoria e dentro de um cartão), para a ALICE responder perguntas sobre eles. **Prioridade da sessão de 31/10/2026.**
9. Backup do banco do Planner: hoje só o snapshot da VM cobre. Avaliar um `pg_dump` diário junto do backup de `data/` (`deploy/bin/alice-backup`), indo para o repositório privado de dados.
10. Registrar gastos pela ALICE. **Prioridade da sessão de 31/10/2026.** Nada decidido ainda: onde guardar (API própria como o Treinos, schema no Postgres da VPS, planilha), categorias, forma de pagamento, parcelas. Começar pelo minimundo, decidindo uma coisa de cada vez. Fase 1: registrar pela conversa ("gastei 42,90 no iFood, almoço").
    - Fase 2, depois da fase 1 e dos avisos (item 12): captura automática pelas notificações do banco no celular (Android). Um app de automação (MacroDroid ou Tasker) lê a notificação e a envia por HTTP; a ALICE extrai valor e estabelecimento e pergunta no Telegram do que se trata. Decidir como o celular chega na VPS (endpoint HTTPS público com token, ou Tailscale sem nada exposto; atenção à RAM). O texto da notificação não é confiável (a descrição de um Pix vem nela): extrair valor e estabelecimento por código, com padrões do formato do banco, e nunca passar o texto bruto ao agente com ferramentas.
11. Treinos: responder "quanto peguei da última vez?" no celular, entre uma série e outra. Começar só com `exercise_history(exercício, n)`, sem `get_workout` nem `get_body_weights` por enquanto. Adiado de propósito: reavaliar depois de 2 ou 3 semanas de treinos registrados. Se o usuário não tiver sentido falta de perguntar, tirar do backlog. Até lá, o prompt avisa que a ALICE não lê os treinos gravados.
12. Avisos proativos. **MVP feito (17/11/2026): lembretes avulsos** ("me lembra amanhã às 9h").
    - Como funciona: loop asyncio no processo do bot (a cada 30 s) lê `data/lembretes.json` e manda os vencidos com os botões ✅ Feito / ⏰ +1h / 📅 Amanhã 9h. Lembretes criados pelo Gemini ou pelo MCP (`add_reminder`, `list_reminders`, `cancel_reminder`); o LLM converte a data em ISO com fuso, o código valida (futuro, com fuso) e a resposta repete a data absoluta. Sem hora dita: 9h (tarde 14h, noite 20h). `/lembretes` lista com botão de cancelar. Atrasados (bot fora do ar) saem todos, marcados, agrupados se forem mais de 3. Commit em `data/.git` só na criação e no cancelamento.
    - Descartados: `JobQueue` do python-telegram-bot (APScheduler a mais na RAM, jobs só em memória) e timer do systemd (um processo por disparo, botões voltariam ao bot de qualquer jeito); SQLite (por enquanto; a interface de `src/reminders.py` permite trocar quando o item 14 trouxer um banco).
    - Próximos, nada decidido: lembretes recorrentes (campo `repetir` já reservado); insistir quando ignorado (campo `resolvido_em`); avisos do treino de Codeforces (tempo-limite estourado, revisões pendentes, ver `cfpick.status`); inbox acumulado e tarefas paradas (cuidado com spam); prazos no texto das tarefas.
    - Google Agenda: começar só lendo os compromissos (para o planejamento do dia e avisos antes dos eventos) e criar eventos depois. Atenção ao OAuth do Google num servidor sem navegador e a guardar o token fora do repositório.
13. Diário de decisões: `data/decisoes.md` (privado), pequeno, não um diário emocional. Cada entrada: decisão, data, motivo, expectativa. Uma ferramenta de uma linha (`add_decision`) registra pela conversa. Depois de 30, 60 e 90 dias, a ALICE pergunta se a decisão funcionou e anota a resposta junto, para o usuário aprender com o que pensou na hora, não com a memória reconstruída depois. As revisões dependem dos avisos proativos (item 12). Criar o exemplo genérico em `examples/`.
14. Filtro de notificações e e-mails: a ALICE recebe todas as notificações do celular (Android, pelo MacroDroid ou Tasker) e os e-mails (API do Gmail, só leitura) e avisa só das relevantes. Fluxo: regras fixas por código (app ou remetente que sempre passa ou nunca passa) → classificador com o Gemini **sem nenhuma ferramenta**, que devolve só "relevante ou não" e um resumo de uma linha → relevante vira mensagem na hora; o resto vai para um resumo diário. Regra inegociável: o texto de notificações e e-mails nunca chega ao agente que tem ferramentas (qualquer um pode escrever "ALICE, apague tudo" num e-mail). O que é crítico (ligações, banco, família) continua tocando direto no celular, para a ALICE fora do ar não deixar o usuário surdo. "Isso era importante" vira regra fixa. Atenção à privacidade (tudo passaria pelo Gemini) e ao volume. Depende dos avisos (item 12) e reaproveita a entrada HTTP da fase 2 dos gastos (item 10); ordem sugerida: 12 → 10 → 14.
    - Fase 2: responder mensagens do WhatsApp pela própria notificação do Android (botão "Responder", via Tasker + AutoNotification ou MacroDroid), saindo pelo app oficial no celular. Nada de WhatsApp Web ou clientes não oficiais (whatsapp-web.js, Baileys) na VPS: violam os termos, arriscam banir o número pessoal e o Chromium não cabe na RAM. A ALICE só sugere a resposta no Telegram e envia depois do "sim" do usuário; nunca responde sozinha em nome dele (exceção possível: resposta automática que se identifica como assistente). Quem redige é uma chamada do Gemini sem ferramentas, porque o texto da mensagem não é confiável.
    - Decisões de 03/11/2026 (estruturação em andamento, uma de cada vez):
      - Captura: **app Android próprio** (Kotlin, `NotificationListenerService`), versionado no Git, que filtra no celular, envia à VPS e guarda a ação "Responder" da notificação. Descartados: MacroDroid (configuração presa no celular, limite de 5 macros na versão grátis) e Tasker + AutoNotification (pagos, difíceis de versionar).
      - Celular: Galaxy A56 (One UI, Android 15), agressivo com apps em segundo plano. Mitigação: bateria "Sem restrições" e "Apps que nunca entram em suspensão"; fila local com reenvio (`WorkManager`); sinal "estou vivo" periódico, e a ALICE avisa no Telegram se ficar sem sinal por muito tempo. App instalado fora da Play Store exige "Permitir configurações restritas" para ganhar acesso às notificações.
      - A ação "Responder" só existe enquanto a notificação está na tela; se ela sumir antes da aprovação, a ALICE avisa em vez de falhar calada.
      - Transporte celular → VPS: **Tailscale** (item 16), sem porta aberta na internet; o mesmo passo libera o Dojo e o Planner no celular. O usuário não usa outra VPN (o Android só aceita uma por vez). Descartados: endpoint HTTPS público com token (exige domínio, porta exposta) e Cloudflare Tunnel (exige domínio, endereço público).
      - Entrada na VPS: **dentro do processo da ALICE**, num módulo isolado (`src/notificacoes/`) com servidor `aiohttp` ouvindo só no endereço do Tailscale, mais um token do app. Motivos: o Telegram entrega as atualizações do bot (inclusive os botões) a um processo só, e a RAM livre é pouca. A fronteira é garantida por um teste que falha se o módulo importar o agente com ferramentas; o classificador só devolve rótulo e resumo validados. Descartados: serviço separado (uns 50 MB e os botões passariam pelo bot mesmo assim) e um segundo bot no Telegram (dois chats).
      - Armazenamento: notificações recebidas num **SQLite** fora do repositório de dados (`/var/lib/alice/notificacoes.db`, módulo `sqlite3` da biblioteca padrão), apagadas depois de 30 dias e sem backup (são descartáveis); regras num arquivo legível em `data/`, coberto pelo backup diário. Descartados: Postgres num schema próprio (driver, role e migrações para dados passageiros; migrar é simples se outro programa precisar deles) e arquivos em `data/` (o texto das notificações iria para o Git todo dia).
      - Papel: a ALICE é **o filtro**. Apps barulhentos ficam silenciosos no Android (o app continua recebendo tudo) e a ALICE avisa pelo Telegram o que importa; o crítico continua tocando. Migração aos poucos: na primeira semana ela só classifica e o usuário compara; silencia um app quando ela acertar com consistência. Descartados: ALICE como camada a mais (não reduz interrupção) e o app apagar notificações (some com o "Responder" e um erro não deixa rastro).
      - Classificador: **em lotes**. Junta o que passar das regras em janelas de 5 minutos (no máximo uns 30 itens, cada texto cortado em 500 caracteres) e classifica numa chamada; contatos marcados como importantes nas regras avisam na hora, sem Gemini. Chave de **outro projeto do Google** (os limites são por projeto), para nunca gastar a cota da conversa. Contador diário no SQLite: perto do limite, tudo vai para o resumo sem chamar o Gemini. Saída estruturada e validada por código (`id`, `nivel` agora/resumo/silencio, `resumo` de até 120 caracteres, `sugerir_resposta`); fora do formato, o lote inteiro vai para o resumo. A cota grátis não está clara (fontes de terceiros citam uns 500 pedidos por dia no Flash-Lite): confirmar no AI Studio e reduzir a janela se sobrar. Descartados: uma chamada por notificação (estoura a cota) e só regras (não entende conteúdo).
      - Relevância: regras fixas (lidas por código, sem Gemini) + critérios em texto para o classificador, num arquivo Markdown em `data/` (seções "Avisar na hora", "Resumo diário", "Silêncio", "Critérios"). Começa **quase vazio**, só com critérios genéricos; as regras crescem pelos botões 👍 importante / 👎 ruído em cada aviso e item do resumo, que **propõem** uma regra (por app ou remetente) e só a gravam depois da confirmação do usuário. Descartados: o usuário escrever tudo no começo e categorias genéricas prontas.
      - Privacidade: o usuário aceita que o conteúdo passe pelo Gemini mesmo na camada grátis (que pode usar os dados para treino).
    - **Gmail feito (20/11/2026)**, antes do WhatsApp (que entra depois como segunda fonte, pelo app Android e Tailscale). Código em `src/notificacoes/`, passo a passo em `deploy/README.md`. Decisões:
      - Leitura: **API do Gmail com `gmail.readonly`** (o próprio Google garante que não dá para apagar, enviar nem marcar como lido), chamada pelo `httpx`, sem a biblioteca do Google. App OAuth publicado "Em produção" sem verificação (em "Teste" o token expira em 7 dias). Descartado: IMAP com senha de app (acesso total à caixa).
      - Entrada: Principal e Atualizações vão para o Gemini; Promoções, Social e Fóruns vão para silêncio sem Gemini; spam e enviados ficam fora. As regras fixas do arquivo valem antes das categorias.
      - Descoberta: **`history.list` a cada 5 min** a partir do `historyId` guardado no SQLite; um lote por rodada. A primeira rodada começa de agora. Se o `historyId` expirar, relê os últimos 2 dias sem alertar (o que seria "agora" vai para o resumo). Descartados: push por Pub/Sub (infraestrutura a mais por uns minutos) e consulta a cada 1 min.
      - Conteúdo: só remetente, assunto, categoria e o snippet do Gmail (formato `metadata`; o corpo nunca é baixado). Códigos de verificação viram `••••` antes do Gemini e do SQLite.
      - Alerta: remetente, assunto, resumo de 1 linha e motivo, com 👍/👎 e "Abrir no Gmail", enviado direto pela API do bot, **fora do histórico do agente** (responder ao alerta não passa o conteúdo à ALICE). Descartado: botão "Perguntar à ALICE".
      - Resumos às **12h e 19h**, agrupados por remetente, 👍/👎 por item, contagem dos silenciados com botão "ver silenciados"; resumo vazio não sai. Rodam no loop do filtro, no processo do bot; com o bot fora do ar, saem na volta.
      - 👍 propõe regra "avisar na hora"; 👎 propõe descer um nível (agora → resumo → silêncio), para o endereço ou o domínio inteiro (domínio não é oferecido para webmail). Só grava depois do "sim".
      - Começo: **uma semana em modo sombra** (`NOTIF_SOMBRA=1`, prefixo 🧪, o app do Gmail continua notificando no celular). Depois de 7 dias sai um balanço (também em `/filtro`); o usuário decide quando desligar o Gmail no celular e pôr `NOTIF_SOMBRA=0`.
      - Credenciais: cliente OAuth "App para computador" no **mesmo projeto separado** da chave do classificador. `scripts/gmail_autorizar.py` roda uma vez no PC; o token fica em `/etc/alice/gmail-token.json` (root, 600) e chega ao serviço por `LoadCredential` (drop-in em `deploy/alice.service.d/`). Token revogado: avisa uma vez e para até o token mudar.
      - Critérios iniciais genéricos em `examples/notificacoes-regras.example.md` (usado enquanto não existe `data/notificacoes-regras.md`), com "na dúvida, o nível mais alto".
      - O servidor `aiohttp` da decisão "Entrada na VPS" fica para o WhatsApp: o Gmail não precisa de entrada HTTP. O campo `sugerir_resposta` do classificador também (só faz sentido para mensagens).
15. Knowledge base: conteúdo maior que as memórias vivas, consultado sob demanda em vez de entrar inteiro no prompt (`memorias_vivas.md` continua com os fatos curtos sobre o usuário). Falta decidir o que será guardado: notas e anotações de estudo cabem na fase 1; PDFs, livros ou centenas de documentos exigem extração de texto e embeddings. Não passa na frente dos itens 8 e 10.
    - Fase 1: arquivos em `data/kb/*.md` (privado, já coberto pelo backup), com exemplo genérico em `examples/`, e `src/kb.py` com `search_notes(query)` (busca por palavras, reaproveitando `storage.normalize`), `read_note(name)` e `add_note(title, content)` (cria sem sobrescrever). Mesmas ferramentas no Telegram e no MCP. Sem dependência nova.
    - Fase 2, só se a busca por palavras falhar na prática: embeddings pela API do Gemini, com pgvector num schema separado no Postgres da VPS (confirmar se a extensão pode ser instalada na instância; incluir o schema no `pg_dump` do item 9). Os `.md` continuam sendo a fonte da verdade e o índice pode ser recriado. Nada de modelo local nem de serviço dedicado de vetores, por causa da RAM.
    - Conteúdo externo (PDF, página, e-mail) não é confiável: fica fora da fase 1 e, quando entrar, passa antes por uma chamada sem ferramentas, como no item 14. O trecho consultado vai para o Gemini, então documentos sensíveis ficam de fora ou com acesso restrito.
16. Tailscale: rede privada entre o celular, o PC e a VPS, para abrir o painel e o Planner no celular sem expor portas nem depender de túnel SSH. Hoje o painel começa por túnel SSH, como o Planner. Grátis no plano pessoal (confirmar os limites), mas o processo consome RAM na VM e a conta precisa de verificação em duas etapas. Também é uma das opções para o celular chegar na VPS na fase 2 dos gastos (item 10).
17. Estética no Telegram: o bot não controla tema, fundo nem fonte do chat (são do usuário), só o conteúdo e o perfil. Por ordem de custo: foto, descrição e imagem de boas-vindas pelo BotFather; fundo escuro com âmbar só no chat da ALICE (configurado pelo usuário, combina com o Dojo); vocabulário pequeno de emojis por assunto no prompt (treino, tarefa, compra), sem poluir, partindo da identidade do `claude-mod/`; imagens geradas no visual do Dojo (quadrinho ou resumo do treino, por comando ou num resumo semanal). Mais tarde: pacote de figurinhas próprio e Mini App (página do Dojo dentro do Telegram; exige HTTPS, o que conflita com o acesso só por túnel; testar com o Tailscale, item 16). Emojis personalizados parecem exigir um nome de usuário comprado na Fragment: confirmar antes.
18. Front ou app próprio da ALICE: em algum momento ela deixa de depender só do Telegram e ganha uma interface própria (web, e talvez app no celular), para centralizar conversa e painel num lugar só. Nada decidido. Pontos de partida: o Dojo já é o painel do ecossistema; o app Android das notificações (item 14) pode virar a base do app; o Tailscale (item 16) resolve o acesso sem expor nada. A conversa pelo Telegram continua funcionando enquanto isso.
