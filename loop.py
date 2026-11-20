"""rigour: scout ideas, check novelty twice, test them with sealed referee tests, record everything.

    py loop.py init                     # create the records folder (ideas/, runs/, CONTEXT.md, TEMPLATE.md)
    py loop.py scout "<topic>"          # new ideas into the records (status idea, or dropped with the prior art)
    py loop.py run <idea-id>            # novelty x2 (+ tie-break) -> referee tests -> build -> judge -> record
    py loop.py resume <idea-id>          # repair the most recent partial run and judge it again
    py loop.py canary [n]               # plant n known (dropped) ideas, check the novelty agents catch them
    py loop.py calibration              # canary catch rate per agent
    py loop.py usage [now]              # 5-hour and weekly subscription usage per agent (now = live reading)
    py loop.py auto [cycles] [topic]    # a fixed number of cycles, then a session report
    py loop.py night [minutes] [topic]  # start work until the time is up, then write a session report
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
from uuid import uuid4

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
R = [f"{SHELL}(Rscript *)", f"{SHELL}(Rscript.exe *)"]
ROLE_FILES = {"novelty1": "novelty.md", "novelty2": "novelty.md", "tiebreak": "novelty.md", "scout": "scout.md",
              "referee_spec": "referee-spec.md", "builder": "builder.md", "referee_judge": "referee-judge.md", "synth": "synth.md"}
METRICS = ["date", "run", "role", "agent", "model", "cost_usd", "input", "output", "cache_read", "cache_write",
           "web_searches", "seconds", "error", "tokens_total", "five_hour_pct", "seven_day_pct"]
now = lambda fmt="%Y%m%d-%H%M": datetime.now().strftime(fmt)  # noqa: E731


class Stop(Exception):
    """End the session cleanly (usage limit or budget), without blaming the idea in progress."""


def spent(since: str) -> float:
    """USD-equivalent logged in metrics.csv since a 'YYYY-MM-DD HH:MM' stamp."""
    if not (RECORDS / "metrics.csv").exists():
        return 0.0
    return sum(float(r["cost_usd"] or 0) for r in csv.DictReader(open(RECORDS / "metrics.csv", encoding="utf-8")) if r["date"] >= since)


def latest_usage() -> dict:
    """Latest subscription usage per agent from metrics.csv: {agent: (five_hour_pct, seven_day_pct, date)}."""
    out = {}
    if (RECORDS / "metrics.csv").exists():
        for r in csv.DictReader(open(RECORDS / "metrics.csv", encoding="utf-8")):
            if r.get("five_hour_pct") or r.get("seven_day_pct"):
                out[r["agent"]] = (r.get("five_hour_pct"), r.get("seven_day_pct"), r["date"])
    return out


def over_budget(session_start: str) -> str:
    b = CFG.get("budget", {})
    if b.get("session_usd") and spent(session_start) >= b["session_usd"]:
        return f"session budget of {b['session_usd']} USD reached"
    if b.get("day_usd") and spent(now("%Y-%m-%d")) >= b["day_usd"]:
        return f"daily budget of {b['day_usd']} USD reached"
    for agent, (five, seven, _) in latest_usage().items():
        if b.get("five_hour_pct") and five and float(five) >= b["five_hour_pct"]:
            return f"{agent} is at {five}% of its 5-hour limit (cap {b['five_hour_pct']}%)"
        if b.get("seven_day_pct") and seven and float(seven) >= b["seven_day_pct"]:
            return f"{agent} is at {seven}% of its weekly limit (cap {b['seven_day_pct']}%)"
    return ""


def parse_claude(stdout: str) -> dict:
    """Read Claude's stream-json events: the final result and the latest subscription usage."""
    res, status, windows = {}, "allowed", {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            res = event
        elif event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            status = info.get("status", status)
            windows.update({k: v for k, v in (info.get("unifiedWindows") or {}).items()
                            if v and v.get("utilization") is not None})
            if info.get("rateLimitType") and info.get("utilization") is not None:
                windows[info["rateLimitType"]] = info
    pct = lambda name: round(100 * windows[name]["utilization"], 1) if name in windows else ""
    return {"result": res, "five": pct("five_hour"), "seven": pct("seven_day"), "status": status,
            "resets": {name: window.get("resetsAt") for name, window in windows.items()}}


def codex_usage(codex_home: str, since: float, output: str = "") -> dict:
    session = re.search(r"(?im)^session id:\s*([0-9a-f-]{36})\s*$", output)
    files = Path(codex_home).glob(f"sessions/**/*{session[1]}.jsonl" if session else "sessions/**/*.jsonl")
    recent = [(mtime, path) for path in files if (mtime := path.stat().st_mtime) >= since - 5]
    for _, path in sorted(recent, reverse=True):
        windows = {}
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "event_msg":
                    continue
                payload = event.get("payload") or {}
                limits = payload.get("rate_limits") or {}
                if payload.get("type") != "token_count" or limits.get("limit_id") not in (None, "codex"):
                    continue
                for key, default_minutes in (("primary", 300), ("secondary", 10080)):
                    window = limits.get(key) or {}
                    if window.get("used_percent") is not None:
                        windows[window.get("window_minutes") or default_minutes] = window
        if 300 in windows or 10080 in windows:
            return {"five": windows.get(300, {}).get("used_percent", ""),
                    "seven": windows.get(10080, {}).get("used_percent", ""),
                    "resets": {"five_hour": windows.get(300, {}).get("resets_at"),
                               "seven_day": windows.get(10080, {}).get("resets_at")}}
    return {"five": "", "seven": "", "resets": {}}


def role_cfg(role: str) -> dict:
    r = dict(CFG["roles"][role])
    if CFG["agents"][r["agent"]]["kind"] == "codex" and not shutil.which("codex"):
        r["agent"] = CFG["fallback"]["codex"]
    return r


def usage_accounts() -> dict:
    active = {role_cfg(role)["agent"] for role in CFG["roles"]}
    return {name: agent for name, agent in CFG["agents"].items() if name in active}


def usage_text(five, seven) -> str:
    pct = lambda value: f"{float(value):g}%" if value not in ("", None) else "unavailable"
    return f"5-hour {pct(five)} | weekly {pct(seven)}"


def print_usage() -> None:
    rows = latest_usage()
    for name in usage_accounts():
        five, seven, date = rows.get(name, ("", "", ""))
        stamp = f" (last reported {date})" if date else ""
        print(f"  {name} | {usage_text(five, seven)}{stamp}", flush=True)


def add_r_to_path(env: dict[str, str]) -> None:
    path = env.get("PATH", os.defpath)
    if os.name != "nt" or shutil.which("Rscript", path=path):
        return
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\R-core\R") as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            continue
        r_bin = Path(install_path) / "bin"
        if (r_bin / "Rscript.exe").is_file():
            env["PATH"] = str(r_bin) + os.pathsep + path
            return


def call(role: str, cwd: Path, task: str = "", tools: list[str] | None = None) -> None:
    """One fresh, isolated agent session in cwd. Results come back as files; cost and tokens go to metrics.csv."""
    r = role_cfg(role)
    a = CFG["agents"][r["agent"]]
    skills = "".join(f"\n\n## Skill: {s}\n\n" + (HERE / "plugin" / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
                     for s in r.get("skills", []))
    prompt = (HERE / "roles" / ROLE_FILES[role]).read_text(encoding="utf-8") + skills + (f"\n\n## Task\n\n{task}" if task else "")
    env = {**os.environ, **{k: os.path.expanduser(v) for k, v in a.get("env", {}).items()}}
    tools = tools or ["Read", "Write", "Glob", "Grep", *WEB]
    if any(tool in R for tool in tools):
        add_r_to_path(env)
    if a["kind"] == "claude":
        # --safe-mode: no CLAUDE.md, memory, hooks or plugins. --restricted: file tools stay inside cwd.
        cmd = ["claude", "-p", "Do the task in your instructions. Work in the current folder.",
               "--append-system-prompt", prompt, "--no-session-persistence", "--safe-mode", "--restricted",
               "--permission-mode", "acceptEdits", "--output-format", "stream-json", "--verbose",
               "--model", r["model"], "--effort", r.get("effort", "medium"),
               "--tools", ",".join(sorted({t.split("(")[0] for t in tools})), "--allowed-tools", *tools]
        if r.get("fallback_model"):
            cmd += ["--fallback-model", r["fallback_model"]]
    else:
        # Codex: give it its own CODEX_HOME in config.json so your AGENTS.md is not loaded. Sessions are saved there
        # (no --ephemeral) because that is where Codex records its usage limits.
        # workspace-write limits writes to cwd; reads are not confined. The prompt goes in on stdin ("-").
        cmd = [shutil.which("codex") or "codex", "exec", "--skip-git-repo-check", "--ignore-rules",
               "-s", "workspace-write", "-C", str(cwd),
               "-c", 'web_search="live"' if any(t in WEB for t in tools) else 'web_search="disabled"',
               "-c", f'model_reasoning_effort="{r.get("effort", "medium")}"']
        if os.name == "nt":
            cmd += ["-c", 'windows.sandbox="unelevated"']
        if r.get("model") not in (None, "", "default"):
            cmd += ["-m", r["model"]]
        cmd.append("-")
    print(f"  [{role}: {r['agent']}/{r['model']}] in {cwd.name}", flush=True)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=60 * CFG.get("max_call_minutes", 60), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", input=None if a["kind"] == "claude" else prompt)
    (cwd / f"_{role}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    if a["kind"] == "claude":
        u = parse_claude(p.stdout)
    else:
        u = codex_usage(env.get("CODEX_HOME") or os.path.expanduser("~/.codex"), t0, p.stderr + "\n" + p.stdout)
    log_metrics(cwd, role, r, u, time.time() - t0, p.stdout + p.stderr)
    cost = (u.get("result") or {}).get("total_cost_usd")
    price = f"USD-equivalent ${cost:.3f}" if cost is not None else "USD-equivalent unavailable"
    print(f"  [{role} complete] {r['agent']} | {usage_text(u['five'], u['seven'])} | {price}", flush=True)
    if u.get("status", "allowed") != "allowed":
        raise Stop(f"{r['agent']} reports its usage limit as '{u['status']}' during {role}")
    # shortcut: matches the limit message text, which the CLIs may change; check _<role>.log if a stop looks wrong
    failed = p.returncode != 0 or u.get("result", {}).get("is_error")
    if failed and re.search(r"usage limit|rate limit|limit reached|out of (extra )?usage", p.stdout[-2000:] + p.stderr[-2000:], re.I):
        raise Stop(f"{r['agent']} hit a usage limit during {role}")
    if p.returncode:
        raise SystemExit(f"{role} ({r['agent']}) failed (exit {p.returncode}); see {cwd / f'_{role}.log'}")


def log_metrics(cwd: Path, role: str, r: dict, u: dict, seconds: float, raw: str = "") -> None:
    d = u.get("result") or {}
    us = d.get("usage", {})
    if d:
        vals = [d.get("total_cost_usd"), us.get("input_tokens"), us.get("output_tokens"), us.get("cache_read_input_tokens"),
                us.get("cache_creation_input_tokens"), us.get("server_tool_use", {}).get("web_search_requests"), d.get("is_error")]
        total = sum(int(us.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    else:
        vals = [""] * 7
        m = re.search(r"tokens used\s*([\d,]+)", raw)  # Codex prints its total; it reports no cost
        total = int(m.group(1).replace(",", "")) if m else ""
    run = cwd.relative_to(RUNS).parts[0] if RUNS in cwd.parents else cwd.name
    path = RECORDS / "metrics.csv"
    if path.exists() and path.read_text(encoding="utf-8").split("\n", 1)[0].strip() != ",".join(METRICS):
        old = list(csv.DictReader(open(path, encoding="utf-8")))  # files from older versions: add the new columns
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, METRICS, extrasaction="ignore")
            w.writeheader()
            w.writerows(old)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(METRICS)
        w.writerow([now("%Y-%m-%d %H:%M"), run, role, r["agent"], r["model"], *vals[:6], round(seconds), vals[6], total,
                    u.get("five", ""), u.get("seven", "")])


def usage(probe: bool = False) -> None:
    """Show each agent's 5-hour and weekly usage. With `now`, make one tiny call per agent for fresh numbers."""
    if probe:
        for name, a in usage_accounts().items():
            env = {**os.environ, **{k: os.path.expanduser(v) for k, v in a.get("env", {}).items()}}
            t0 = time.time()
            if a["kind"] == "claude":
                p = subprocess.run(["claude", "-p", "Reply with the single word ok.", "--model", "haiku", "--effort", "low",
                                    "--no-session-persistence", "--safe-mode", "--output-format", "stream-json", "--verbose"],
                                   env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
                u = parse_claude(p.stdout)
            else:
                cmd = [shutil.which("codex") or "codex", "exec", "--skip-git-repo-check", "--ignore-rules", "-s", "read-only", "-"]
                p = subprocess.run(cmd, input="Reply with the single word ok.", env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=300, cwd=HERE)
                u = codex_usage(env.get("CODEX_HOME") or os.path.expanduser("~/.codex"), t0, p.stderr + "\n" + p.stdout)
            resets = u["resets"]
            windows = ", ".join(f"{label} resets {datetime.fromtimestamp(resets[key]).strftime('%a %H:%M')}"
                                for key, label in (("five_hour", "5-hour"), ("seven_day", "weekly")) if resets.get(key))
            print(f"{name} | {usage_text(u['five'], u['seven'])}" + (f" ({windows})" if windows else ""), flush=True)
        return
    print_usage()


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
    subprocess.run(["git", "-c", "core.safecrlf=false", "add", "-A"], cwd=RECORDS, check=True)
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


def novelty(run: Path, idea_text: str, roles=("novelty1", "novelty2"), task: str = "") -> dict:
    out = {}
    for role in roles:
        ws = run / f"novelty-{role}"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "idea.md").write_text(idea_text, encoding="utf-8")
        call(role, ws, task=task)
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
    decisive = list(nov.values())
    if len(verdicts) > 1:
        print("    the checks disagree: tie-break")
        task = ("Assess both earlier checks below. Open the decisive sources yourself. "
                "Explain which core feature they already deliver and what gap remains.\n"
                + json.dumps(nov, indent=2))
        nov.update(novelty(run, idea, ("tiebreak",), task=task))
        decisive = [nov["tiebreak"]]
    verdict = decisive[0]["verdict"]
    matches = [hit for check in decisive for hit in check.get("closest", [])
               if hit.get("matches") and hit.get("url")]
    if verdict == "exists" and matches:
        return record(idea_id, run, {"verdict": "exists", "novelty": nov})
    if verdict != "novel":
        return record(idea_id, run, {"verdict": "review", "novelty": nov,
                                   "lessons": "Review the cited prior art before building or dropping this idea."})

    print("2/5 referee writes criteria and sealed tests")
    spec = HERE / ".sealed" / run.name  # outside the records tree; the builder's file tools cannot reach it
    spec.mkdir(parents=True)
    (spec / "idea.md").write_text(idea, encoding="utf-8")
    write_context(spec, track_of(idea))
    related(spec, idea)
    call("referee_spec", spec, tools=["Read", "Write", "Edit", "Glob", "Grep", *WEB, *PY, *R])
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

    return judge_mvp(idea_id, run, spec, mvp, sealed, nov)


def resume(idea_id: str) -> Path:
    if Path(idea_id).name != idea_id:
        raise SystemExit("Use an idea ID from the records.")
    path = RECORDS / "ideas" / f"{idea_id}.md"
    if not path.is_file():
        raise SystemExit(f"Unknown idea: {idea_id}")
    idea = path.read_text(encoding="utf-8")
    history = re.findall(r"^- \d{4}-\d{2}-\d{2}: run `([^/\\`]+)`:", idea, re.M)
    if not history:
        raise SystemExit(f"No completed run for {idea_id}")
    previous = RUNS / history[-1]
    result = read_json(previous / "result.json")
    if result["verdict"] != "partial":
        raise SystemExit(f"The last verdict for {idea_id} was {result['verdict']}. Resume requires partial.")
    check_independence()
    run = RUNS / f"{now()}-repair-{uuid4().hex[:8]}-{idea_id}"
    run.mkdir()
    spec = HERE / ".sealed" / run.name
    shutil.copytree(previous / "referee", spec)
    regression = spec.with_name(f"{run.name}-regressions")
    regression.mkdir()
    shutil.copy2(spec / "criteria.md", regression / "criteria.md")
    shutil.copy2(spec / "idea.md", regression / "idea.md")
    (regression / "RELATED.md").write_text("\n".join(result.get("evidence", []) + [result.get("lessons", "")]),
                                           encoding="utf-8")
    call("referee_spec", regression, task=(
        "This is a repair test plan. Keep the existing acceptance criteria. Use RELATED.md for the prior verdict. "
        "Write only tests/test_repair.py covering concrete failures from that verdict. "
        "Import the MVP from the sibling mvp directory of the judge workspace. "
        "Cover defects with known answers. Leave broader product work for later."
    ), tools=["Read", "Write", "Edit", "Glob", "Grep", *PY, *R])
    tests = regression / "tests" / "test_repair.py"
    if not tests.is_file() or not tests.stat().st_size:
        raise SystemExit("The referee did not produce repair tests.")
    index = 1
    while (spec / "tests" / f"test_repair_{index}.py").exists():
        index += 1
    shutil.copy2(tests, spec / "tests" / f"test_repair_{index}.py")
    sealed = seal(spec)

    mvp = run / "mvp"
    shutil.copytree(previous / "mvp", mvp, ignore=shutil.ignore_patterns("related", "__pycache__", ".pytest_cache", ".venv"))
    (mvp / "REPAIR.md").write_text(result.get("lessons", ""), encoding="utf-8")
    call("builder", mvp, task=(
        "Repair the existing MVP in place. Read REPAIR.md for the referee's feedback. "
        "Fix the defects within the original acceptance criteria and update REPORT.md."
    ), tools=["Read", "Write", "Edit", "Glob", "Grep", *PY])
    return judge_mvp(idea_id, run, spec, mvp, sealed, result.get("novelty", {}), previous.name)


def judge_mvp(idea_id: str, run: Path, spec: Path, mvp: Path, sealed: str,
              novelty_checks: dict, previous: str | None = None) -> Path:
    print("4/5 referee checks the seal, runs its tests and judges")
    if seal(spec) != sealed:
        raise SystemExit("The referee's sealed tests changed during the build. Run stopped.")
    judge = run / "judge"
    shutil.copytree(spec, judge)
    shutil.copytree(spec, run / "referee")
    shutil.copytree(mvp, judge / "mvp", ignore=shutil.ignore_patterns("related"))
    call("referee_judge", judge, tools=["Read", "Write", "Glob", "Grep", *PY, *R])
    v = read_json(judge / "verdict.json")
    v.update(novelty=novelty_checks, builder=role_cfg("builder")["agent"], referee=role_cfg("referee_judge")["agent"], seal=sealed)
    if previous:
        v["previous_run"] = previous
    print("5/5 record")
    return record(idea_id, run, v)


def record(idea_id: str, run: Path, v: dict) -> Path:
    (run / "result.json").write_text(json.dumps(dict(v, idea_id=idea_id), indent=1), encoding="utf-8")
    nov = ", ".join(f"{a}: {n['verdict']}" for a, n in v.get("novelty", {}).items())
    tests = f", tests {v['tests_passed']}/{v['tests_total']}, reproduced {v['reproduced']}" if "tests_total" in v else ""
    line = f"- {now('%Y-%m-%d')}: run `{run.name}`: {v['verdict']}{tests}. Novelty ({nov}). {v.get('lessons', '')}".rstrip() + "\n"
    path = RECORDS / "ideas" / f"{idea_id}.md"
    text = re.sub(r"^updated: .*$", f"updated: {now('%Y-%m-%d')}", path.read_text(encoding="utf-8"), count=1, flags=re.M)
    status = {"works": "prototype", "exists": "dropped", "review": "parked", "error": "parked"}.get(v["verdict"])
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
    """'work', 'Work idea' or 'portfolio ideas about X' -> (track, rest of the topic)."""
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


def dropped_ideas() -> list[Path]:
    return [p for p in (RECORDS / "ideas").glob("*.md")
            if re.search(r"^status: dropped$", p.read_text(encoding="utf-8"), re.M)]


def canary(n: int = 1, roles=("novelty1", "novelty2"), candidates: list[Path] | None = None) -> list[Path]:
    dropped = dropped_ideas() if candidates is None else candidates
    selected = random.sample(dropped, min(n, len(dropped)))
    if not selected:
        print("No eligible dropped ideas for calibration.")
        return []
    log = RECORDS / "calibration.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "canary", "agent", "verdict", "caught", "confidence"])
        for p in selected:
            text = p.read_text(encoding="utf-8")
            title = re.search(r"^title: (.*)$", text, re.M).group(1)
            problem = text.split("## Problem", 1)[1].split("##", 1)[0].strip() if "## Problem" in text else ""
            blind = f"# {title}\n\n{problem}\n"  # no status, prior art or lessons: the agent must find them
            for role, res in novelty(RUNS / f"{now()}-canary-{p.stem}", blind, roles).items():
                agent = f"{role_cfg(role)['agent']}/{role_cfg(role)['model']}"
                w.writerow([now("%Y-%m-%d"), p.stem, agent, res["verdict"], res["verdict"] == "exists", res.get("confidence")])
                print(f"  {p.stem} / {agent}: {res['verdict']}")
    commit(f"canary x{len(selected)}")
    return selected


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
    canary_pool = dropped_ideas()
    c = 0
    try:
        while go() and (cycles is None or c < cycles):
            c += 1
            print(f"=== cycle {c}" + (f", {round((deadline - time.time()) / 60)} min left" if minutes else "")
                  + f", ${spent(stamp):.2f} Claude USD-equivalent so far", flush=True)
            print_usage()
            if c % 3 == 0:
                for case in canary(candidates=canary_pool):
                    canary_pool.remove(case)
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
        write_session_report(start)
        commit(f"session stopped: {e}")
        return  # no synthesis call when the account is out of usage
    print(f"Session ends: {over_budget(stamp) or 'time or cycles used up'}")
    write_session_report(start)
    if CFG.get("auto_synthesis", False):
        synthesise(start)
    else:
        commit("session report")


def write_session_report(since: datetime) -> None:
    report = RECORDS / "journal" / f"{now('%Y-%m-%d-%H%M%S')}-session.md"
    report.parent.mkdir(exist_ok=True)
    summary = tonight_summary(since)
    report.write_text("# Session report\n\n" + summary, encoding="utf-8")
    print(summary, end="", flush=True)
    print(f"Session report: {report}", flush=True)


def tonight_summary(since: datetime) -> str:
    out = []
    for f in sorted(RUNS.glob("*/result.json")):
        if datetime.fromtimestamp(f.stat().st_mtime) < since:
            continue
        v = json.loads(f.read_text(encoding="utf-8"))
        nov = ", ".join(f"{role}={check['verdict']}" for role, check in v.get("novelty", {}).items())
        out.append(f"- {f.parent.name}: **{v['verdict']}** ([result](../runs/{f.parent.name}/result.json))")
        if "tests_total" in v:
            out.append(f"  - Tests {v['tests_passed']}/{v['tests_total']}. Reproduced: {v.get('reproduced')}.")
        if nov:
            out.append(f"  - Novelty: {nov}.")
        for evidence in v.get("evidence", []):
            out.append(f"  - {evidence}")
        checks = v.get("novelty", {})
        if "tiebreak" in checks:
            checks = {"tiebreak": checks["tiebreak"]}
        for check in checks.values():
            for hit in check.get("closest", []):
                if hit.get("matches") and hit.get("url") and check["verdict"] == "exists":
                    item = f"  - Prior art: {hit['name']} ({hit['url']}) matches {hit['matches']}"
                    if item not in out:
                        out.append(item)
        if v.get("lessons"):
            out.append(f"  - {v['lessons']}")
        if v["verdict"] == "partial":
            idea_id = v.get("idea_id") or f.parent.name.split("-", 2)[2]
            out.append(f"  - Continue with `py loop.py resume {idea_id}`.")
    if not out:
        out.append("- No completed idea runs.")
    if (RECORDS / "calibration.csv").exists():
        with (RECORDS / "calibration.csv").open(encoding="utf-8") as stream:
            checks = [f"- {row['canary']} / {row['agent']}: {row['verdict']} (caught: {row['caught']})"
                      for row in csv.DictReader(stream) if row["date"] == since.strftime("%Y-%m-%d")]
        if checks:
            out.extend(["", "Canary checks logged today", "", *checks])
    rows = []
    if (RECORDS / "metrics.csv").exists():
        with (RECORDS / "metrics.csv").open(encoding="utf-8") as stream:
            rows = [row for row in csv.DictReader(stream) if row["date"] >= since.strftime("%Y-%m-%d %H:%M")]
    priced = [float(row["cost_usd"]) for row in rows if row["cost_usd"]]
    out.extend(["", f"Agent calls: {len(rows)}. Claude USD-equivalent: ${sum(priced):.2f} "
                    f"({len(priced)} priced, {len(rows) - len(priced)} unpriced)."])
    for name, (five, seven, date) in latest_usage().items():
        out.append(f"- {name} | {usage_text(five, seven)} (last reported {date})")
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
     "resume": lambda: resume(args[0]),
     "canary": lambda: canary(int(num(0, 1))), "calibration": calibration, "usage": lambda: usage(args[:1] == ["now"]),
     "auto": lambda: session(" ".join(args[1:]), cycles=int(num(0, 3))),
     "night": lambda: session(" ".join(args[1:]), minutes=num(0, 60)),
     "synthesise": lambda: synthesise(), "schedule": lambda: schedule(args[0], args[1] if len(args) > 1 else "60"),
     "unschedule": unschedule}.get(cmd, lambda: print(__doc__))()
