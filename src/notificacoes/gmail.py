"""Leitura do Gmail só com o escopo gmail.readonly, pelo httpx (sem a biblioteca do Google).

O token (client_id, client_secret, refresh_token) é gerado uma vez no PC por scripts/gmail_autorizar.py e fica
na VPS fora do repositório (NOTIF_GMAIL_TOKEN_PATH). As mensagens são pedidas no formato "metadata": só
cabeçalhos e o snippet do Gmail; o corpo nunca é baixado.
"""
import html
import json
import re
import time
from email.utils import parseaddr
from datetime import datetime

import httpx

from src.config import NOTIF_GMAIL_TOKEN_PATH
from src.notificacoes.db import TZ

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TIMEOUT = 20

# Categorias da caixa de entrada; sem rótulo de categoria, conta como Principal
CATEGORIAS = {
    "CATEGORY_PERSONAL": "principal",
    "CATEGORY_UPDATES": "atualizacoes",
    "CATEGORY_PROMOTIONS": "promocoes",
    "CATEGORY_SOCIAL": "social",
    "CATEGORY_FORUMS": "foruns",
}
FORA = {"SPAM", "TRASH", "SENT", "DRAFT", "CHAT"}

# Códigos de verificação: com uma dessas palavras no texto, sequências de 4 a 8 dígitos viram ••••
CODIGO_CONTEXTO = re.compile(r"c[óo]digo|code|verifica|otp|token|senha|password|pin\b", re.IGNORECASE)
CODIGO = re.compile(r"\b(?:[A-Z]-)?\d{4,8}\b|\b\d{3}[ -]\d{3}\b")


class TokenRevogado(Exception):
    """O Google recusou o refresh token (senha trocada, acesso revogado): parar de tentar e avisar."""


class HistoricoExpirado(Exception):
    """O historyId guardado é velho demais (bot fora do ar por muito tempo): é preciso reler."""


def mascarar_codigos(texto: str) -> str:
    if not CODIGO_CONTEXTO.search(texto):
        return texto
    return CODIGO.sub("••••", texto)


class Gmail:
    def __init__(self, token_path=None):
        self.token_path = token_path or NOTIF_GMAIL_TOKEN_PATH
        self._access = None
        self._expira = 0.0
        self._http = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "alice-notificacoes"})

    def _token(self) -> str:
        if self._access and time.time() < self._expira - 60:
            return self._access
        cred = json.loads(self.token_path.read_text(encoding="utf-8"))
        r = self._http.post(TOKEN_URL, data={
            "client_id": cred["client_id"],
            "client_secret": cred["client_secret"],
            "refresh_token": cred["refresh_token"],
            "grant_type": "refresh_token",
        })
        if r.status_code in (400, 401) and "invalid_grant" in r.text:
            raise TokenRevogado()
        r.raise_for_status()
        dados = r.json()
        self._access = dados["access_token"]
        self._expira = time.time() + int(dados.get("expires_in", 3600))
        return self._access

    def _get(self, caminho: str, params=None) -> dict:
        r = self._http.get(f"{API}{caminho}", params=params, headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code == 401:
            self._access = None
            r = self._http.get(f"{API}{caminho}", params=params, headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code == 404 and caminho == "/history":
            raise HistoricoExpirado()
        r.raise_for_status()
        return r.json()

    def history_id_atual(self) -> str:
        return str(self._get("/profile")["historyId"])

    def novos_desde(self, history_id: str) -> tuple[list[str], str]:
        """IDs das mensagens que entraram na caixa de entrada desde history_id, e o historyId novo."""
        ids: list[str] = []
        params = {"startHistoryId": history_id, "historyTypes": "messageAdded", "labelId": "INBOX"}
        novo = history_id
        while True:
            dados = self._get("/history", params)
            novo = str(dados.get("historyId", novo))
            for h in dados.get("history", []):
                for add in h.get("messagesAdded", []):
                    msg = add.get("message", {})
                    if msg.get("id") and not FORA & set(msg.get("labelIds", [])) and msg["id"] not in ids:
                        ids.append(msg["id"])
            if not dados.get("nextPageToken"):
                return ids, novo
            params["pageToken"] = dados["nextPageToken"]

    def recentes(self, dias: int = 2) -> list[str]:
        """IDs da caixa de entrada dos últimos dias (para reler quando o historyId expira)."""
        ids: list[str] = []
        params = {"q": f"in:inbox newer_than:{dias}d", "maxResults": 100}
        while True:
            dados = self._get("/messages", params)
            ids += [m["id"] for m in dados.get("messages", [])]
            if not dados.get("nextPageToken") or len(ids) >= 300:
                return ids
            params["pageToken"] = dados["nextPageToken"]

    def mensagem(self, msg_id: str) -> dict | None:
        """Cabeçalhos e snippet de uma mensagem, já no formato de item do filtro. None se ela não serve."""
        try:
            dados = self._get(f"/messages/{msg_id}", [("format", "metadata"), ("metadataHeaders", "From"),
                                                      ("metadataHeaders", "Subject")])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:  # apagada entre a listagem e a leitura
                return None
            raise
        rotulos = set(dados.get("labelIds", []))
        if FORA & rotulos or "INBOX" not in rotulos:
            return None
        cab = {h["name"].lower(): h["value"] for h in dados.get("payload", {}).get("headers", [])}
        nome, endereco = parseaddr(cab.get("from", ""))
        categoria = next((CATEGORIAS[r] for r in CATEGORIAS if r in rotulos and r != "CATEGORY_PERSONAL"), "principal")
        recebido = datetime.fromtimestamp(int(dados.get("internalDate", "0")) / 1000, TZ)
        return {
            "fonte": "gmail",
            "ext_id": msg_id,
            "remetente": (nome or endereco or "?")[:80],
            "endereco": endereco.lower()[:120],
            "assunto": mascarar_codigos(cab.get("subject", "(sem assunto)"))[:200],
            "categoria": categoria,
            "trecho": mascarar_codigos(html.unescape(dados.get("snippet", "")))[:300],
            "link": f"https://mail.google.com/mail/u/0/#all/{msg_id}",
            "recebido_em": recebido.isoformat(timespec="seconds"),
        }
