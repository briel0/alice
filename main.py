import sys
from pathlib import Path

# Garante suporte a UTF-8 no terminal Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Adiciona o diretório raiz ao path para importação limpa
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.bot import run_bot

if __name__ == "__main__":
    run_bot()
