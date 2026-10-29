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
