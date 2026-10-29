# 🚀 Guia Rápido de Deploy no AWS Lightsail (ALICE + PostgreSQL)

Com este setup, a ALICE e o seu PostgreSQL sobem juntos com **1 único comando**, com persistência total em disco.

---

### Passo 1: Criar a Instância no Lightsail
1. Acesse o [Console do AWS Lightsail](https://lightsail.aws.amazon.com/).
2. Clique em **"Create instance"**.
3. Escolha:
   * **Plataforma:** Linux/Unix
   * **Blueprint:** OS Only -> **Ubuntu 24.04 LTS**
   * **Plano:** $5.00/mês (1 GB RAM, 1 vCPU, 40 GB SSD) — *Primeiros 3 meses grátis*.
4. Dê um nome (ex: `alice-server`) e clique em **Create instance**.

---

### Passo 2: Configurar o Firewall no Lightsail
1. Na aba **Networking** da sua instância, adicione:
   * Porta **5432 (TCP)** se quiser acessar o Postgres de fora pelo seu PC (recomendado restringir ao seu IP residencial se quiser segurança extra).
   * Porta **22 (SSH)** já vem aberta por padrão.

---

### Passo 3: Conectar e Subir a Stack (1 Comando)
Abra o terminal SSH (direto pelo botão no navegador do Lightsail ou via terminal local):

```bash
# 1. Instalar Docker e Docker Compose
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
newgrp docker

# 2. Clonar o repositório
git clone https://github.com/briel0/alice.git
cd alice

# 3. Criar o arquivo .env
cp .env.example .env
nano .env  # Coloque seu TELEGRAM_BOT_TOKEN, GEMINI_API_KEY e ALLOWED_TELEGRAM_USER_ID

# 4. Iniciar tudo (ALICE + Postgres)
docker compose up -d --build
```

---

### Comandos Úteis no Servidor:
* Ver logs da ALICE em tempo real: `docker compose logs -f alice`
* Ver logs do Postgres: `docker compose logs -f postgres`
* Reiniciar tudo: `docker compose restart`
* Parar tudo: `docker compose down`

Os dados do Postgres (`pgdata`) e os arquivos Markdown (`data/`) ficam gravados no SSD da máquina e sobrevivem a qualquer reinicialização.
