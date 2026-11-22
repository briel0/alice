# ALICE 24/7 em uma VM Linux

Roda com systemd numa VM pequena (Ubuntu 24.04, 512 MB + swap bastam). Não precisa de Docker, porta HTTP pública nem domínio: o bot só abre conexões de saída para o Telegram.

## Fonte única da verdade

`/opt/alice/app/data/` na VM é a **única** cópia dos dados. Nada é sincronizado:

- O bot do Telegram roda na VM.
- Agentes no PC usam o MCP **na VM**, por SSH (veja `mcp_config_guide.md`).
- A CLI roda na VM via `ssh -t`.
- Não rode o polling do mesmo token em dois lugares (dá erro 409).

## Layout na VM

```
/opt/alice/app          código (clone deste repositório público)
/opt/alice/app/data     dados; repositório git próprio, privado (remoto: seu repo de dados)
/opt/alice/bin          wrappers de deploy/bin (root, 755)
/opt/alice/.ssh         chave de deploy com escrita só no repo de dados
/etc/alice/alice.env    segredos (root, 600), lido pelo systemd
```

## Instalação

1. Crie o usuário de sistema `alice` com home `/opt/alice`, instale git e uv para ele.
2. Como `alice`: `git clone https://github.com/<você>/alice.git /opt/alice/app` e `uv sync --locked --no-dev --python 3.14` dentro dele.
3. Dados: clone seu repositório privado de dados em `/opt/alice/app/data` (ou crie um novo a partir de `examples/`). Deixe `data/` com permissão `700`. Um `data/.gitignore` com `audio_temp/` evita versionar áudios temporários.
4. Crie `/etc/alice/alice.env` (root, `600`) com as variáveis de `.env.example`.
5. Copie os arquivos de systemd e os wrappers:
   ```sh
   sudo install -m 755 deploy/bin/* /opt/alice/bin/
   sudo cp deploy/alice.service deploy/alice-backup.service deploy/alice-backup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now alice alice-backup.timer
   ```
6. Teste pelo Telegram: `/start`, um pedido simples e `/tarefas`. Confira `git -C /opt/alice/app/data log` para ver o commit da mudança.

## Filtro de e-mails (opcional, item 14 do AGENTS.md)

A ALICE lê o Gmail **só com permissão de leitura** (`gmail.readonly`), a cada 5 min, e avisa no Telegram o que importa; o resto vai para os resumos das 12h e 19h. O texto dos e-mails nunca chega ao agente com ferramentas.

1. **Projeto separado no Google Cloud** (console.cloud.google.com → novo projeto, ex.: `alice-notificacoes`). Ative a **Gmail API**.
2. **Tela de consentimento OAuth**: tipo "Externo", adicione o escopo `.../auth/gmail.readonly` e **publique o app** ("Publicar app" → "Em produção"). Não precisa enviar para verificação: para uso só seu basta passar pela tela "O Google não verificou este app" no login. Em modo "Teste" o token expira a cada 7 dias.
3. **Credenciais** → "Criar credenciais" → "ID do cliente OAuth" → tipo **App para computador**. Baixe o JSON.
4. **Chave do Gemini do mesmo projeto** (aistudio.google.com → "Get API key" → escolha o projeto `alice-notificacoes`). Assim o classificador nunca gasta a cota da conversa.
5. **No PC**, autorize uma vez (abre o navegador; aceite só a leitura):
   ```sh
   uv run python scripts/gmail_autorizar.py caminho/do/client_secret.json
   scp .cache/gmail-token.json alice-vm:/tmp/gmail-token.json
   ```
   Depois apague `.cache/gmail-token.json` e o JSON do cliente do PC.
6. **Na VM**:
   ```sh
   sudo install -o root -g root -m 600 /tmp/gmail-token.json /etc/alice/gmail-token.json && rm /tmp/gmail-token.json
   sudo -u alice cp -n /opt/alice/app/examples/notificacoes-regras.example.md /opt/alice/app/data/notificacoes-regras.md
   sudo install -D -m 644 /opt/alice/app/deploy/alice.service.d/gmail.conf /etc/systemd/system/alice.service.d/gmail.conf
   sudo cp /opt/alice/app/deploy/alice.service /etc/systemd/system/   # cria /var/lib/alice (StateDirectory)
   ```
   O token continua só do root; o systemd entrega uma cópia ao serviço (`LoadCredential`). No `/etc/alice/alice.env`:
   ```
   NOTIF_GMAIL_TOKEN_PATH=/run/credentials/alice.service/gmail-token.json
   NOTIF_GEMINI_API_KEY=<chave do passo 4>
   NOTIF_DB_PATH=/var/lib/alice/notificacoes.db
   ```
   Depois `sudo systemctl daemon-reload && sudo systemctl restart alice`.
7. A primeira rodada começa **de agora** (não varre a caixa antiga). A primeira semana é o **modo sombra**: tudo sai com 🧪 e o app do Gmail no celular continua notificando. Depois de 7 dias chega um balanço (ou peça com `/filtro`); se estiver bom, desligue as notificações do Gmail no celular e ponha `NOTIF_SOMBRA=0` no `alice.env`.

Se o Google revogar a autorização (senha trocada, acesso removido em myaccount.google.com/permissions), a ALICE avisa uma vez e para de ler; refaça os passos 5 e 6 e reinicie a ALICE (o token novo destrava sozinho). O SQLite guarda remetente, assunto e snippet por 30 dias, sem backup.

## Wrappers (`deploy/bin`)

- `alice-mcp`: MCP em stdio como `alice` (`sudo -u alice`); não carrega `/etc/alice/alice.env`. Para o MCP também criar cartões no Planner, ponha só `PLANNER_API_URL` (e `PLANNER_INBOX_CATEGORY`, se usar) em `/opt/alice/app/.env` (dono `alice`, `600`). A URL não é segredo. O mesmo vale para o treino de Codeforces: só o `CF_HANDLE` (as chaves da API ficam no `alice.env`).
- `alice-cli`: carrega `/etc/alice/alice.env` como root e desce para `alice` com `runuser`.
- `alice-status`: imprime `tarefas.md`, a linha `<<<ALICE-MEMORIAS>>>` e `memorias_vivas.md` (usado pelo cabeçalho do `claude-mod`).
- `alice-backup`: commit do que mudou em `data/` e push para o remoto privado.
- `alice-cfpick`: seletor de problemas do Codeforces pela linha de comando, como `alice` com o `alice.env`. O catálogo de gyms não se atualiza sozinho: rode `sudo /opt/alice/bin/alice-cfpick gym-discover --dry` para conferir a lista e `sudo /opt/alice/bin/alice-cfpick gym-discover` para baixar os gyms novos (demora; se a rede cair, rodar de novo continua de onde parou). Precisa de `CF_API_KEY` e `CF_API_SECRET`.
- `alice-dump-treinos`: exporta o schema do Treinos com `pg_dump` para `data/backups/treinos.sql` (roda como root, antes do `alice-backup`).

## Backup

- Cada mudança de tarefa vira um commit local em `data/` (feito pelo próprio bot).
- `alice-backup.timer` roda `alice-backup` todo dia às 03:30 (Brasília) e envia tudo ao repositório privado. `Persistent=true` executa o backup perdido se a VM estava desligada.
- A chave da VM é uma deploy key com escrita **só** no repositório de dados.
- Rodar na hora: `sudo systemctl start alice-backup`. Ver resultado: `journalctl -u alice-backup -n 20`.
- Snapshots automáticos do provedor são uma segunda camada barata.
- O dump do Treinos vai junto. Se ele falhar, o backup de `data/` segue com o arquivo anterior e a falha aparece só no journal: confira de vez em quando a data do arquivo.
- Restaurar o dump num banco vazio: `sudo -u postgres createdb <banco>`, depois `sudo cat data/backups/treinos.sql | sudo -u postgres psql -d <banco> -v ON_ERROR_STOP=1`. Ele não recria o usuário `treinos` nem as permissões.

## Atualizar o código

```sh
sudo -u alice git -C /opt/alice/app pull --ff-only
sudo -u alice sh -c 'cd /opt/alice/app && /opt/alice/.local/bin/uv sync --locked --no-dev'
sudo systemctl restart alice
```

## Problemas comuns

- **409 Conflict**: outra instância está fazendo polling com o mesmo token.
- **Falhas repetidas na inicialização**: corrija a causa e rode `systemctl reset-failed alice`.
- O serviço recusa iniciar sem `ALLOWED_TELEGRAM_USER_ID`, token e uma chave de API.
