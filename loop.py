"""rigour: scout ideas, check novelty twice, test them with sealed referee tests, record everything.

    py loop.py init                     # create the records folder (ideas/, runs/, CONTEXT.md, TEMPLATE.md)
    py loop.py scout "<topic>"          # new ideas into the records (status idea, or dropped with the prior art)
    py loop.py run <idea-id>            # novelty x2 (+ tie-break) -> referee tests -> build -> judge -> record
    py loop.py canary [n]               # plant n known (dropped) ideas, check the novelty agents catch them
    py loop.py calibration              # canary catch rate per agent
    py loop.py auto [cycles] [topic]    # a fixed number of cycles, then synthesis
    py loop.py night [minutes] [topic]  # until the time is up (the current idea always finishes), then synthesis
    py loop.py synthesise               # journal, links and combined ideas from tonight's runs
    py loop.py schedule HH:MM [minutes] # run `night` every day at HH:MM (Windows Task Scheduler, or prints a cron line)
    py loop.py unschedule

Settings: config.json (copy config.example.json). Each role has an agent, a model, an effort level and skills.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import records

HERE = Path(__file__).resolve().parent
CFG_FILE = Path(os.environ.get("RIGOUR_CONFIG") or (HERE / ("config.json" if (HERE / "config.json").exists() else "config.example.json")))
CFG = json.loads(CFG_FILE.read_text(encoding="utf-8"))
TASK = CFG.get("task_name", "rigour-night")
RECORDS = Path(os.path.expanduser(os.environ.get("RECORDS") or CFG["records"]))
RUNS = RECORDS / "runs"
SHELL = "PowerShell" if os.name == "nt" else "Bash"
WEB = ["WebSearch", "WebFetch"]
PY = [f"{SHELL}(python *)", f"{SHELL}(py *)", f"{SHELL}(pytest *)"]
ROLE_FILES = {"novelty1": "novelty.md", "novelty2": "novelty.md", "tiebreak": "novelty.md", "scout": "scout.md",
              "referee_spec": "referee-spec.md", "builder": "builder.md", "referee_judge": "referee-judge.md", "synth": "synth.md"}
METRICS = ["date", "run", "role", "agent", "model", "cost_usd", "input", "output", "cache_read", "cache_write",
           "web_searches", "seconds", "error"]
now = lambda fmt="%Y%m%d-%H%M": datetime.now().strftime(fmt)  # noqa: E731


class Stop(Exception):
    """End the session cleanly (usage limit or budget), without blaming the idea in progress."""


def spent(since: str) -> float:
    """USD-equivalent logged in metrics.csv since a 'YYYY-MM-DD HH:MM' stamp."""
    if not (RECORDS / "metrics.csv").exists():
        return 0.0
    return sum(float(r["cost_usd"] or 0) for r in csv.DictReader(open(RECORDS / "metrics.csv", encoding="utf-8")) if r["date"] >= since)


def over_budget(session_start: str) -> str:
    b = CFG.get("budget", {})
    if b.get("session_usd") and spent(session_start) >= b["session_usd"]:
        return f"session budget of {b['session_usd']} USD reached"
    if b.get("day_usd") and spent(now("%Y-%m-%d")) >= b["day_usd"]:
        return f"daily budget of {b['day_usd']} USD reached"
    return ""


def role_cfg(role: str) -> dict:
    r = dict(CFG["roles"][role])
    if CFG["agents"][r["agent"]]["kind"] == "codex" and not shutil.which("codex"):
        r["agent"] = CFG["fallback"]["codex"]
    return r


def call(role: str, cwd: Path, task: str = "", tools: list[str] | None = None) -> None:
    """One fresh, isolated agent session in cwd. Results come back as files; cost and tokens go to metrics.csv."""
    r = role_cfg(role)
    a = CFG["agents"][r["agent"]]
    skills = "".join(f"\n\n## Skill: {s}\n\n" + (HERE / "plugin" / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
                     for s in r.get("skills", []))
    prompt = (HERE / "roles" / ROLE_FILES[role]).read_text(encoding="utf-8") + skills + (f"\n\n## Task\n\n{task}" if task else "")
    env = {**os.environ, **{k: os.path.expanduser(v) for k, v in a.get("env", {}).items()}}
    tools = tools or ["Read", "Write", "Glob", "Grep", *WEB]
    if a["kind"] == "claude":
        # --safe-mode: no CLAUDE.md, memory, hooks or plugins. --restricted: file tools stay inside cwd.
        cmd = ["claude", "-p", "Do the task in your instructions. Work in the current folder.",
               "--append-system-prompt", prompt, "--no-session-persistence", "--safe-mode", "--restricted",
               "--permission-mode", "acceptEdits", "--output-format", "json",
               "--model", r["model"], "--effort", r.get("effort", "medium"),
               "--tools", ",".join(sorted({t.split("(")[0] for t in tools})), "--allowed-tools", *tools]
        if r.get("fallback_model"):
            cmd += ["--fallback-model", r["fallback_model"]]
    else:  # shortcut: codex flags untested (no codex on the first dev machine), check `codex exec --help`
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(cwd), "-m", r["model"], prompt]
    print(f"  [{role}: {r['agent']}/{r['model']}] in {cwd.name}", flush=True)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=60 * CFG.get("max_call_minutes", 60),
                       capture_output=True, text=True, encoding="utf-8")
    (cwd / f"_{role}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    log_metrics(cwd, role, r, p.stdout, time.time() - t0)
    # shortcut: matches the limit message text, which Claude Code may change; check _<role>.log if a stop looks wrong
    failed = p.returncode != 0 or re.search(r'"is_error"\s*:\s*true', p.stdout)
    if failed and re.search(r"usage limit|rate limit|limit reached|out of (extra )?usage", p.stdout[-2000:] + p.stderr[-2000:], re.I):
        raise Stop(f"{r['agent']} hit a usage limit during {role}")
    if p.returncode:
        raise SystemExit(f"{role} ({r['agent']}) failed (exit {p.returncode}); see {cwd / f'_{role}.log'}")


def log_metrics(cwd: Path, role: str, r: dict, stdout: str, seconds: float) -> None:
    try:
        d = json.loads(stdout)
        u = d.get("usage", {})
        vals = [d.get("total_cost_usd"), u.get("input_tokens"), u.get("output_tokens"), u.get("cache_read_input_tokens"),
                u.get("cache_creation_input_tokens"), u.get("server_tool_use", {}).get("web_search_requests"), d.get("is_error")]
    except (json.JSONDecodeError, AttributeError):
        vals = [""] * 7  # codex, or a crash before any output
    run = cwd.relative_to(RUNS).parts[0] if RUNS in cwd.parents else cwd.name
    path = RECORDS / "metrics.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(METRICS)
        w.writerow([now("%Y-%m-%d %H:%M"), run, role, r["agent"], r["model"], *vals[:6], round(seconds), vals[6]])


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Expected {path} but the agent did not write it")
    return json.loads(path.read_text(encoding="utf-8"))


def seal(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("_"):
            h.update(p.relative_to(folder).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


def rebuild() -> None:
    records.build(RECORDS)


def commit(message: str) -> None:
    """Commit and push the records repo, if it is one. Plain git, so no tool attribution."""
    if not (RECORDS / ".git").exists() or not CFG.get("auto_commit", True):
        return
    subprocess.run(["git", "add", "-A"], cwd=RECORDS, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RECORDS).returncode:
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=RECORDS, check=True)
        subprocess.run(["git", "push", "-q"], cwd=RECORDS, check=False)


def related(ws: Path, query: str, copy_mvps: int = 0) -> None:
    """Give the agent RELATED.md (top BM25 hits, about 1,500 characters) and, optionally, copies of related earlier MVPs."""
    hits = records.search(RECORDS, query)
    # one-hop graph expansion: ideas linked (helps/related/blocked_by) to the top idea hits, as digest lines
    linked, digest = set(), {}
    if (RECORDS / "graph.json").exists() and (RECORDS / "DIGEST.md").exists():
        top = set(re.findall(r"ideas/([^.\s]+)\.md", hits))
        edges = json.loads((RECORDS / "graph.json").read_text(encoding="utf-8"))["edges"]
        linked = {e["to"] for e in edges if e["from"] in top and e["type"] in ("helps", "related", "blocked_by")} - top
        digest = {ln.split(" | ")[0]: ln for ln in (RECORDS / "DIGEST.md").read_text(encoding="utf-8").splitlines() if " | " in ln}
    extra = "".join(f"- linked: {digest[i][:240]}\n" for i in sorted(linked) if i in digest)
    (ws / "RELATED.md").write_text("# Related earlier records\n\n" + (hits or "None found.\n") + extra, encoding="utf-8")
    for n, run in enumerate(dict.fromkeys(re.findall(r"runs/([^/\s]+)/", hits))):
        if n >= copy_mvps:
            break
        if (RUNS / run / "mvp").exists():
            shutil.copytree(RUNS / run / "mvp", ws / "related" / run, ignore=shutil.ignore_patterns("_*", "__pycache__"))


def novelty(run: Path, idea_text: str, roles=("novelty1", "novelty2")) -> dict:
    out = {}
    for role in roles:
        ws = run / f"novelty-{role}"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "idea.md").write_text(idea_text, encoding="utf-8")
        call(role, ws)
        out[role] = read_json(ws / "novelty.json")
    return out


def check_independence() -> None:
    """Every role is always a separate, fresh, isolated session. `independence` can demand more: a different model or account."""
    level = CFG.get("independence", "session")
    b, j = role_cfg("builder"), role_cfg("referee_judge")
    if level == "account" and b["agent"] == j["agent"]:
        raise SystemExit("config independence=account: builder and referee must use different accounts")
    if level == "model" and (b["agent"], b["model"]) == (j["agent"], j["model"]):
        raise SystemExit("config independence=model: builder and referee must differ in model or account")


def run_idea(idea_id: str) -> Path:
    idea = (RECORDS / "ideas" / f"{idea_id}.md").read_text(encoding="utf-8")
    run = RUNS / f"{now()}-{idea_id}"
    run.mkdir(parents=True)
    check_independence()

    print(f"1/5 novelty: two independent checks on {idea_id}")
    nov = novelty(run, idea)
    verdicts = {v["verdict"] for v in nov.values()}
    if len(verdicts) > 1:  # cascade: escalate to the strong model only when the cheap checks disagree
        print("    the checks disagree: tie-break")
        nov.update(novelty(run, idea, ("tiebreak",)))
        exists = nov["tiebreak"]["verdict"] == "exists"
    else:
        exists = verdicts == {"exists"}
    if exists:
        return record(idea_id, run, {"verdict": "exists", "novelty": nov})

    print("2/5 referee writes criteria and sealed tests")
    spec = HERE / ".sealed" / run.name  # outside the records tree; the builder's file tools cannot reach it
    spec.mkdir(parents=True)
    (spec / "idea.md").write_text(idea, encoding="utf-8")
    write_context(spec, track_of(idea))
    related(spec, idea)
    call("referee_spec", spec, tools=["Read", "Write", "Edit", "Glob", "Grep", *WEB, *PY])
    criteria = (spec / "criteria.md").read_text(encoding="utf-8")
    if criteria.startswith("UNTESTABLE"):
        return record(idea_id, run, {"verdict": "untestable", "novelty": nov, "evidence": [criteria]})
    sealed = seal(spec)

    print("3/5 builder makes the MVP without seeing the tests")
    mvp = run / "mvp"
    mvp.mkdir()
    (mvp / "idea.md").write_text(idea, encoding="utf-8")
    (mvp / "criteria.md").write_text(criteria, encoding="utf-8")
    related(mvp, idea, copy_mvps=2)
    call("builder", mvp, tools=["Read", "Write", "Edit", "Glob", "Grep", *WEB, *PY])

    print("4/5 referee checks the seal, runs its tests and judges")
    if seal(spec) != sealed:
        raise SystemExit("The referee's sealed tests changed during the build. Run stopped.")
    judge = run / "judge"
    shutil.copytree(spec, judge)
    shutil.copytree(spec, run / "referee")
    shutil.copytree(mvp, judge / "mvp", ignore=shutil.ignore_patterns("related"))
    call("referee_judge", judge, tools=["Read", "Write", "Glob", "Grep", *PY])
    v = read_json(judge / "verdict.json")
    v.update(novelty=nov, builder=role_cfg("builder")["agent"], referee=role_cfg("referee_judge")["agent"], seal=sealed)
    print("5/5 record")
    return record(idea_id, run, v)


def record(idea_id: str, run: Path, v: dict) -> Path:
    (run / "result.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    nov = ", ".join(f"{a}: {n['verdict']}" for a, n in v.get("novelty", {}).items())
    tests = f", tests {v['tests_passed']}/{v['tests_total']}, reproduced {v['reproduced']}" if "tests_total" in v else ""
    line = f"- {now('%Y-%m-%d')}: run `{run.name}`: {v['verdict']}{tests}. Novelty ({nov}). {v.get('lessons', '')}".rstrip() + "\n"
    path = RECORDS / "ideas" / f"{idea_id}.md"
    text = re.sub(r"^updated: .*$", f"updated: {now('%Y-%m-%d')}", path.read_text(encoding="utf-8"), count=1, flags=re.M)
    status = {"works": "prototype", "exists": "dropped", "error": "parked"}.get(v["verdict"])
    if status:
        text = re.sub(r"^status: .*$", f"status: {status}", text, count=1, flags=re.M)
    path.write_text(text.rstrip("\n") + "\n" + line, encoding="utf-8")
    rebuild()
    commit(f"{idea_id}: {v['verdict']}")
    print(line.strip())
    return run


def add_ideas(folder: Path) -> list[str]:
    added = []
    for p in sorted(folder.glob("*.md")):
        if (RECORDS / "ideas" / p.name).exists():
            print(f"  skip {p.name}: already in the records")
            continue
        shutil.copy(p, RECORDS / "ideas" / p.name)
        added.append(p.stem)
    return added


def tracks() -> list[str]:
    """Track names, from `## Track: <name>` headings in CONTEXT.md."""
    ctx = RECORDS / "CONTEXT.md"
    return [t.lower() for t in re.findall(r"^## Track: (\S+)", ctx.read_text(encoding="utf-8"), re.M)] if ctx.exists() else []


def split_track(text: str) -> tuple[str | None, str]:
    """'cv', 'CV idea' or 'oe ideas about X' -> (track, rest of the topic)."""
    words = text.split()
    if not words or words[0].lower() not in tracks():
        return None, text
    rest = words[1:]
    if rest and rest[0].lower() in ("idea", "ideas"):
        rest = rest[1:]
    if rest and rest[0].lower() in ("about", "on", "for"):
        rest = rest[1:]
    return words[0].lower(), " ".join(rest)


def track_of(idea_text: str) -> str | None:
    m = re.search(r"^tags: \[(.*)\]", idea_text, re.M)
    tags = {t.strip().lower() for t in m.group(1).split(",")} if m else set()
    return next((t for t in tracks() if t in tags), None)


def write_context(ws: Path, track: str | None) -> None:
    """Copy CONTEXT.md with the shared sections and only the chosen track's section (all tracks if None)."""
    ctx = RECORDS / "CONTEXT.md"
    if not ctx.exists():
        return
    parts = re.split(r"(?m)^(?=## )", ctx.read_text(encoding="utf-8"))
    head = lambda p: p.split("\n", 1)[0].strip().lower()  # noqa: E731
    keep = [p for p in parts if track is None or not head(p).startswith("## track: ") or head(p) == f"## track: {track}"]
    (ws / "CONTEXT.md").write_text("".join(keep), encoding="utf-8")


def scout(topic: str, track: str | None = None) -> list[str]:
    ws = RUNS / (f"{now()}-scout" + (f"-{track}" if track else ""))
    (ws / "out").mkdir(parents=True)
    for f in ("DIGEST.md", "TEMPLATE.md"):
        if (RECORDS / f).exists():
            shutil.copy(RECORDS / f, ws)
    write_context(ws, track)
    if track:
        task = (f"Track: {track}. Generate ideas only for the 'Track: {track}' section of CONTEXT.md, and put `{track}` "
                f"in each idea's tags." + (f" Topic: {topic}" if topic else ""))
    else:
        task = (topic or "Use the topics in CONTEXT.md.") + (
            f" Put the matching track name ({', '.join(tracks())}) in each idea's tags." if tracks() else "")
    related(ws, task)
    call("scout", ws, task=task)
    added = add_ideas(ws / "out")
    rebuild()
    commit(f"scout: {len(added)} ideas")
    print(f"added {len(added)} ideas: {', '.join(added)}")
    return added


def canary(n: int = 1, roles=("novelty1", "novelty2")) -> None:
    """Plant known ideas (dropped, with prior art) and check whether each novelty agent says 'exists'."""
    dropped = [p for p in (RECORDS / "ideas").glob("*.md") if re.search(r"^status: dropped$", p.read_text(encoding="utf-8"), re.M)]
    if not dropped:
        return print("No dropped ideas to use as canaries yet.")
    log = RECORDS / "calibration.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "canary", "agent", "verdict", "caught", "confidence"])
        for p in random.sample(dropped, min(n, len(dropped))):
            text = p.read_text(encoding="utf-8")
            title = re.search(r"^title: (.*)$", text, re.M).group(1)
            problem = text.split("## Problem", 1)[1].split("##", 1)[0].strip() if "## Problem" in text else ""
            blind = f"# {title}\n\n{problem}\n"  # no status, prior art or lessons: the agent must find them
            for role, res in novelty(RUNS / f"{now()}-canary-{p.stem}", blind, roles).items():
                agent = f"{role_cfg(role)['agent']}/{role_cfg(role)['model']}"
                w.writerow([now("%Y-%m-%d"), p.stem, agent, res["verdict"], res["verdict"] == "exists", res.get("confidence")])
                print(f"  {p.stem} / {agent}: {res['verdict']}")
    commit(f"canary x{n}")


def calibration() -> None:
    rows = list(csv.DictReader(open(RECORDS / "calibration.csv", encoding="utf-8")))
    for agent in sorted({r["agent"] for r in rows}):
        mine = [r for r in rows if r["agent"] == agent]
        print(f"{agent}: caught {sum(r['caught'] == 'True' for r in mine)}/{len(mine)} canaries")


def untested(track: str | None = None) -> list[str]:
    """Ideas with status 'idea', no run yet and (if given) the track's tag, oldest first."""
    out = []
    for p in sorted((RECORDS / "ideas").glob("*.md"), key=lambda p: p.stat().st_mtime):
        text = p.read_text(encoding="utf-8")
        if (re.search(r"^status: idea\s*(#.*)?$", text, re.M) and not re.search(r"run `\d{8}-\d{4}-", text)
                and (track is None or track_of(text) == track)):
            out.append(p.stem)
    return out


def session(topic: str = "", cycles: int | None = None, minutes: float | None = None) -> None:
    """The unattended loop. A new idea starts only before the deadline; the one in progress always finishes."""
    track, topic = split_track(topic)
    print(f"Track: {track or 'all'}" + (f", topic: {topic}" if topic else ""))
    start = datetime.now()
    stamp = start.strftime("%Y-%m-%d %H:%M")
    deadline = time.time() + 60 * minutes if minutes else float("inf")
    go = lambda: time.time() < deadline and not over_budget(stamp)  # noqa: E731  checked before anything new starts
    rebuild()  # orient: fresh digest and search index before any agent runs
    c = 0
    try:
        while go() and (cycles is None or c < cycles):
            c += 1
            print(f"=== cycle {c}" + (f", {round((deadline - time.time()) / 60)} min left" if minutes else "")
                  + f", {spent(stamp):.2f} USD so far")
            if c % 3 == 0:
                canary(1)
            queue = untested(track)
            if len(queue) < 2 and go():
                scout(topic, track)
                queue = untested(track)
            if not queue or not go():
                break
            try:
                run_idea(queue[0])
            except (SystemExit, subprocess.TimeoutExpired) as e:  # one failed run must not stop the night
                print(f"  run failed: {e}")
                failed = RUNS / f"{now()}-{queue[0]}-error"
                failed.mkdir(parents=True, exist_ok=True)
                record(queue[0], failed, {"verdict": "error", "lessons": f"Run error: {e}"})
    except Stop as e:
        print(f"Stopping early: {e}. The idea in progress stays untested and goes first next time.")
        commit(f"session stopped: {e}")
        return  # no synthesis call when the account is out of usage
    print(f"Session ends: {over_budget(stamp) or 'time or cycles used up'}")
    synthesise(start)


def tonight_summary(since: datetime) -> str:
    """Built by script: one block per run since `since`, plus cost per run compared with earlier sessions."""
    out = []
    for f in sorted(RUNS.glob("*/result.json")):
        if datetime.fromtimestamp(f.stat().st_mtime) >= since:
            v = json.loads(f.read_text(encoding="utf-8"))
            nov = ", ".join(f"{a}: {n['verdict']}" for a, n in v.get("novelty", {}).items())
            out.append(f"- {f.parent.name}: {v['verdict']}, tests {v.get('tests_passed', '-')}/{v.get('tests_total', '-')}, "
                       f"reproduced {v.get('reproduced', '-')}, useful {v.get('useful', '-')}. Novelty: {nov}. {v.get('lessons', '')}")
    if (RECORDS / "calibration.csv").exists():
        for row in csv.DictReader(open(RECORDS / "calibration.csv", encoding="utf-8")):
            if row["date"] >= since.strftime("%Y-%m-%d"):
                out.append(f"- canary {row['canary']} / {row['agent']}: {row['verdict']} (caught: {row['caught']})")
    if not out:
        out.append("- No runs or canaries this session.")
    cost = {"tonight": [], "before": []}
    if (RECORDS / "metrics.csv").exists():
        for row in csv.DictReader(open(RECORDS / "metrics.csv", encoding="utf-8")):
            key = "tonight" if row["date"] >= since.strftime("%Y-%m-%d %H:%M") else "before"
            cost[key].append(float(row["cost_usd"] or 0))
    mean = lambda xs: f"{sum(xs) / len(xs):.3f}" if xs else "-"  # noqa: E731
    out.append(f"\nAgent calls tonight: {len(cost['tonight'])}, total {sum(cost['tonight']):.2f} USD-equivalent, "
               f"mean per call {mean(cost['tonight'])} (earlier sessions: {mean(cost['before'])}).")
    return "\n".join(out) + "\n"


def synthesise(since: datetime | None = None) -> None:
    """End of session: journal entry, new links between ideas, and combined ideas. One cheap-model call."""
    since = since or datetime.now().replace(hour=0, minute=0)
    ws = RUNS / f"{now()}-synthesis"
    (ws / "out").mkdir(parents=True)
    for f in ("CONTEXT.md", "DIGEST.md", "TEMPLATE.md"):
        if (RECORDS / f).exists():
            shutil.copy(RECORDS / f, ws)
    summary = tonight_summary(since)
    (ws / "TONIGHT.md").write_text("# Tonight\n\n" + summary, encoding="utf-8")
    related(ws, summary)
    call("synth", ws, tools=["Read", "Write", "Glob", "Grep"])
    (RECORDS / "journal").mkdir(exist_ok=True)
    if (ws / "journal.md").exists():
        shutil.copy(ws / "journal.md", RECORDS / "journal" / f"{now('%Y-%m-%d-%H%M')}.md")
    links = json.loads((ws / "links.json").read_text(encoding="utf-8")) if (ws / "links.json").exists() else []
    for link in links:
        add_link(link.get("from", ""), link.get("to", ""), link.get("type", "related"))
    added = add_ideas(ws / "out")
    rebuild()
    commit(f"synthesis: {len(links)} links, {len(added)} combined ideas")
    print(f"synthesis: journal written, {len(links)} links, {len(added)} combined ideas")


def add_link(src: str, dst: str, kind: str) -> None:
    path = RECORDS / "ideas" / f"{src}.md"
    if kind not in ("related", "helps") or not path.exists() or not (RECORDS / "ideas" / f"{dst}.md").exists():
        return
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^{kind}: \[(.*)\]$", text, re.M)
    items = [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []
    if dst not in items:
        new = f"{kind}: [{', '.join(items + [dst])}]"
        text = text.replace(m.group(0), new, 1) if m else text.replace("\n---\n", f"\n{new}\n---\n", 1)
        path.write_text(text, encoding="utf-8")


def schedule(at: str, minutes: str = "60") -> None:
    cmd_file = HERE / f"{TASK}.cmd"
    (HERE / "logs").mkdir(exist_ok=True)
    log = HERE / "logs" / f"{TASK}.log"
    cmd_file.write_text(f'@echo off\ncd /d "{HERE}"\nset RIGOUR_CONFIG={CFG_FILE}\n'
                        f'"{sys.executable}" loop.py night {minutes} >> "{log}" 2>&1\n', encoding="utf-8")
    if os.name != "nt":
        return print(f"Add this line with `crontab -e`:\n{at[3:5]} {at[:2]} * * * cd {HERE} && "
                     f"RIGOUR_CONFIG={CFG_FILE} {sys.executable} loop.py night {minutes} >> {log} 2>&1")
    subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", at, "/TN", TASK, "/TR", f'"{cmd_file}"'], check=True)
    print(f"Scheduled {TASK}: every day at {at}, {minutes} minutes. Log: {log}. The computer must be on, awake and logged in.")


def unschedule() -> None:
    if os.name == "nt":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK], check=False)
    else:
        print("Remove the line with `crontab -e`.")


def init() -> None:
    for d in ("ideas", "runs", "journal"):
        (RECORDS / d).mkdir(parents=True, exist_ok=True)
    for name in ("TEMPLATE.md", "CONTEXT.md"):
        if not (RECORDS / name).exists():
            shutil.copy(HERE / "templates" / name, RECORDS / name)
    gi = RECORDS / ".gitignore"
    if not gi.exists():
        gi.write_text("search.sqlite\n__pycache__/\n*.pyc\n", encoding="utf-8")
    rebuild()
    print(f"Records folder ready: {RECORDS}. Edit CONTEXT.md first.")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    num = lambda i, d: float(args[i]) if len(args) > i else d  # noqa: E731
    t, rest = split_track(" ".join(args if cmd == "scout" else args[1:]))
    {"init": init, "scout": lambda: scout(rest, t), "run": lambda: run_idea(args[0]),
     "canary": lambda: canary(int(num(0, 1))), "calibration": calibration,
     "auto": lambda: session(" ".join(args[1:]), cycles=int(num(0, 3))),
     "night": lambda: session(" ".join(args[1:]), minutes=num(0, 60)),
     "synthesise": lambda: synthesise(), "schedule": lambda: schedule(args[0], args[1] if len(args) > 1 else "60"),
     "unschedule": unschedule}.get(cmd, lambda: print(__doc__))()
