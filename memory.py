"""rigour's memory: rewards, predictions, the frontier of next steps, the claim store and graph retrieval.
Pure functions over plain files. Standard library only.

    py memory.py     # selftest
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
from datetime import date
from pathlib import Path

VALUE = {"high": 1.0, "medium": 0.7, "low": 0.4}
JUDGED = ("works", "partial", "fails")

# Pursuit (bandit) constants. Tune after a few sessions of `py loop.py stats`.
EXPLORE, TEST_BASE, DECAY, REPAIR_BONUS = 0.3, 0.45, 0.85, 0.1
MAX_STEPS_PER_SESSION = 2

# Claim store limits.
MAX_CLAIMS, MAX_ADDS, CLAIM_CHARS = 60, 5, 240
ROLES = {"scout", "triage", "referee", "builder", "novelty", "all"}


# ---------- rewards and predictions ----------

def reward(v: dict) -> float | None:
    """One number per run: what the run is worth. None for errors, so they stay out of averages."""
    verdict = v.get("verdict")
    if verdict in (None, "error"):
        return None
    value = VALUE.get(v.get("useful"), VALUE["medium"])
    return {"works": value, "partial": value / 2, "fails": 0.1}.get(verdict, 0.0)


def predicted(triage: dict) -> float:
    return float(triage.get("p_works") or 0) * VALUE.get(triage.get("useful_if_works"), VALUE["medium"])


PRED_FIELDS = ["date", "run", "idea", "p_works", "predicted", "verdict", "actual", "surprise"]


def log_prediction(path: Path, run: str, idea: str, pred: dict, v: dict) -> None:
    actual = reward(v)
    if actual is None or not isinstance(pred.get("predicted"), (int, float)):
        return
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(PRED_FIELDS)
        w.writerow([date.today().isoformat(), run, idea, pred.get("p_works", ""), round(pred["predicted"], 3),
                    v.get("verdict"), round(actual, 3), round(actual - pred["predicted"], 3)])


def prediction_scores(path: Path, n: int = 20) -> tuple[float, float, int] | None:
    """Mean absolute error of the predicted reward and Brier score of p_works, over the last n rows."""
    if not path.exists():
        return None
    rows = list(csv.DictReader(open(path, encoding="utf-8")))[-n:]
    rows = [r for r in rows if r["p_works"] not in ("", None)]
    if not rows:
        return None
    mae = sum(abs(float(r["surprise"])) for r in rows) / len(rows)
    brier = sum((float(r["p_works"]) - (r["verdict"] == "works")) ** 2 for r in rows) / len(rows)
    return mae, brier, len(rows)


def surprises(path: Path) -> dict[str, float]:
    """run folder name -> surprise."""
    if not path.exists():
        return {}
    return {r["run"]: float(r["surprise"]) for r in csv.DictReader(open(path, encoding="utf-8"))}


# ---------- run history ----------

def history(runs: Path) -> dict[str, list[dict]]:
    """idea -> its runs in time order: {run, verdict, reward, previous_run}. Errors are left out."""
    out: dict[str, list[dict]] = {}
    for f in sorted(runs.glob("*/result.json"), key=lambda f: f.parent.name):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        r = reward(v)
        if r is None or not v.get("idea_id"):
            continue
        out.setdefault(v["idea_id"], []).append({"run": f.parent.name, "verdict": v["verdict"], "reward": r,
                                                 "previous_run": v.get("previous_run")})
    return out


def judged(hist: dict, idea: str) -> list[dict]:
    return [r for r in hist.get(idea, []) if r["verdict"] in JUDGED]


# ---------- frontier and pursuit ----------

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def add_steps(path: Path, idea: str, run: str, steps, today: str | None = None) -> int:
    """Append the referee's next steps (at most 3 valid ones) as open frontier items. Returns how many were added."""
    rows = read_jsonl(path)
    n = sum(r["idea"] == idea for r in rows)
    added = 0
    for s in (steps if isinstance(steps, list) else [])[:3]:
        if not isinstance(s, dict) or s.get("kind") not in ("deepen", "repair") or not str(s.get("step", "")).strip():
            continue
        n += 1
        added += 1
        rows.append({"id": f"{idea}#{n}", "idea": idea, "run": run, "kind": s["kind"], "step": str(s["step"]).strip()[:500],
                     "size": s.get("size", "M"), "created": today or date.today().isoformat(), "status": "open",
                     "result_run": "", "reward": ""})
    if added:
        write_jsonl(path, rows)
    return added


def close_steps(path: Path, status: str, item_id: str | None = None, idea: str | None = None,
                run: str = "", value: float | None = None) -> None:
    """Close one item (by id) or every open item of an idea."""
    rows = read_jsonl(path)
    for r in rows:
        if r["status"] == "open" and (r["id"] == item_id or idea and r["idea"] == idea):
            r.update(status=status, result_run=run, reward="" if value is None else round(value, 3))
    write_jsonl(path, rows)


def score(item: dict, hist: dict, total_runs: int) -> float:
    """UCB1-style: the value of the idea so far, plus a bonus for ideas we know little about."""
    runs = judged(hist, item["idea"])
    bonus = EXPLORE * math.sqrt(math.log(total_runs + 1) / (len(runs) + 1))
    if item["kind"] == "test":
        return TEST_BASE + bonus
    last = runs[-1] if runs else None
    base = (last["reward"] if last else 0.0) * DECAY ** len(runs)
    if item["kind"] == "repair" and last and last["verdict"] == "partial":
        base += REPAIR_BONUS
    return base + bonus


def choose(items: list[dict], hist: dict, total_runs: int) -> dict | None:
    return max(items, key=lambda it: score(it, hist, total_runs), default=None)


def plateau(hist: dict, idea: str) -> bool:
    """The last two advance runs did not beat the run before them."""
    runs = judged(hist, idea)
    if len(runs) < 3 or not all(r["previous_run"] for r in runs[-2:]):
        return False
    return max(r["reward"] for r in runs[-2:]) <= runs[-3]["reward"]


# ---------- claim store (knowledge) ----------

def claim_score(c: dict, today: date | None = None) -> float:
    """Beta mean of support against contradictions, times a forgetting curve."""
    today = today or date.today()
    days = max(0, (today - date.fromisoformat(c.get("seen") or c["created"])).days)
    return (c["support"] + 1) / (c["support"] + c["contra"] + 2) * 0.98 ** days


def apply_ops(claims: list[dict], ops, run_exists, today: str | None = None) -> tuple[list[dict], list[dict]]:
    """Apply consolidation operations. Returns (claims, rejected). Invalid operations change nothing."""
    today = today or date.today().isoformat()
    live = {c["id"]: c for c in claims if c["status"] == "live"}
    rejected, adds = [], 0
    next_id = 1 + max((int(c["id"][1:]) for c in claims if re.fullmatch(r"k\d+", c["id"])), default=0)

    def text_ok(t):
        return isinstance(t, str) and 0 < len(t.strip()) <= CLAIM_CHARS

    def evidence_ok(ev, required):
        return isinstance(ev, list) and (ev or not required) and all(isinstance(r, str) and run_exists(r) for r in ev)

    def new_claim(role, text, evidence, support=1, contra=0):
        nonlocal next_id
        c = {"id": f"k{next_id}", "role": role, "text": text.strip(), "evidence": evidence, "support": support,
             "contra": contra, "created": today, "seen": today, "status": "live"}
        next_id += 1
        claims.append(c)
        live[c["id"]] = c

    for op in ops if isinstance(ops, list) else []:
        kind = op.get("op") if isinstance(op, dict) else None
        if kind == "add" and adds < MAX_ADDS and op.get("role") in ROLES and text_ok(op.get("text")) \
                and evidence_ok(op.get("evidence"), True):
            new_claim(op["role"], op["text"], op["evidence"])
            adds += 1
        elif kind in ("support", "contra") and op.get("id") in live and evidence_ok(op.get("evidence", []), False):
            c = live[op["id"]]
            c[kind] += 1
            c["seen"] = today
            c["evidence"] = list(dict.fromkeys(c["evidence"] + op.get("evidence", [])))[-10:]
        elif kind == "merge" and isinstance(op.get("ids"), list) and len(set(op["ids"])) >= 2 \
                and all(i in live for i in op["ids"]) and text_ok(op.get("text")):
            olds = [live.pop(i) for i in dict.fromkeys(op["ids"])]
            roles = {c["role"] for c in olds}
            new_claim(roles.pop() if len(roles) == 1 else "all", op["text"],
                      list(dict.fromkeys(r for c in olds for r in c["evidence"]))[-10:],
                      sum(c["support"] for c in olds), sum(c["contra"] for c in olds))
            for c in olds:
                c.update(status="retired", merged_into=claims[-1]["id"])
        elif kind == "retire" and op.get("id") in live:
            live.pop(op["id"])["status"] = "retired"
        else:
            rejected.append(op)
            continue
        while len(live) > MAX_CLAIMS:  # capacity: the weakest claim fades
            weakest = min(live.values(), key=lambda c: claim_score(c, date.fromisoformat(today)))
            live.pop(weakest["id"])["status"] = "retired"
    return claims, rejected


def render_knowledge(claims: list[dict]) -> str:
    out = ["# Knowledge", "", "Generated by `records.py` from `knowledge.jsonl`. Claims learned from runs, strongest first.", ""]
    live = [c for c in claims if c["status"] == "live"]
    for role in sorted({c["role"] for c in live}):
        out += [f"## {role}", ""]
        for c in sorted((c for c in live if c["role"] == role), key=claim_score, reverse=True):
            out.append(f"- {c['id']} ({c['support']}+/{c['contra']}-): {c['text']} [{', '.join(c['evidence'][-3:])}]")
        out.append("")
    return "\n".join(out)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def pack(claims: list[dict], role: str, text: str, k: int = 8, budget: int = 1200) -> str:
    """The claims for one role, ranked by strength and word overlap with the task. Small and fixed in size."""
    mine = words(text)
    live = [c for c in claims if c["status"] == "live" and c["role"] in (role, "all")]
    ranked = sorted(live, key=lambda c: claim_score(c) * (1 + len(mine & words(c["text"])) / 5), reverse=True)
    out, size = [], 0
    for c in ranked[:k]:
        line = f"- {c['id']}: {c['text']}\n"
        if size + len(line) > budget:
            break
        out.append(line)
        size += len(line)
    return "".join(out)


# ---------- graph retrieval and elites ----------

def ppr(graph: dict, seeds: dict[str, float], iters: int = 20, restart: float = 0.5) -> dict[str, float]:
    """Personalized PageRank: activation spreads from the seed nodes over undirected edges."""
    nbrs: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        nbrs.setdefault(e["from"], []).append(e["to"])
        nbrs.setdefault(e["to"], []).append(e["from"])
    total = sum(seeds.values()) or 1
    seeds = {k: v / total for k, v in seeds.items()}
    p = dict(seeds)
    for _ in range(iters):
        nxt = {k: restart * v for k, v in seeds.items()}
        for node, mass in p.items():
            for nb in nbrs.get(node, []):
                nxt[nb] = nxt.get(nb, 0.0) + (1 - restart) * mass / len(nbrs[node])
        p = nxt
    return p


def elites(niche: dict[str, tuple], hist: dict) -> list[tuple[str, float, tuple]]:
    """MAP-Elites archive: the idea with the best latest reward in each niche. Ideas with no judged run do not count."""
    best: dict[tuple, tuple[str, float]] = {}
    for idea, key in niche.items():
        runs = judged(hist, idea)
        if runs and runs[-1]["reward"] > best.get(key, ("", 0.0))[1]:
            best[key] = (idea, runs[-1]["reward"])
    return [(idea, r, key) for key, (idea, r) in best.items()]


def sample_parents(archive: list[tuple[str, float, tuple]], k: int = 3, rng=random) -> list[str]:
    """Up to k elites, sampled in proportion to reward. They come from different niches by construction."""
    pool, out = list(archive), []
    while pool and len(out) < k:
        pick = rng.choices(pool, weights=[r for _, r, _ in pool])[0]
        out.append(pick[0])
        pool.remove(pick)
    return out


# ---------- selftest ----------

def _selftest() -> None:
    import tempfile

    assert reward({"verdict": "works", "useful": "high"}) == 1.0
    assert reward({"verdict": "partial", "useful": "medium"}) == 0.35
    assert reward({"verdict": "fails"}) == 0.1 and reward({"verdict": "skip"}) == 0.0
    assert reward({"verdict": "error"}) is None
    assert abs(predicted({"p_works": 0.5, "useful_if_works": "high"}) - 0.5) < 1e-9

    tmp = Path(tempfile.mkdtemp())
    pred = tmp / "predictions.csv"
    assert prediction_scores(pred) is None
    log_prediction(pred, "r1", "a", {"p_works": 0.8, "predicted": 0.56}, {"verdict": "works", "useful": "medium"})
    log_prediction(pred, "r2", "b", {"p_works": 0.6, "predicted": 0.42}, {"verdict": "skip"})
    log_prediction(pred, "r3", "c", {"p_works": 0.5, "predicted": 0.5}, {"verdict": "error"})  # left out
    assert surprises(pred) == {"r1": 0.14, "r2": -0.42}, surprises(pred)
    mae, brier, n = prediction_scores(pred)
    assert n == 2 and abs(mae - 0.28) < 1e-9 and abs(brier - (0.04 + 0.36) / 2) < 1e-9

    # the plan's worked example: 47 runs so far
    hist = {"w": [{"run": "1", "verdict": "works", "reward": 1.0, "previous_run": None}],
            "p": [{"run": "2", "verdict": "partial", "reward": 0.35, "previous_run": None}]}
    s_test = score({"kind": "test", "idea": "new"}, hist, 47)
    s_works = score({"kind": "deepen", "idea": "w"}, hist, 47)
    s_part = score({"kind": "repair", "idea": "p"}, hist, 47)
    assert abs(s_test - 1.04) < 0.01 and abs(s_works - 1.27) < 0.01 and abs(s_part - 0.81) < 0.01, (s_test, s_works, s_part)
    assert choose([{"kind": "test", "idea": "new"}, {"kind": "deepen", "idea": "w"}], hist, 47)["idea"] == "w"
    assert choose([], hist, 47) is None

    flat = [{"run": str(i), "verdict": "works", "reward": r, "previous_run": None if i == 0 else str(i - 1)}
            for i, r in enumerate([0.7, 0.7, 0.35])]
    assert plateau({"x": flat}, "x")
    assert not plateau({"x": flat[:2] + [dict(flat[2], reward=1.0)]}, "x")
    assert not plateau({"x": flat[:2]}, "x")

    front = tmp / "frontier.jsonl"
    assert add_steps(front, "w", "run1", [{"kind": "deepen", "step": "add role binding"}, {"kind": "bad", "step": "x"},
                                          {"kind": "repair", "step": " "}, "junk"]) == 1
    assert add_steps(front, "w", "run2", [{"kind": "repair", "step": "fix it", "size": "S"}]) == 1
    rows = read_jsonl(front)
    assert [r["id"] for r in rows] == ["w#1", "w#2"] and all(r["status"] == "open" for r in rows)
    close_steps(front, "done", item_id="w#1", run="run3", value=0.7)
    close_steps(front, "plateau", idea="w")
    assert [(r["status"], r["reward"]) for r in read_jsonl(front)] == [("done", 0.7), ("plateau", "")]

    runs = {"r1", "r2"}
    claims, rej = apply_ops([], [{"op": "add", "role": "referee", "text": "Bind each number to its role.", "evidence": ["r1"]},
                                 {"op": "add", "role": "builder", "text": "Sample big sources.", "evidence": ["r2"]},
                                 {"op": "add", "role": "nobody", "text": "x", "evidence": ["r1"]},
                                 {"op": "add", "role": "all", "text": "y" * 300, "evidence": ["r1"]},
                                 {"op": "add", "role": "all", "text": "no evidence", "evidence": []},
                                 {"op": "add", "role": "all", "text": "unknown run", "evidence": ["r9"]},
                                 {"op": "support", "id": "k1", "evidence": ["r2"]},
                                 {"op": "contra", "id": "k2"},
                                 {"op": "support", "id": "k99"}], runs.__contains__, "2026-11-26")
    assert len(rej) == 5 and [c["id"] for c in claims] == ["k1", "k2"], rej
    assert claims[0]["support"] == 2 and claims[0]["evidence"] == ["r1", "r2"] and claims[1]["contra"] == 1
    claims, rej = apply_ops(claims, [{"op": "merge", "ids": ["k1", "k2"], "text": "Merged."}, {"op": "retire", "id": "k1"}],
                            runs.__contains__, "2026-11-26")
    assert len(rej) == 1 and claims[2]["id"] == "k3" and claims[2]["role"] == "all" and claims[2]["support"] == 3
    assert [c["status"] for c in claims] == ["retired", "retired", "live"] and claims[0]["merged_into"] == "k3"
    many = [{"op": "add", "role": "all", "text": f"claim {i}", "evidence": ["r1"]} for i in range(MAX_CLAIMS + 5)]
    big = []
    for i in range(0, len(many), MAX_ADDS):
        big, _ = apply_ops(big, many[i:i + MAX_ADDS], runs.__contains__, "2026-11-26")
    assert sum(c["status"] == "live" for c in big) == MAX_CLAIMS
    assert abs(claim_score({"support": 0, "contra": 0, "created": "2026-11-26", "seen": "2026-11-26"}, date(2026, 11, 26)) - 0.5) < 1e-9
    assert "k3: Merged." in pack(claims, "builder", "merged numbers")
    assert pack(claims, "scout", "x").startswith("- k3")  # role "all" reaches every role
    assert "## all" in render_knowledge(claims)

    g = {"edges": [{"from": "a", "to": "p1"}, {"from": "b", "to": "p1"}, {"from": "c", "to": "p2"}]}
    act = ppr(g, {"a": 1.0})
    assert act.get("b", 0) > act.get("c", 0) == 0

    hist2 = {"x": [{"verdict": "works", "reward": 1.0, "previous_run": None}],
             "y": [{"verdict": "works", "reward": 0.4, "previous_run": None}],
             "z": [{"verdict": "partial", "reward": 0.35, "previous_run": None}]}
    arch = elites({"x": ("cv", "p"), "y": ("cv", "p"), "z": ("oe", "q"), "u": ("oe", "q")}, hist2)
    assert sorted(i for i, _, _ in arch) == ["x", "z"]
    assert sorted(sample_parents(arch, 3, random.Random(1))) == ["x", "z"]
    print("memory.py selftest ok")


if __name__ == "__main__":
    _selftest()
