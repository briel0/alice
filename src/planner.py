"""Cliente mínimo da API do Planner (quadros de projetos).

A ALICE só CRIA cartões: capturar pelo Telegram é rápido; organizar, mover e editar é trabalho
de quem usa o Planner. A API é idempotente pelo id do cartão (UUID v7 gerado aqui), então um
pedido repetido não duplica nada.
"""

import uuid

import httpx

from src.config import PLANNER_API_URL, PLANNER_INBOX_CATEGORY
from src.storage import normalize

TIMEOUT_SECONDS = 10
# Folga entre o cartão novo e o último do quadro (a mesma do Planner, em placement.ts)
GAP = 24
TITLE_MAX_LENGTH = 200

def is_enabled() -> bool:
    return bool(PLANNER_API_URL)

def _position_below(cards: list[dict]) -> dict:
    """Logo abaixo do cartão mais baixo, alinhado à esquerda: nunca cai por cima de outro."""
    if not cards:
        return {"x": GAP, "y": GAP}
    left = min(c["position"]["x"] for c in cards)
    bottom = max(c["position"]["y"] + c["size"]["height"] for c in cards)
    return {"x": left, "y": bottom + GAP}

def _pick_category(categories: list[dict], wanted: str) -> tuple[dict | None, str]:
    """Categoria pedida (por trecho do nome) e uma observação quando ela não serviu."""
    if not wanted.strip():
        return None, ""
    exact = [c for c in categories if normalize(c["name"]) == normalize(wanted)]
    matches = exact or [c for c in categories if normalize(wanted) in normalize(c["name"])]
    if len(matches) == 1:
        return matches[0], ""
    if matches:
        names = ", ".join(c["name"] for c in matches)
        return None, f" ('{wanted}' casa com mais de uma categoria: {names}; ficou no {PLANNER_INBOX_CATEGORY})"
    return None, f" (não existe categoria '{wanted}'; ficou no {PLANNER_INBOX_CATEGORY})"

def _inbox(client: httpx.Client, categories: list[dict]) -> dict:
    """A categoria de entrada; criada na primeira vez que for precisa."""
    for category in categories:
        if normalize(category["name"]) == normalize(PLANNER_INBOX_CATEGORY):
            return category
    response = client.post("/api/categories", json={"id": str(uuid.uuid7()), "name": PLANNER_INBOX_CATEGORY})
    response.raise_for_status()
    return response.json()

def _text_doc(text: str) -> dict:
    """Descrição no formato do editor do Planner (documento do Tiptap): um parágrafo por linha."""
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs],
    }

def create_card(title: str, category: str = "", description: str = "") -> str:
    title = " ".join(title.split())[:TITLE_MAX_LENGTH]
    if not title:
        return "O cartão precisa de um título."
    try:
        with httpx.Client(base_url=PLANNER_API_URL, timeout=TIMEOUT_SECONDS) as client:
            response = client.get("/api/categories")
            response.raise_for_status()
            categories = response.json()
            target, note = _pick_category(categories, category)
            if target is None:
                target = _inbox(client, categories)

            response = client.get(f"/api/categories/{target['id']}/cards")
            response.raise_for_status()
            body = {"id": str(uuid.uuid7()), "title": title, "position": _position_below(response.json())}
            response = client.post(f"/api/categories/{target['id']}/cards", json=body)
            response.raise_for_status()
            card = response.json()
    except httpx.HTTPError as error:
        return (
            f"Não consegui falar com o Planner ({error.__class__.__name__}); nada foi criado lá. "
            "Ofereça anotar no INBOX do tarefas.md."
        )

    message = f"Cartão criado no Planner, em {target['name']}: {title}{note}"
    if description.strip():
        try:
            with httpx.Client(base_url=PLANNER_API_URL, timeout=TIMEOUT_SECONDS) as client:
                response = client.patch(f"/api/cards/{card['id']}", json={"content": _text_doc(description)})
                response.raise_for_status()
        except httpx.HTTPError:
            message += " (a descrição não foi salva)"
    return message
