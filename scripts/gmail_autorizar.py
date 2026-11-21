"""Autoriza a ALICE a LER o Gmail (escopo gmail.readonly). Roda uma vez, no PC, com navegador.

Uso:
    uv run python scripts/gmail_autorizar.py caminho/do/client_secret.json [saida.json]

O client_secret.json é o cliente OAuth do tipo "App para computador" baixado do Google Cloud (passo a passo
em deploy/README.md). O script abre o navegador, você aceita só a leitura do Gmail, e ele grava
client_id, client_secret e refresh_token em saida.json (padrão: .cache/gmail-token.json, fora do Git).
Depois copie esse arquivo para a VPS (NOTIF_GMAIL_TOKEN_PATH) e apague a cópia do PC.

Só biblioteca padrão. Não imprime o token.
"""
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ESCOPO = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cliente = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cliente = cliente.get("installed") or cliente.get("web") or cliente
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".cache/gmail-token.json")

    estado = secrets.token_urlsafe(16)
    verificador = secrets.token_urlsafe(48)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    recebido: dict = {}

    class Retorno(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recebido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Pronto, pode fechar esta aba e voltar ao terminal.".encode())

        def log_message(self, *args):
            pass

    servidor = http.server.HTTPServer(("127.0.0.1", 0), Retorno)
    redirect = f"http://127.0.0.1:{servidor.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cliente["client_id"],
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": ESCOPO,
        "access_type": "offline",
        "prompt": "consent",
        "state": estado,
        "code_challenge": desafio,
        "code_challenge_method": "S256",
    })
    print("Abrindo o navegador. Se não abrir, cole este endereço:\n" + url)
    webbrowser.open(url)
    while "code" not in recebido and "error" not in recebido:
        servidor.handle_request()

    if recebido.get("state") != estado:
        sys.exit("Resposta com state diferente: abortado.")
    if "error" in recebido:
        sys.exit(f"Autorização negada: {recebido['error']}")

    dados = urllib.parse.urlencode({
        "code": recebido["code"],
        "client_id": cliente["client_id"],
        "client_secret": cliente["client_secret"],
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
        "code_verifier": verificador,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=dados)) as r:
        token = json.load(r)
    if ESCOPO not in token.get("scope", "").split():
        sys.exit("O Google não concedeu o escopo gmail.readonly: abortado.")
    if set(token.get("scope", "").split()) - {ESCOPO}:
        sys.exit(f"Escopos a mais concedidos ({token['scope']}): abortado, a ALICE só deve ler o Gmail.")
    if "refresh_token" not in token:
        sys.exit("O Google não devolveu refresh_token. Revogue o acesso em myaccount.google.com/permissions e rode de novo.")

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps({
        "client_id": cliente["client_id"],
        "client_secret": cliente["client_secret"],
        "refresh_token": token["refresh_token"],
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Token gravado em {saida}. Copie para a VPS e apague daqui.")


if __name__ == "__main__":
    main()
