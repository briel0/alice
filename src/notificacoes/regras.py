"""Regras do filtro, num arquivo Markdown em data/ (formato em examples/notificacoes-regras.example.md).

Seções "Avisar na hora", "Resumo diário" e "Silêncio": uma regra por linha, "- endereço@exemplo.com" (remetente
exato) ou "- @exemplo.com" (o domínio e os subdomínios dele). Lidas só por código, sem Gemini.
Seção "Critérios": texto livre que vai para o classificador.

Ordem: o endereço exato vence o domínio; entre regras igualmente específicas, vence o nível mais alto
(um alarme falso custa menos que um urgente perdido). O arquivo só muda por proposta confirmada pelo usuário
(botões 👍/👎), nunca sozinho.
"""
import re

from src.config import BASE_DIR, NOTIF_RULES_FILE
from src.storage import commit_data_file

SECOES = {"avisar na hora": "agora", "resumo diário": "resumo", "resumo diario": "resumo",
          "silêncio": "silencio", "silencio": "silencio"}
TITULO = {"agora": "Avisar na hora", "resumo": "Resumo diário", "silencio": "Silêncio"}
ORDEM = {"agora": 0, "resumo": 1, "silencio": 2}

# Sem o arquivo em data/, começa pelo exemplo genérico (critérios iniciais do item 14)
MODELO = BASE_DIR / "examples" / "notificacoes-regras.example.md"

ENDERECO_RE = re.compile(r"^@?[a-z0-9._%+-]*@?[a-z0-9.-]+\.[a-z]{2,}$")


def _texto() -> str:
    arquivo = NOTIF_RULES_FILE if NOTIF_RULES_FILE.exists() else MODELO
    return arquivo.read_text(encoding="utf-8")


def ler() -> tuple[dict[str, str], str]:
    """Devolve ({regra: nível}, critérios em texto)."""
    regras: dict[str, str] = {}
    criterios: list[str] = []
    secao = None
    for linha in _texto().splitlines():
        if linha.startswith("## "):
            nome = linha[3:].strip().lower()
            secao = SECOES.get(nome, "criterios" if nome.startswith("crit") else None)
            continue
        if secao == "criterios":
            criterios.append(linha)
        elif secao and linha.strip().startswith("- "):
            regra = linha.strip()[2:].split()[0].lower() if linha.strip()[2:].strip() else ""
            if ENDERECO_RE.match(regra):
                atual = regras.get(regra)
                if atual is None or ORDEM[secao] < ORDEM[atual]:
                    regras[regra] = secao
    return regras, "\n".join(criterios).strip()


def nivel_por_regra(endereco: str, regras: dict[str, str]) -> tuple[str, str] | None:
    """(nível, regra que casou) para o remetente, ou None se nenhuma regra fala dele."""
    endereco = endereco.lower()
    if endereco in regras:
        return regras[endereco], endereco
    dominio = endereco.rsplit("@", 1)[-1]
    casaram = [r for r in regras if r.startswith("@") and (dominio == r[1:] or dominio.endswith("." + r[1:]))]
    if not casaram:
        return None
    melhor = min(casaram, key=lambda r: (ORDEM[regras[r]], -len(r)))
    return regras[melhor], melhor


def adicionar(regra: str, nivel: str) -> str:
    """Grava a regra na seção do nível (tirando-a das outras). Só chamado depois do "sim" do usuário."""
    regra = regra.strip().lower()
    if not ENDERECO_RE.match(regra) or nivel not in TITULO:
        return "Regra inválida."
    linhas = [l for l in _texto().splitlines() if l.strip().split()[1:2] != [regra] or not l.strip().startswith("- ")]
    titulo = f"## {TITULO[nivel]}"
    if titulo not in linhas:
        linhas += ["", titulo]
    pos = linhas.index(titulo) + 1
    while pos < len(linhas) and linhas[pos].strip().startswith("- "):
        pos += 1
    linhas.insert(pos, f"- {regra}")
    NOTIF_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTIF_RULES_FILE.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")
    commit_data_file(NOTIF_RULES_FILE, f"feat(notificacoes): {regra} -> {nivel}")
    return f"Regra gravada: {regra} → {TITULO[nivel]}."
