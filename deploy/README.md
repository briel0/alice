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
4. Crie `/etc/alice/alice.env` (root, `600`) com as variáveis de `.env.example`. Para usar só o Gemini, deixe `ANTHROPIC_API_KEY` ausente.
5. Copie os arquivos de systemd e os wrappers:
   ```sh
   sudo install -m 755 deploy/bin/* /opt/alice/bin/
   sudo cp deploy/alice.service deploy/alice-backup.service deploy/alice-backup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now alice alice-backup.timer
   ```
6. Teste pelo Telegram: `/start`, um pedido simples e `/tarefas`. Confira `git -C /opt/alice/app/data log` para ver o commit da mudança.

## Wrappers (`deploy/bin`)

- `alice-mcp`: MCP em stdio como `alice` (`sudo -u alice`); não precisa de segredos.
- `alice-cli`: carrega `/etc/alice/alice.env` como root e desce para `alice` com `runuser`.
- `alice-status`: imprime `tarefas.md`, a linha `<<<ALICE-MEMORIAS>>>` e `memorias_vivas.md` (usado pelo cabeçalho do `claude-mod`).
- `alice-backup`: commit do que mudou em `data/` e push para o remoto privado.

## Backup

- Cada mudança de tarefa vira um commit local em `data/` (feito pelo próprio bot).
- `alice-backup.timer` roda `alice-backup` todo dia às 03:30 (Brasília) e envia tudo ao repositório privado. `Persistent=true` executa o backup perdido se a VM estava desligada.
- A chave da VM é uma deploy key com escrita **só** no repositório de dados.
- Rodar na hora: `sudo systemctl start alice-backup`. Ver resultado: `journalctl -u alice-backup -n 20`.
- Snapshots automáticos do provedor são uma segunda camada barata.

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
