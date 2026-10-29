import json
from datetime import datetime
from pathlib import Path
from src.config import DATA_DIR

HISTORY_FILE = DATA_DIR / "historico.jsonl"

def append_message(role: str, content: str, user_id: int | None = None) -> None:
    """Registra uma mensagem (user ou model) no arquivo persistente de histórico."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "role": role,  # 'user' ou 'model'
        "content": content,
        "user_id": user_id
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def get_recent_history(limit: int = 20) -> list[dict]:
    """Recupera as últimas N mensagens do histórico persistente."""
    if not HISTORY_FILE.exists():
        return []
        
    messages = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                    
    return messages[-limit:]

def clear_history() -> None:
    """Limpa o histórico de mensagens ativas se o usuário pedir reset."""
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
