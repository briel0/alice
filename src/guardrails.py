"""Disjuntor de Segurança (Circuit Breaker) para controle de custos e consumo de APIs.

Garante que o bot nunca ultrapasse limites financeiros ou de requisições diárias.
"""

import json
from datetime import datetime
from pathlib import Path
from src.config import DATA_DIR, BASE_DIR

USAGE_FILE = DATA_DIR / "usage_tracker.json"

# Preços aproximados por milhão de tokens (Claude 3.5 Haiku)
PRICE_PER_M_INPUT = 0.80   # $0.80 por 1M tokens de entrada
PRICE_PER_M_OUTPUT = 4.00  # $4.00 por 1M tokens de saída

# Tetos diários de segurança padrão
DEFAULT_MAX_REQUESTS_PER_DAY = 60
DEFAULT_MAX_COST_USD_PER_DAY = 0.35  # ~$0.35 USD (cerca de R$ 2,00 por dia)

def _get_today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def load_usage() -> dict:
    today = _get_today_str()
    if not USAGE_FILE.exists():
        return {"date": today, "requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        if data.get("date") != today:
            # Novo dia, reseta contadores
            return {"date": today, "requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
        return data
    except Exception:
        return {"date": today, "requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}

def save_usage(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def check_guardrails() -> tuple[bool, str]:
    """Verifica se a chamada atual é permitida ou se atingiu o teto diário."""
    usage = load_usage()
    
    requests = usage.get("requests", 0)
    cost = usage.get("estimated_cost_usd", 0.0)
    
    if requests >= DEFAULT_MAX_REQUESTS_PER_DAY:
        return False, (
            f"🛡️ *Trava de Segurança Ativada:*\n"
            f"Você atingiu o limite de {DEFAULT_MAX_REQUESTS_PER_DAY} requisições hoje ({requests} enviadas).\n"
            f"Novas chamadas pausadas para sua proteção até amanhã."
        )
        
    if cost >= DEFAULT_MAX_COST_USD_PER_DAY:
        return False, (
            f"🛡️ *Trava de Custo Ativada:*\n"
            f"O consumo diário atingiu ${cost:.3f} (teto de segurança: ${DEFAULT_MAX_COST_USD_PER_DAY:.2f}).\n"
            f"Chamadas pausadas para proteger seu orçamento até amanhã."
        )
        
    return True, ""

def record_token_usage(input_tokens: int, output_tokens: int) -> dict:
    """Registra tokens gastos e calcula o custo estimado."""
    usage = load_usage()
    
    usage["requests"] += 1
    usage["input_tokens"] += input_tokens
    usage["output_tokens"] += output_tokens
    
    cost_input = (input_tokens / 1_000_000) * PRICE_PER_M_INPUT
    cost_output = (output_tokens / 1_000_000) * PRICE_PER_M_OUTPUT
    usage["estimated_cost_usd"] = round(usage["estimated_cost_usd"] + cost_input + cost_output, 4)
    
    save_usage(usage)
    return usage

def get_usage_summary() -> str:
    """Retorna um resumo amigável do consumo atual do dia."""
    usage = load_usage()
    return (
        f"[CONSUMO DE HOJE: {usage.get('date')}]\n"
        f"- Requisicoes: {usage.get('requests', 0)} / {DEFAULT_MAX_REQUESTS_PER_DAY}\n"
        f"- Tokens: {usage.get('input_tokens', 0):,} in / {usage.get('output_tokens', 0):,} out\n"
        f"- Custo Estimado: ${usage.get('estimated_cost_usd', 0.0):.4f} USD (teto maximo diario: ${DEFAULT_MAX_COST_USD_PER_DAY:.2f})"
    )
