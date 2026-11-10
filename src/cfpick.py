"""Seletor de problemas (Codeforces + gyms de ICPC) para treino.

Regras:
  1. Dificuldade por escada adaptativa, uma por fonte (CF e gym): acertou no timebox, sobe; errou, desce.
     Converge para TARGET de acerto.
  2. Problema e fonte sorteados, sem olhar tags (prática intercalada). Revisões vencidas têm prioridade.
  3. Problema em que falhou volta depois de REVIEW_DAYS para reimplementar sem olhar (recuperação espaçada).

Funções usadas pela ALICE (devolvem dict; erros levantam CFPickError): pick, record, skip, status.
O catálogo de gyms é montado à mão, rodando gym-discover de vez em quando (é demorado; nunca pela conversa).

Gyms das provas brasileiras oficiais (Primeira Fase, Latin American Regional, Latin America Championship)
ficam reservados para virtual em time e nunca são sorteados individualmente.

CLI: python -m src.cfpick pick [cf|gym] | ok | fail | skip | status | gym-discover [n] [--dry] | gym-add <id...>

state.json e gyms.json ficam em data/cfpick/ (repositório privado); problemset.json é cache em .cache/cfpick/.
"""

import hashlib
import http.client
import json
import math
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from src.config import BASE_DIR, CF_API_KEY, CF_API_SECRET, CF_HANDLE, DATA_DIR

STATE_DIR = DATA_DIR / "cfpick"
CACHE_DIR = BASE_DIR / ".cache" / "cfpick"

TARGET          = 0.5    # taxa de acerto alvo dentro do timebox
STEP            = 100    # passo da escada, em pontos de rating
TIMEBOX_MIN     = 60     # AC depois disso conta como falha para a escada
P_GYM           = 0.5    # chance de sortear gym (se houver catálogo)
REVIEW_DAYS     = 7
REVIEW_MAX      = 3      # tentativas de revisão antes de desistir do problema
CF_START_OFFSET = 100    # escada CF começa em rating + isso
CF_MIN_CONTEST  = 1000   # heurística: ignora problemas muito antigos
GYM_MIN_PARTIES = 10     # mínimo de participantes para confiar na estimativa
GYM_KINDS       = {"Official ICPC Contest"}   # campo "kind" do contest.list
GYM_MIN_SEASON  = 2010   # temporada mínima (gyms sem ano nenhum entram no fim da fila)
GYM_MIN_HOURS   = 4      # regionais/finais têm 5h; rodadas online e warmups, menos
# Competições brasileiras: entram com qualquer "kind" e mesmo sendo treino.
GYM_BR          = re.compile(r"brazil|brasil|\bsbc\b|\bmaratona\b|maratonusp|usp-icmc"
                             r"|\b(usp|unicamp|ufba|udesc|ufmg|ufpe|ufrj|ufrn|ufcg|unb|ufsc"
                             r"|ufrgs|utfpr|ufc|ufpr|ufam|ufes|ufg|ita)\b", re.I)
# "kind" é preenchido por quem sobe o gym e às vezes falta ou está errado:
# gyms com nome de prova oficial também entram.
GYM_RESCUE      = re.compile(r"\b(sub-?)?regional\b|latin america|first phase"
                             r"|(icpc|acm).*world finals"
                             r"|\b(n|ne|nw|sw|se|c)e?erc\b|\bnerc\b|\becna\b|\bncna\b", re.I)
# Sempre fora: provas para iniciantes, aulas/listas e nomes que entregam o tópico
# (o nome do gym aparece na página do problema, então seria spoiler).
GYM_BLOCK       = re.compile(r"freshm|bixes|starters|\blista\b|homework|tarefa|\baula\b"
                             r"|\b(dsu|union[- ]find|combinatoric\w*|geometr\w*|dp|dynamic programming"
                             r"|graphs?|strings?|flows?|segment trees?|number theory|greedy"
                             r"|bitmasks?|probabilit\w*|game theory|data structures?)\b", re.I)
# Fora, exceto se for brasileiro: treinos, aquecimentos, divisões mais fáceis.
GYM_TRAINING    = re.compile(r"training|treino|practice|warm-?up|aquecimento"
                             r"|div\.? ?2|(?<!uni)camp\b", re.I)
# Reservados para virtual em time (não são sorteados individualmente). None desliga.
GYM_RESERVE     = re.compile(r"brazil subregional|brazil first phase"
                             r"|latin american? regional|latin america championship", re.I)
VERIFY_AC       = True   # confere o AC na API antes de aceitar "ok"
CACHE_TTL_DAYS  = 7      # o problemset só cresce; não precisa baixar todo dia

API = "https://codeforces.com/api/"
DAY = 86400
SOURCES = ("cf", "gym")


class CFPickError(Exception):
    pass


class CFNetworkError(CFPickError):
    """Falha de rede/limite da API: tente de novo mais tarde."""


def is_enabled() -> bool:
    return bool(CF_HANDLE)


# ---------------------------------------------------------------- API do CF
_last_call = [0.0]


def _api(method, auth=False, **params):
    wait = 2.1 - (time.time() - _last_call[0])      # limite: ~1 chamada / 2 s
    if wait > 0:
        time.sleep(wait)
    params = {k: str(v) for k, v in params.items()}
    if auth:
        if not (CF_API_KEY and CF_API_SECRET):
            raise CFPickError("defina CF_API_KEY e CF_API_SECRET para baixar placares de gym")
        params["apiKey"] = CF_API_KEY
        params["time"] = str(int(time.time()))
        rnd = f"{random.randrange(10**6):06d}"
        q = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hashlib.sha512(f"{rnd}/{method}?{q}#{CF_API_SECRET}".encode()).hexdigest()
        params["apiSig"] = rnd + sig
    url = API + method + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        _last_call[0] = time.time()
        data = None
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:      # o CF devolve 400 com JSON
            try:
                data = json.load(e)
            except Exception:
                pass
        except (OSError, http.client.HTTPException, ValueError):   # rede, conexão cortada, JSON quebrado
            pass
        if isinstance(data, dict) and "limit exceeded" not in str(data.get("comment", "")).lower():
            break
        if attempt == 2:
            raise CFNetworkError(f"falha ao acessar a API do Codeforces ({method})")
        time.sleep(5)
    if data.get("status") != "OK":
        raise CFPickError(data.get("comment", "erro na API do Codeforces"))
    return data["result"]


# ---------------------------------------------------------------- arquivos
def _read(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _write(path, obj, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    tmp.replace(path)


def _load():
    return _read(STATE_DIR / "state.json",
                 {"ladder": {"cf": None, "gym": 0.0}, "current": None, "seen": [],
                  "reviews": [], "history": []})


def _save(s):
    _write(STATE_DIR / "state.json", s, indent=1)


def _load_gyms():
    return _read(STATE_DIR / "gyms.json", {})


def _save_gyms(cat):
    _write(STATE_DIR / "gyms.json", cat)


def _url(pid):
    cid, idx = pid.split("/")
    if int(cid) >= 100000:
        return f"https://codeforces.com/gym/{cid}/problem/{idx}"
    return f"https://codeforces.com/problemset/problem/{cid}/{idx}"


def _need_handle():
    if not CF_HANDLE:
        raise CFPickError("defina CF_HANDLE")


# ---------------------------------------------------------------- pools
def _cf_problems():
    """Problemset enxuto em cache (id, rating) para não gastar RAM a cada pick."""
    p = CACHE_DIR / "problemset.json"
    if p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL_DAYS * DAY:
        return _read(p, [])
    raw = _api("problemset.problems")["problems"]
    slim = [[f"{x['contestId']}/{x['index']}", x["rating"]] for x in raw
            if x.get("rating") and x.get("contestId", 0) >= CF_MIN_CONTEST
            and "*special" not in x.get("tags", [])]
    del raw
    _write(p, slim)
    return slim


def _touched():
    """Todo problema em que você já submeteu algo (CF e gym)."""
    return {f"{x['problem']['contestId']}/{x['problem']['index']}"
            for x in _api("user.status", handle=CF_HANDLE)
            if x["problem"].get("contestId")}


def _first_ac_since(pid, since):
    """Horário do primeiro AC desse problema desde que foi sorteado (ou None)."""
    acs = [x["creationTimeSeconds"] for x in _api("user.status", handle=CF_HANDLE, count=200)
           if f"{x['problem'].get('contestId')}/{x['problem']['index']}" == pid
           and x.get("verdict") == "OK" and x["creationTimeSeconds"] >= since - 60]
    return min(acs) if acs else None


def _closest(pool, level):
    """Sorteia entre os problemas mais próximos do nível da escada."""
    best = min(abs(d - level) for _, d in pool)
    lim = max(best, STEP / 2)
    return random.choice([(pid, d) for pid, d in pool if abs(d - level) <= lim])


def _reserved(name):
    return bool(GYM_RESERVE and GYM_RESERVE.search(name))


# ---------------------------------------------------------------- API pública
def pick(source=None):
    """Próximo problema. Devolve só o link (nunca tag/rating), para não dar pista."""
    _need_handle()
    source = (source or "").strip().lower() or None
    if source not in (None, *SOURCES):
        raise CFPickError(f"fonte inválida: '{source}' (use cf, gym ou nada)")
    s = _load()
    now = time.time()
    if s["current"]:
        c = s["current"]
        return {"url": _url(c["id"]), "review": c["review"] > 0, "pending": True,
                "elapsed_min": round((now - c["t"]) / 60)}

    due = sorted((r for r in s["reviews"] if r["due"] <= now), key=lambda r: r["due"])
    if due:
        r = due[0]
        s["reviews"].remove(r)
        s["current"] = {"id": r["id"], "src": r["src"], "d": r["d"],
                        "review": r["n"], "t": now}
        _save(s)
        return {"url": _url(r["id"]), "review": True, "pending": False}

    touched = _touched() | set(s["seen"]) | {r["id"] for r in s["reviews"]}
    gym_pool = [(f"{cid}/{p['index']}", p["d"])
                for cid, g in _load_gyms().items() if not _reserved(g.get("name", ""))
                for p in g["problems"]
                if p["n"] >= GYM_MIN_PARTIES and f"{cid}/{p['index']}" not in touched]

    src = source or ("gym" if gym_pool and random.random() < P_GYM else "cf")
    if src == "gym":
        if not gym_pool:
            raise CFPickError("catálogo de gym vazio ou esgotado (rode gym-discover)")
        pool = gym_pool
    else:
        if s["ladder"]["cf"] is None:
            rating = _api("user.info", handles=CF_HANDLE)[0].get("rating", 1200)
            s["ladder"]["cf"] = float(rating + CF_START_OFFSET)
        pool = [(pid, d) for pid, d in _cf_problems() if pid not in touched]
        if not pool:
            raise CFPickError("nenhum problema novo disponível")

    level = s["ladder"][src]
    pid, d = _closest(pool, level)
    s["current"] = {"id": pid, "src": src, "d": d, "review": 0, "t": now}
    s["seen"].append(pid)
    _save(s)
    return {"url": _url(pid), "review": False, "pending": False}


def record(solved):
    """Fecha o problema atual. solved=True só se AC sem ver editorial."""
    _need_handle()
    s = _load()
    c = s["current"]
    if not c:
        raise CFPickError("nenhum problema em aberto")
    now = time.time()
    end = now
    if solved and VERIFY_AC:
        ac = _first_ac_since(c["id"], c["t"])
        if ac is None:
            raise CFPickError("não encontrei AC desse problema desde que ele foi sorteado")
        end = ac
    minutes = (end - c["t"]) / 60
    success = bool(solved) and minutes <= TIMEBOX_MIN

    if c["review"]:
        if not success and c["review"] < REVIEW_MAX:
            s["reviews"].append({"id": c["id"], "src": c["src"], "d": c["d"],
                                 "n": c["review"] + 1, "due": now + REVIEW_DAYS * DAY})
    else:
        lad = s["ladder"]
        lad[c["src"]] += STEP * 2 * (1 - TARGET) if success else -STEP * 2 * TARGET
        lo, hi = (800, 3500) if c["src"] == "cf" else (-1000, 1000)
        lad[c["src"]] = max(lo, min(hi, lad[c["src"]]))
        if not success:
            s["reviews"].append({"id": c["id"], "src": c["src"], "d": c["d"],
                                 "n": 1, "due": now + REVIEW_DAYS * DAY})

    s["history"].append({"id": c["id"], "src": c["src"], "d": c["d"], "review": c["review"],
                         "solved": bool(solved), "success": success,
                         "minutes": round(minutes), "t": int(c["t"])})
    s["current"] = None
    _save(s)
    return {"success": success, "late": bool(solved) and not success,
            "minutes": round(minutes), "review": c["review"] > 0,
            "ladder": {k: round(v) if v is not None else None for k, v in s["ladder"].items()}}


def skip():
    """Descarta o atual (sem tempo, enunciado quebrado...). Não mexe na escada."""
    s = _load()
    c = s["current"]
    if not c:
        raise CFPickError("nenhum problema em aberto")
    if c["review"]:                          # revisão pulada volta amanhã
        s["reviews"].append({"id": c["id"], "src": c["src"], "d": c["d"],
                             "n": c["review"], "due": time.time() + DAY})
    s["current"] = None
    _save(s)
    return {"skipped": _url(c["id"])}


def status():
    s = _load()
    now = time.time()
    new = [h for h in s["history"] if not h["review"]]

    def rate(src):
        h = [x for x in new if x["src"] == src][-20:]
        return {"success": sum(x["success"] for x in h), "of": len(h)}

    return {"ladder": {k: round(v) if v is not None else None for k, v in s["ladder"].items()},
            "recent": {"cf": rate("cf"), "gym": rate("gym")},
            "target": TARGET,
            "attempts_7d": sum(x["t"] >= now - 7 * DAY for x in s["history"]),
            "reviews_due": sum(r["due"] <= now for r in s["reviews"]),
            "reviews_pending": len(s["reviews"]),
            "gym_problems": sum(p["n"] >= GYM_MIN_PARTIES for g in _load_gyms().values()
                                if not _reserved(g.get("name", "")) for p in g["problems"]),
            "current": _url(s["current"]["id"]) if s["current"] else None}


def as_tool_result(fn, *args) -> str:
    """Roda uma função pública e devolve JSON (ou o erro em texto) para o Gemini."""
    try:
        return json.dumps(fn(*args), ensure_ascii=False)
    except CFNetworkError as e:
        return f"Erro de rede: {e}. Nada foi alterado; tente de novo mais tarde."
    except CFPickError as e:
        return f"Erro: {e}. Nada foi alterado."


# ---------------------------------------------------------------- gym (só pela CLI)
def gym_add(cid):
    """Baixa o placar do gym e estima a dificuldade de cada problema."""
    cid = int(cid)
    res = _api("contest.standings", auth=True, contestId=cid, showUnofficial="true")
    probs = res["problems"]
    solved, parties = [0] * len(probs), 0
    for row in res["rows"]:
        if row["party"]["participantType"] not in ("CONTESTANT", "VIRTUAL"):
            continue                          # PRACTICE costuma ter lido o editorial
        got = [r.get("points", 0) > 0 for r in row["problemResults"]]
        if not any(got):
            continue                          # abriu e não fez nada
        parties += 1
        for i, g in enumerate(got):
            solved[i] += g
    out = []
    for p, k in zip(probs, solved):
        f = (k + 0.5) / (parties + 1)         # suavização: nunca 0 nem 1
        out.append({"index": p["index"], "solved": k, "n": parties,
                    "d": round(400 * math.log10((1 - f) / f), 1)})
    cat = _load_gyms()
    cat[str(cid)] = {"name": res["contest"]["name"], "fetched": int(time.time()),
                     "problems": out}
    _save_gyms(cat)
    return {"gym": cid, "name": res["contest"]["name"], "participants": parties,
            "problems": len(out), "usable": parties >= GYM_MIN_PARTIES}


def _season_year(c):
    season = c.get("season") or ""
    if season[:4].isdigit():
        return int(season[:4])
    m = re.search(r"\b(20\d\d)\b", c.get("name", ""))
    if m:
        return int(m.group(1))
    if c.get("startTimeSeconds"):
        return time.gmtime(c["startTimeSeconds"]).tm_year
    return None


def gym_discover(limit=None, dry_run=False):
    """Acha gyms de ICPC que ainda não estão no catálogo e baixa os placares (mais recentes antes).
    Gyms já baixados nunca são baixados de novo; os que falham ficam marcados para não serem tentados
    de novo. Se a rede cair, rode de novo: continua de onde parou.
    dry_run=True: só devolve os nomes que entrariam, na ordem, sem baixar nada."""
    cat = _load_gyms()
    cands, reserved = [], 0
    for c in _api("contest.list", gym="true"):
        name = c.get("name", "")
        br = bool(GYM_BR.search(name))
        if c.get("type") != "ICPC" or c.get("phase") != "FINISHED":
            continue
        if c.get("kind") not in GYM_KINDS and not br and not GYM_RESCUE.search(name):
            continue
        if c.get("durationSeconds", 0) < GYM_MIN_HOURS * 3600:
            continue
        if GYM_BLOCK.search(name) or (not br and GYM_TRAINING.search(name)):
            continue
        if _reserved(name):
            reserved += 1
            continue
        year = _season_year(c)            # sem ano nenhum: mantém, vai pro fim da fila
        if year is not None and year < GYM_MIN_SEASON:
            continue
        cands.append((-(year or 0), -c["id"], c["id"], name))
    cands.sort()
    new = [(cid, name) for _, _, cid, name in cands if str(cid) not in cat]
    if dry_run:
        return {"total": len(cands), "reserved": reserved, "new": len(new),
                "preview": [f"{cid}  {name}" for cid, name in new[:limit or 50]]}
    done, failed, stopped = [], [], False
    for cid, name in new[:limit]:
        print(f"{cid}  {name}", file=sys.stderr)
        try:
            done.append(gym_add(cid))
        except CFNetworkError:            # rede/limite: para; rodar de novo continua daqui
            stopped = True
            break
        except CFPickError as e:          # gym privado, placar quebrado etc.
            cat = _load_gyms()
            cat[str(cid)] = {"name": name, "fetched": int(time.time()), "problems": [], "error": str(e)}
            _save_gyms(cat)
            failed.append(cid)
    return {"added": len(done), "usable": sum(d["usable"] for d in done), "failed": failed,
            "stopped_by_network": stopped, "remaining_new": len(new) - len(done) - len(failed)}


# ---------------------------------------------------------------- CLI
def _main(argv):
    cmd, args = (argv[0] if argv else "pick"), argv[1:]
    if cmd == "pick":
        out = pick(args[0] if args else None)
    elif cmd in ("ok", "fail"):
        out = record(cmd == "ok")
    elif cmd == "skip":
        out = skip()
    elif cmd == "status":
        out = status()
    elif cmd == "gym-add":
        out = [gym_add(c) for c in args]
    elif cmd == "gym-discover":
        nums = [a for a in args if a.isdigit()]
        out = gym_discover(int(nums[0]) if nums else None, dry_run="--dry" in args)
    else:
        print(__doc__)
        return
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        _main(sys.argv[1:])
    except CFPickError as e:
        sys.exit(f"erro: {e}")
