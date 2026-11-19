"""Research agent: scout ideas, check novelty twice, test them with sealed referee tests, record everything.

    py loop.py init                    # create the records folder (ideas/, runs/, CONTEXT.md, TEMPLATE.md)
    py loop.py scout "<topic>"         # new ideas into the records (status idea, or dropped with the prior art)
    py loop.py run <idea-id>           # novelty x2 -> referee tests -> build -> judge -> record
    py loop.py canary [n]              # plant n known (dropped) ideas, check the novelty agents catch them
    py loop.py calibration             # how often each agent caught the canaries
    py loop.py auto [cycles] [topic]   # unattended: scout when the backlog is low, run, canary every 3rd cycle, commit

Settings: config.json (copy config.example.json). Roles map to agents there. The referee must differ from the builder.
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
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / ("config.json" if (HERE / "config.json").exists() else "config.example.json")).read_text(encoding="utf-8"))
RECORDS = Path(os.path.expanduser(os.environ.get("RECORDS") or CFG["records"]))
RUNS = RECORDS / "runs"
PLUGINS = [HERE / "plugin"] + [Path(os.path.expanduser(p)) for p in CFG.get("extra_plugin_dirs", [])]
READ_ONLY = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write"]
BUILD = ["Read", "Glob", "Grep", "Write", "Edit", "WebSearch", "WebFetch",
         "Bash(python *)", "Bash(py *)", "Bash(pytest *)", "Bash(ls *)", "Bash(dir *)"]
now = lambda fmt="%Y%m%d-%H%M": datetime.now().strftime(fmt)  # noqa: E731


def agent_for(role: str) -> str:
    name = CFG["roles"][role]
    if CFG["agents"][name]["kind"] == "codex" and not shutil.which("codex"):
        name = CFG["fallback"]["codex"]
    return name


def call(agent: str, role_file: str, cwd: Path, task: str = "", tools: list[str] | None = None, timeout: int = 3600) -> None:
    """Run one fresh, non-interactive agent session in cwd. Results come back as files, not stdout."""
    a = CFG["agents"][agent]
    prompt = (HERE / "roles" / role_file).read_text(encoding="utf-8") + (f"\n\n## Task\n\n{task}" if task else "")
    env = {**os.environ, **{k: os.path.expanduser(v) for k, v in a.get("env", {}).items()}}
    if a["kind"] == "claude":
        cmd = ["claude", "-p", "Do the task in your instructions. Work in the current folder.",
               "--append-system-prompt", prompt, "--no-session-persistence", "--permission-mode", "acceptEdits",
               *[x for p in PLUGINS if p.exists() for x in ("--plugin-dir", str(p))],
               "--allowed-tools", *(tools or READ_ONLY)]
    else:  # shortcut: codex flags untested (no codex on the first dev machine), check `codex exec --help`
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(cwd), prompt]
    print(f"  [{agent}] {role_file} in {cwd.relative_to(RECORDS)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True, encoding="utf-8")
    (cwd / f"_{agent}_{role_file}.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"{agent} failed on {role_file} (exit {r.returncode}); see the _*.log file in {cwd}")


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Expected {path} but the agent did not write it")
    return json.loads(path.read_text(encoding="utf-8"))


def seal(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(folder).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


def rebuild() -> None:
    subprocess.run([sys.executable, str(HERE / "records.py"), str(RECORDS)], check=False)


def commit(message: str) -> None:
    """Commit and push the records repo, if it is one. Plain git, so no tool attribution."""
    if not (RECORDS / ".git").exists() or not CFG.get("auto_commit", True):
        return
    subprocess.run(["git", "add", "-A"], cwd=RECORDS, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RECORDS).returncode:
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=RECORDS, check=True)
        subprocess.run(["git", "push", "-q"], cwd=RECORDS, check=False)


def novelty(run: Path, idea_text: str, roles=("scout", "novelty2")) -> dict:
    out = {}
    for role in roles:
        agent = agent_for(role)
        ws = run / f"novelty-{agent}"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "idea.md").write_text(idea_text, encoding="utf-8")
        call(agent, "novelty.md", ws)
        out[agent] = read_json(ws / "novelty.json")
    return out


def run_idea(idea_id: str) -> None:
    idea = (RECORDS / "ideas" / f"{idea_id}.md").read_text(encoding="utf-8")
    run = RUNS / f"{now()}-{idea_id}"
    run.mkdir(parents=True)
    builder, referee = agent_for("builder"), agent_for("referee")
    assert builder != referee, "referee and builder must be different agents"

    print("1/5 novelty, two agents independently")
    nov = novelty(run, idea)
    if all(v["verdict"] == "exists" for v in nov.values()):
        return record(idea_id, run, {"verdict": "exists", "novelty": nov})

    print("2/5 referee writes criteria and sealed tests")
    spec = HERE / ".sealed" / run.name  # outside the records tree while the builder works
    spec.mkdir(parents=True)
    (spec / "idea.md").write_text(idea, encoding="utf-8")
    shutil.copy(RECORDS / "CONTEXT.md", spec) if (RECORDS / "CONTEXT.md").exists() else None
    call(referee, "referee-spec.md", spec, tools=READ_ONLY + ["Bash(python *)", "Bash(pytest *)"])
    criteria = (spec / "criteria.md").read_text(encoding="utf-8")
    if criteria.startswith("UNTESTABLE"):
        return record(idea_id, run, {"verdict": "untestable", "novelty": nov, "evidence": [criteria]})
    sealed = seal(spec)

    print("3/5 builder makes the MVP without seeing the tests")
    mvp = run / "mvp"
    mvp.mkdir()
    (mvp / "idea.md").write_text(idea, encoding="utf-8")
    (mvp / "criteria.md").write_text(criteria, encoding="utf-8")
    # shortcut: tests sit outside the builder's folder and the seal catches edits, but a determined builder could still read them; use a container if that matters.
    call(builder, "builder.md", mvp, tools=BUILD)

    print("4/5 referee checks the seal, runs its tests and judges")
    if seal(spec) != sealed:
        raise SystemExit("The referee's sealed tests changed during the build. Run stopped.")
    judge = run / "judge"
    shutil.copytree(spec, judge)
    shutil.copytree(spec, run / "referee")
    shutil.copytree(mvp, judge / "mvp")
    call(referee, "referee-judge.md", judge, tools=READ_ONLY + ["Bash(python *)", "Bash(pytest *)", "Bash(py *)"])
    v = read_json(judge / "verdict.json")
    v.update(novelty=nov, builder=builder, referee=referee, seal=sealed)
    print("5/5 record")
    record(idea_id, run, v)


def record(idea_id: str, run: Path, v: dict) -> None:
    (run / "result.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    nov = ", ".join(f"{a}: {n['verdict']}" for a, n in v.get("novelty", {}).items())
    tests = f", tests {v['tests_passed']}/{v['tests_total']}, reproduced {v['reproduced']}" if "tests_total" in v else ""
    line = f"- {now('%Y-%m-%d')}: run `{run.name}`: {v['verdict']}{tests}. Novelty ({nov}). {v.get('lessons', '')}".rstrip() + "\n"
    path = RECORDS / "ideas" / f"{idea_id}.md"
    text = re.sub(r"^updated: .*$", f"updated: {now('%Y-%m-%d')}", path.read_text(encoding="utf-8"), count=1, flags=re.M)
    status = {"works": "prototype", "exists": "dropped"}.get(v["verdict"])
    if status:
        text = re.sub(r"^status: .*$", f"status: {status}", text, count=1, flags=re.M)
    path.write_text(text.rstrip("\n") + "\n" + line, encoding="utf-8")
    rebuild()
    commit(f"{idea_id}: {v['verdict']}")
    print(line.strip())


def scout(topic: str) -> list[str]:
    ws = RUNS / f"{now()}-scout"
    (ws / "out").mkdir(parents=True)
    for f in ("CONTEXT.md", "INDEX.md", "graph.json", "TEMPLATE.md"):
        if (RECORDS / f).exists():
            shutil.copy(RECORDS / f, ws)
    call(agent_for("scout"), "scout.md", ws, task=topic or "Use the topics in CONTEXT.md.")
    added = []
    for p in sorted((ws / "out").glob("*.md")):
        if (RECORDS / "ideas" / p.name).exists():
            print(f"  skip {p.name}: already in the records")
            continue
        shutil.copy(p, RECORDS / "ideas" / p.name)
        added.append(p.stem)
    rebuild()
    commit(f"scout: {len(added)} ideas")
    print(f"added {len(added)} ideas: {', '.join(added)}")
    return added


def canary(n: int = 1, roles=("scout", "novelty2")) -> None:
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
            for agent, res in novelty(RUNS / f"{now()}-canary-{p.stem}", blind, roles).items():
                w.writerow([now("%Y-%m-%d"), p.stem, agent, res["verdict"], res["verdict"] == "exists", res.get("confidence")])
                print(f"  {p.stem} / {agent}: {res['verdict']}")
    commit(f"canary x{n}")


def calibration() -> None:
    rows = list(csv.DictReader(open(RECORDS / "calibration.csv", encoding="utf-8")))
    for agent in sorted({r["agent"] for r in rows}):
        mine = [r for r in rows if r["agent"] == agent]
        print(f"{agent}: caught {sum(r['caught'] == 'True' for r in mine)}/{len(mine)} canaries")


def untested() -> list[str]:
    """Ideas with status 'idea' and no run yet, oldest first."""
    ideas = [p for p in (RECORDS / "ideas").glob("*.md") if re.search(r"^status: idea$", p.read_text(encoding="utf-8"), re.M)]
    ideas = [p for p in ideas if "run `" not in p.read_text(encoding="utf-8")]
    return [p.stem for p in sorted(ideas, key=lambda p: p.stat().st_mtime)]


def auto(cycles: int, topic: str) -> None:
    for c in range(1, cycles + 1):
        print(f"=== cycle {c}/{cycles}")
        if c % 3 == 0:
            canary(1)
        queue = untested()
        if len(queue) < 2:
            scout(topic)
            queue = untested()
        if not queue:
            print("Nothing to test. Stopping.")
            return
        try:
            run_idea(queue[0])
        except SystemExit as e:  # one failed run must not stop the night; it is logged and the idea is parked
            print(f"  run failed: {e}")
            failed = RUNS / f"{now()}-{queue[0]}-error"
            failed.mkdir(parents=True, exist_ok=True)
            record(queue[0], failed, {"verdict": "error", "lessons": f"Run error: {e}"})
            set_status(queue[0], "parked")


def set_status(idea_id: str, status: str) -> None:
    path = RECORDS / "ideas" / f"{idea_id}.md"
    path.write_text(re.sub(r"^status: .*$", f"status: {status}", path.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")


def init() -> None:
    for d in ("ideas", "runs"):
        (RECORDS / d).mkdir(parents=True, exist_ok=True)
    for name in ("TEMPLATE.md", "CONTEXT.md"):
        if not (RECORDS / name).exists():
            shutil.copy(HERE / "templates" / name, RECORDS / name)
    rebuild()
    print(f"Records folder ready: {RECORDS}. Edit CONTEXT.md first.")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"init": init, "scout": lambda: scout(" ".join(args)), "run": lambda: run_idea(args[0]),
     "canary": lambda: canary(int(args[0]) if args else 1), "calibration": calibration,
     "auto": lambda: auto(int(args[0]) if args else 3, " ".join(args[1:]))}.get(cmd, lambda: print(__doc__))()
