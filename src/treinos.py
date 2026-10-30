"""Cliente mínimo da API do Treinos (registro de treinos e peso corporal).

A ALICE registra um exercício por chamada, somando ao treino do dia: serve tanto para mandar o treino inteiro
numa mensagem (uma chamada por exercício) quanto para ir mandando durante o treino. Se ainda não existe treino
no dia, ela cria um. Os ids (UUID v7) são gerados aqui; a API não duplica um pedido repetido com o mesmo id.
"""

import uuid
from datetime import date, datetime, time, timedelta

import httpx
from pydantic import BaseModel

from src.config import TREINOS_API_URL

TIMEOUT_SECONDS = 10

class Serie(BaseModel):
    """Uma série. Preencha só as medidas que o tipo do exercício usa; as outras ficam vazias."""

    reps: int | None = None
    load_kg: float | None = None
    assistance_kg: float | None = None
    duration_sec: int | None = None
    distance_m: int | None = None
    warmup: bool = False
    failed: bool = False
    side: str | None = None

# Que medidas cada tipo de medição do exercício usa (nomes da ferramenta)
MEDIDAS = {
    "weight_reps": "reps e load_kg",
    "bodyweight": "reps; load_kg só com carga adicional, assistance_kg só com máquina ou elástico",
    "time": "duration_sec",
    "distance_time": "distance_m e duration_sec",
}

def is_enabled() -> bool:
    return bool(TREINOS_API_URL)

def _client() -> httpx.Client:
    return httpx.Client(base_url=TREINOS_API_URL, timeout=TIMEOUT_SECONDS)

def _day(day: str) -> date | None:
    """O dia pedido (AAAA-MM-DD), hoje se vazio; None se inválido."""
    if not day.strip():
        return date.today()
    try:
        return date.fromisoformat(day.strip())
    except ValueError:
        return None

def _problem(response: httpx.Response) -> str:
    """O motivo de um erro da API (Problem Details), para o Gemini repassar ao usuário."""
    try:
        body = response.json()
        return (body.get("detail") or body.get("title") or response.reason_phrase).rstrip(".")
    except ValueError:
        return response.reason_phrase

def _set_body(serie: dict) -> dict:
    side = (serie.get("side") or "").strip().lower()
    body = {
        "id": str(uuid.uuid7()),
        "type": "warmup" if serie.get("warmup") else "working",
        "isFailed": bool(serie.get("failed")),
        "reps": serie.get("reps"),
        "loadKg": serie.get("load_kg"),
        "assistanceKg": serie.get("assistance_kg"),
        "durationSec": serie.get("duration_sec"),
        "distanceM": serie.get("distance_m"),
        "side": {"esquerdo": "left", "direito": "right"}.get(side, side) or None,
    }
    return {key: value for key, value in body.items() if value is not None}

def _describe_set(serie: dict) -> str:
    parts = []
    if serie.get("reps") is not None:
        parts.append(f"{serie['reps']} rep")
    if serie.get("loadKg") is not None:
        parts.append(f"{serie['loadKg']:g} kg")
    if serie.get("assistanceKg") is not None:
        parts.append(f"-{serie['assistanceKg']:g} kg de assistência")
    if serie.get("distanceM") is not None:
        parts.append(f"{serie['distanceM']} m")
    if serie.get("durationSec") is not None:
        minutes, seconds = divmod(serie["durationSec"], 60)
        parts.append(f"{minutes}min{seconds:02d}s" if minutes else f"{seconds}s")
    if serie.get("side"):
        parts.append({"left": "esquerdo", "right": "direito"}[serie["side"]])
    if serie.get("type") == "warmup":
        parts.append("aquecimento")
    if serie.get("isFailed"):
        parts.append("falhou")
    return " ".join(parts)

def _workout_of_day(client: httpx.Client, day: date) -> dict | None:
    """O treino mais recente que começou no dia (no fuso do servidor), se houver."""
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    response = client.get("/api/workouts", params={"since": start.isoformat(), "until": end.isoformat()})
    response.raise_for_status()
    workouts = response.json()
    return workouts[0] if workouts else None

def _when(day: date) -> str:
    return "hoje" if day == date.today() else day.strftime("%d/%m")

def _catalog_names(client: httpx.Client) -> str:
    response = client.get("/api/exercises")
    response.raise_for_status()
    return ", ".join(sorted(e["name"] for e in response.json()))

def log_exercise(exercise: str, sets: list[dict], day: str = "") -> str:
    exercise = " ".join(exercise.split())
    if not exercise:
        return "Diga qual exercício foi feito."
    if not sets:
        return "O exercício precisa de pelo menos uma série."
    workout_day = _day(day)
    if workout_day is None:
        return f"Data inválida: '{day}'. Use AAAA-MM-DD."

    try:
        with _client() as client:
            response = client.get("/api/exercises/resolve", params={"term": exercise})
            if response.status_code == 404:
                return (
                    f"Não existe '{exercise}' no catálogo; nada foi registrado. Pergunte ao usuário qual destes "
                    f"é: {_catalog_names(client)}"
                )
            response.raise_for_status()
            found = response.json()

            entry = {
                "id": str(uuid.uuid7()),
                "exerciseId": found["id"],
                "sets": [_set_body(dict(serie)) for serie in sets],
            }
            workout = _workout_of_day(client, workout_day)
            if workout is None:
                # Treino de hoje começa agora; num dia passado, sem a hora certa, fica ao meio-dia
                started = datetime.now() if workout_day == date.today() else datetime.combine(workout_day, time(12))
                body = {"id": str(uuid.uuid7()), "startedAt": started.astimezone().isoformat(), "exercises": [entry]}
                response = client.post("/api/workouts", json=body)
            else:
                response = client.post(f"/api/workouts/{workout['id']}/exercises", json=entry)
            if response.status_code == 400:
                return (
                    f"A API recusou as séries de {found['name']}: {_problem(response)}. Nada foi registrado. "
                    f"Esse exercício usa {MEDIDAS[found['measurementType']]}; confira com o usuário."
                )
            response.raise_for_status()
    except httpx.HTTPError as error:
        return f"Não consegui falar com a API de treinos ({error.__class__.__name__}); nada foi registrado."

    when = _when(workout_day)
    described = "; ".join(_describe_set(serie) for serie in entry["sets"])
    return f"Registrado no treino de {when}: {found['name']} — {len(entry['sets'])} série(s): {described}"

def remove_exercise(exercise: str, day: str = "") -> str:
    """Tira do treino do dia a ocorrência mais recente do exercício, com as séries. Treino vazio é apagado."""
    exercise = " ".join(exercise.split())
    if not exercise:
        return "Diga qual exercício tirar."
    workout_day = _day(day)
    if workout_day is None:
        return f"Data inválida: '{day}'. Use AAAA-MM-DD."

    try:
        with _client() as client:
            response = client.get("/api/exercises/resolve", params={"term": exercise})
            if response.status_code == 404:
                return f"Não existe '{exercise}' no catálogo; nada foi tirado."
            response.raise_for_status()
            found = response.json()

            workout = _workout_of_day(client, workout_day)
            if workout is None:
                return f"Não há treino registrado em {_when(workout_day)}; nada foi tirado."
            matches = [e for e in workout["exercises"] if e["exerciseId"] == found["id"]]
            if not matches:
                names = ", ".join(e["exerciseName"] for e in workout["exercises"])
                return f"{found['name']} não está no treino de {_when(workout_day)}; nada foi tirado. O treino tem: {names}"
            target = matches[-1]
            response = client.delete(f"/api/workouts/{workout['id']}/exercises/{target['id']}")
            response.raise_for_status()
            remaining = response.json()["exercises"]
            if not remaining:
                client.delete(f"/api/workouts/{workout['id']}").raise_for_status()
    except httpx.HTTPError as error:
        return f"Não consegui falar com a API de treinos ({error.__class__.__name__}); nada foi tirado."

    described = "; ".join(_describe_set(serie) for serie in target["sets"])
    left = ", ".join(e["exerciseName"] for e in remaining) or "nada (o treino vazio foi apagado)"
    return f"Tirado do treino de {_when(workout_day)}: {found['name']} ({described}). Ficou: {left}"

def log_body_weight(weight_kg: float, day: str = "") -> str:
    weigh_day = _day(day)
    if weigh_day is None:
        return f"Data inválida: '{day}'. Use AAAA-MM-DD."
    try:
        with _client() as client:
            response = client.put(f"/api/body-weights/{weigh_day.isoformat()}", json={"weightKg": weight_kg})
            if response.status_code == 400:
                return f"A API recusou o peso: {_problem(response)}. Nada foi registrado."
            response.raise_for_status()
    except httpx.HTTPError as error:
        return f"Não consegui falar com a API de treinos ({error.__class__.__name__}); nada foi registrado."
    when = _when(weigh_day)
    replaced = " (substituiu o registro do dia)" if response.status_code == 200 else ""
    return f"Peso registrado para {when}: {weight_kg:g} kg{replaced}"
