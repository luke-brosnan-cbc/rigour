# rigour

**An overnight research loop that tries to kill your ideas before you build them.**

rigour runs on the Claude Code and Codex CLIs, on the subscriptions you already pay for. It scouts ideas, sends two independent agents to hunt for prior art, and builds a small MVP of each survivor. A separate referee then judges the build against tests it wrote and sealed before the build started. Every verdict, test and lesson lands in a records repo of plain Markdown, so the next night starts smarter than the last.

It also tests its own judges. It plants ideas that already exist and measures how often each agent catches them.

<p align="center"><img src="docs/pipeline.svg" alt="Scout, novelty checks, triage, referee writes sealed tests, builder, referee judges, records repo feeding the next scout" width="900"></p>

## Why it exists

A 2026 survey of AI-scientist systems found that 38% run a novelty check and none tests whether that check works ([arXiv 2608.05179](https://arxiv.org/abs/2608.05179)). rigour measures it. Canary ideas give each novelty agent a catch rate, and `py loop.py calibration` prints it.

The rest of the design keeps the agents honest. Each role is a fresh, isolated session with none of your own CLAUDE.md, memory or plugins. Agents hand off through files, never chat. The builder never sees the tests, its file tools cannot leave its folder, and a hash stops the run if anyone changes the tests.

## Quick start

You need [Claude Code](https://code.claude.com), logged in. [Codex](https://github.com/openai/codex) is optional and adds a second model family for more independent checks.

```
git clone https://github.com/luke-brosnan-cbc/rigour
cd rigour
```

Create `config.json` with one line that says where your records live:

```json
{ "records": "~/research-records" }
```

Then:

```
py loop.py init        # create the records folder, then edit its CONTEXT.md
py loop.py auto 3      # three cycles, then a session report
```

On macOS and Linux, use `python3` in place of `py`. The **[guide](docs/GUIDE.md)** covers everything else: second accounts, Codex, every setting, tracks, scheduling, budgets and canaries.

## Your records, your settings

`records` can point to a local folder or a git repo. Give it `gh:you/my-research` or any git URL, and rigour clones it to `~/.rigour/` and pulls before each run. After each run it commits and pushes the results.

Keep your personal setup in the records repo, not in rigour. A `rigour.json` there overrides the defaults in [`config.example.json`](config.example.json): which account and model plays each role, effort levels, budgets and tracks. The local `config.json` stays one line, and the same setup follows you to any machine.

`CONTEXT.md` in the records repo tells the agents what to look for. Split it into tracks with `## Track: <name>` sections and start a run with the track name, for example `py loop.py night 120 work`. Tracks listed in `adoption_tracks` judge ideas on practical value for a team instead of novelty.

## Running it

```
py loop.py night 120 [track] [topic]   # start new work for 120 minutes
py loop.py auto 5 [track] [topic]      # run 5 cycles
py loop.py scout [track] [topic]       # only generate and vet ideas
py loop.py run <idea-id>               # test one idea end to end
py loop.py schedule 01:00 120          # every night at 01:00
py loop.py usage now                   # live 5-hour and weekly usage per account
```

The expensive part of a run is the referee and the builder, so rigour spends as little as possible before them. A word-overlap check with no LLM drops near-duplicate ideas as the scout returns them. The scout keeps at most `scout_survivors` ideas (default 3). Adoption tracks skip the novelty stage because it would not decide anything there. Then one Haiku call, the triage, reads each idea and decides whether a build would teach anything new. A typical triage costs about $0.002.

A cycle tests the oldest untested idea and scouts more when fewer than two are waiting. Every third cycle runs a canary. If an account reports that it hit its usage limit, the session stops cleanly, and the idea in progress goes first next time. `metrics.csv` logs the cost, tokens and time of every call. You can set budget caps in USD or in subscription percentage.

## What a records repo holds

| Path | Contents |
|---|---|
| `CONTEXT.md` | Goals, tracks, your edge and the rules |
| `rigour.json` | Your settings (optional) |
| `ideas/<id>.md` | One idea: status, problem, prior art, dated progress, lessons |
| `runs/` | Novelty verdicts, sealed tests, the MVP and the referee's verdict |
| `DIGEST.md`, `INDEX.md`, `graph.json` | One line per idea, ideas by status, links between ideas |
| `journal/` | One report per session |
| `metrics.csv`, `calibration.csv` | Cost per call, canary catch rates |

Agents never get the whole history. A local BM25 index (`records.py`, no LLM) gives each one the five most relevant earlier records. Dropped ideas teach later runs without inflating the context.

## Limits

- Use free, public data only. Never give the loop credentials or licensed data.
- The builder can run Python, and Python can read any file. Run rigour where that is acceptable, or in a container.
- Codex's sandbox limits writes, not reads, so use Codex as a referee, not a builder.
- Canaries measure missed prior art, not false alarms on new ideas.
- Scripted `claude -p` use is allowed on your own account. Check your plan's current terms, and do not share accounts.

## Credits

rigour borrows ideas, not code, from [AI Scientist](https://www.nature.com/articles/s41586-026-10265-5) (cheap similarity checks before costly work), [AI-Researcher](https://github.com/NoviScl/AI-Researcher) (LLM-free deduplication before the novelty check), [TrustResearcher](https://arxiv.org/abs/2510.20844), [claudexor](https://github.com/razzant/claudexor), [omc-codex](https://github.com/jhcdev/omc-codex), [cross-review](https://github.com/lploc94/cross-review), [agentmemory](https://github.com/rohitg00/agentmemory) and [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Tools like [CORAL](https://github.com/Human-Agent-Society/CORAL) and [helix](https://github.com/VectorInstitute/helix) optimise a metric you choose. rigour works one level up: it decides which ideas are new and worth a metric at all.

MIT licence.
