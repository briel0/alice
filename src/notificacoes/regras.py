"""Regras do filtro, num arquivo Markdown em data/ (formato em examples/notificacoes-regras.example.md).

Seções "Avisar na hora", "Resumo diário" e "Silêncio": uma regra por linha, de dois tipos, lidas só por código:
- "- endereço@exemplo.com": tudo desse remetente exato;
- "- endereço@exemplo.com | trecho do assunto": desse remetente, quando o assunto contém o trecho
  (sem diferenciar maiúsculas nem espaços repetidos).
Seção "Critérios": texto livre que vai para o classificador; as correções do usuário entram no fim dela.

Ordem: remetente + assunto vence só remetente; entre regras igualmente específicas, vence o nível mais alto
(um alarme falso custa menos que um urgente perdido). O arquivo só muda por proposta confirmada pelo usuário
(botões de correção no Telegram), nunca sozinho.
"""
import re

from src.config import BASE_DIR, NOTIF_RULES_FILE
from src.storage import commit_data_file

SECOES = {"avisar na hora": "agora", "resumo diário": "resumo", "resumo diario": "resumo",
          "silêncio": "silencio", "silencio": "silencio"}
TITULO = {"agora": "Avisar na hora", "resumo": "Resumo diário", "silencio": "Silêncio"}
ORDEM = {"agora": 0, "resumo": 1, "silencio": 2}
CORRECOES = "Correções do usuário (valem mais que os critérios acima):"

# Sem o arquivo em data/, começa pelo exemplo genérico (critérios iniciais do item 14)
MODELO = BASE_DIR / "examples" / "notificacoes-regras.example.md"

ENDERECO_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
TRECHO_MIN, TRECHO_MAX = 3, 80
CRITERIO_MIN, CRITERIO_MAX = 10, 150

Chave = tuple[str, str]  # (endereço, trecho do assunto normalizado; "" = só remetente)


def normalizar(texto: str) -> str:
    return " ".join((texto or "").split()).casefold()


def trecho_valido(trecho: str) -> bool:
    t = " ".join(trecho.split())
    return TRECHO_MIN <= len(t) <= TRECHO_MAX and "|" not in t


def _texto() -> str:
    arquivo = NOTIF_RULES_FILE if NOTIF_RULES_FILE.exists() else MODELO
    return arquivo.read_text(encoding="utf-8")


def _secao(linha: str) -> str | None:
    """Nível da seção (ou "criterios") para uma linha de título "## ..."; None para título desconhecido."""
    nome = linha[3:].strip().lower()
    return SECOES.get(nome, "criterios" if nome.startswith("crit") else None)


def _chave(linha: str) -> Chave | None:
    """A regra de uma linha "- endereço [| trecho]", ou None se a linha não for uma regra válida."""
    linha = linha.strip()
    if not linha.startswith("- "):
        return None
    esquerda, _, direita = linha[2:].partition("|")
    palavras = esquerda.split()
    if not palavras or not ENDERECO_RE.match(palavras[0].lower()):
        return None
    if direita.strip() and not trecho_valido(direita):
        return None
    return palavras[0].lower(), normalizar(direita)


def ler() -> tuple[dict[Chave, str], str]:
    """Devolve ({(endereço, trecho): nível}, critérios em texto)."""
    regras: dict[Chave, str] = {}
    criterios: list[str] = []
    secao = None
    for linha in _texto().splitlines():
        if linha.startswith("## "):
            secao = _secao(linha)
            continue
        if secao == "criterios":
            criterios.append(linha)
        elif secao and (chave := _chave(linha)):
            atual = regras.get(chave)
            if atual is None or ORDEM[secao] < ORDEM[atual]:
                regras[chave] = secao
    return regras, "\n".join(criterios).strip()


def nivel_por_regra(endereco: str, assunto: str, regras: dict[Chave, str]) -> tuple[str, str] | None:
    """(nível, regra que casou) para o e-mail, ou None se nenhuma regra fala dele."""
    endereco, assunto = endereco.lower(), normalizar(assunto)
    casaram = [(t, n) for (e, t), n in regras.items() if e == endereco and t and t in assunto]
    if casaram:
        trecho, nivel = min(casaram, key=lambda tn: (ORDEM[tn[1]], -len(tn[0])))
        return nivel, f"{endereco} | {trecho}"
    if (endereco, "") in regras:
        return regras[(endereco, "")], endereco
    return None


def _gravar(linhas: list[str], mensagem: str) -> None:
    NOTIF_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTIF_RULES_FILE.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")
    commit_data_file(NOTIF_RULES_FILE, mensagem)


def adicionar(endereco: str, trecho: str, nivel: str) -> str:
    """Grava a regra na seção do nível (tirando a mesma regra das outras). Só chamado depois do "sim" do usuário.
    trecho vazio = regra só por remetente."""
    endereco, trecho = endereco.strip().lower(), " ".join((trecho or "").split())
    if not ENDERECO_RE.match(endereco) or nivel not in TITULO or (trecho and not trecho_valido(trecho)):
        return "Regra inválida."
    alvo = (endereco, normalizar(trecho))
    linhas, secao = [], None
    for linha in _texto().splitlines():
        if linha.startswith("## "):
            secao = _secao(linha)
        elif secao in ORDEM and _chave(linha) == alvo:
            continue
        linhas.append(linha)
    titulo = f"## {TITULO[nivel]}"
    if titulo not in linhas:
        linhas += ["", titulo]
    pos = linhas.index(titulo) + 1
    while pos < len(linhas) and linhas[pos].strip().startswith("- "):
        pos += 1
    regra = endereco + (f" | {trecho}" if trecho else "")
    linhas.insert(pos, f"- {regra}")
    _gravar(linhas, f"feat(notificacoes): regra {regra} -> {nivel}")
    return f"Regra gravada: {regra} → {TITULO[nivel]}."


def adicionar_criterio(frase: str, nivel: str) -> str:
    """Acrescenta uma correção no fim de "Critérios". Só chamado depois do "sim" do usuário."""
    frase = " ".join((frase or "").split())
    if not CRITERIO_MIN <= len(frase) <= CRITERIO_MAX or nivel not in TITULO:
        return "Critério inválido."
    linhas = _texto().splitlines()
    inicio = next((i for i, l in enumerate(linhas) if l.startswith("## ") and _secao(l) == "criterios"), None)
    if inicio is None:
        linhas += ["", "## Critérios"]
        inicio = len(linhas) - 1
    fim = next((i for i in range(inicio + 1, len(linhas)) if linhas[i].startswith("## ")), len(linhas))
    if CORRECOES in linhas[inicio:fim]:
        pos = linhas.index(CORRECOES, inicio) + 1
        while pos < fim and linhas[pos].strip().startswith("- "):
            pos += 1
    else:
        while fim > inicio + 1 and not linhas[fim - 1].strip():
            fim -= 1
        linhas[fim:fim] = ["", CORRECOES]
        pos = fim + 2
    linhas.insert(pos, f"- {frase} → {TITULO[nivel]}")
    _gravar(linhas, f"feat(notificacoes): critério -> {nivel}")
    return f"Critério gravado: {frase} → {TITULO[nivel]}."
