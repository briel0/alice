import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis do arquivo .env
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Como a ALICE chama o usuário (opcional)
USER_NAME = os.getenv("USER_NAME", "").strip()

raw_user_id =os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
ALLOWED_TELEGRAM_USER_ID = int(raw_user_id) if raw_user_id.isdigit() else None

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TASKS_FILE = DATA_DIR / "tarefas.md"
AUDIO_DIR = DATA_DIR / "audio_temp"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Modelos padrão
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-latest")

# Planner (opcional): API de quadros de projetos. Sem URL, a ferramenta create_card não é oferecida.
PLANNER_API_URL = os.getenv("PLANNER_API_URL", "").strip().rstrip("/")
PLANNER_INBOX_CATEGORY = os.getenv("PLANNER_INBOX_CATEGORY", "Inbox").strip() or "Inbox"

# Treinos (opcional): API de registro de treinos e peso corporal. Sem URL, as ferramentas de treino não são oferecidas.
TREINOS_API_URL = os.getenv("TREINOS_API_URL", "").strip().rstrip("/")

# Codeforces (opcional): sorteio de problemas para treino de ICPC. Sem handle, as ferramentas não são oferecidas.
# Chave e segredo da API só são usados para baixar placares de gym (src.cfpick gym-discover, pela linha de comando).
CF_HANDLE = os.getenv("CF_HANDLE", "").strip()
CF_API_KEY = os.getenv("CF_API_KEY", "").strip()
CF_API_SECRET = os.getenv("CF_API_SECRET", "").strip()

# Filtro de notificações e e-mails (opcional, item 14). Sem token do Gmail e chave própria do Gemini, não roda.
# A chave é de outro projeto do Google, para o filtro nunca gastar a cota da conversa.
NOTIF_GMAIL_TOKEN_PATH = Path(os.getenv("NOTIF_GMAIL_TOKEN_PATH", "").strip() or BASE_DIR / ".cache" / "gmail-token.json")
NOTIF_GEMINI_API_KEY = os.getenv("NOTIF_GEMINI_API_KEY", "").strip()
NOTIF_GEMINI_MODEL = os.getenv("NOTIF_GEMINI_MODEL", "").strip() or GEMINI_MODEL
NOTIF_GEMINI_LIMITE_DIA = int(os.getenv("NOTIF_GEMINI_LIMITE_DIA", "150") or 150)
# Fora de data/: o texto dos e-mails não vai para o Git
NOTIF_DB_PATH = Path(os.getenv("NOTIF_DB_PATH", "").strip() or BASE_DIR / ".cache" / "notificacoes.db")
NOTIF_RULES_FILE = DATA_DIR / "notificacoes-regras.md"
# Modo sombra (primeira semana): tudo sai com 🧪 e o usuário ainda recebe as notificações do Gmail no celular
NOTIF_SOMBRA = os.getenv("NOTIF_SOMBRA", "1").strip() not in ("0", "false", "nao", "não")
NOTIF_ATIVO = bool(NOTIF_GEMINI_API_KEY) and NOTIF_GMAIL_TOKEN_PATH.exists()
