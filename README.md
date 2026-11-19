# rigour

An autonomous research loop that runs on the Claude Code and Codex command-line tools, on the subscriptions you already have. It finds ideas, tries to kill each one with a prior-art search, and tests the survivors with a small build. A different agent then judges the build against tests it wrote before the build started. Every result goes into a records folder of plain Markdown and JSON, so later sessions (and other LLMs) can read, combine and build on it.

The loop also tests its own judges. It plants ideas that are known to exist (canaries) and measures how often each agent catches them.

## Why another research agent

Research agents and Claude/Codex orchestrators already exist. This project uses their ideas and credits them below. The gap it fills: a 2026 survey of AI-scientist systems found that 38% run a novelty check, and none tests whether that check is reliable ([arXiv 2608.05179](https://arxiv.org/abs/2608.05179)). This loop measures that reliability directly, with these checks:

- **Canaries.** `loop.py canary` takes an idea that the records already mark as existing, removes its prior art and lessons, and asks each novelty agent about it. `loop.py calibration` prints the catch rate per agent and model.
- **Two independent novelty checks.** Two agents search for prior art in separate fresh sessions. If they disagree, a stronger model breaks the tie.
- **Sealed tests.** The referee writes the criteria and the tests before the build. The builder sees the criteria only. The tests sit outside the builder's folder, the builder's file tools cannot leave its folder, and a hash stops the run if the tests change.
- **Isolated agents.** Every call is a fresh session with `--safe-mode` (no CLAUDE.md, memory, hooks or plugins from your own setup) and `--restricted` (file tools stay in the working folder). Agents pass results as files, never through chat. The loop refuses to run if the referee and the builder are the same agent.

## How a run works

1. **Scout** reads `CONTEXT.md`, the one-line-per-idea `DIGEST.md` and the earlier records that match the topic (`RELATED.md`), then generates ideas with the bundled `vetted-idea-generation` skill. Ideas that fail the prior-art search go in as `dropped`, with the evidence.
2. **Novelty**: two independent checks, and a tie-break only if they disagree.
3. **Referee** reads the related earlier records, then writes `criteria.md`, `holdout.md` and pytest tests. If earlier work already covers part of the idea, it tests only the new part.
4. **Builder** gets the criteria, the related records and copies of up to two related earlier MVPs to reuse. It builds the smallest version that meets the criteria and writes `REPORT.md`.
5. **Referee** checks the seal, runs its tests, reproduces the result and writes `verdict.json`.
6. **Record**: the loop appends a dated line to the idea, sets its status, rebuilds the index, digest, graph and search index, and commits the records repo.

## Sessions and scheduling

```
py loop.py night 60                 # run for 60 minutes, then synthesise
py loop.py auto 5                   # run 5 cycles, then synthesise
py loop.py schedule 01:00 60        # every night at 01:00, for 60 minutes
py loop.py unschedule
```

A session works like this:

1. **Orient.** Rebuild the digest and the search index. No LLM is used.
2. **Cycle** until the time is up. Run the scout if fewer than 2 ideas wait. Test the oldest untested idea. Run a canary every third cycle. A new idea starts only before the deadline. The idea in progress always finishes. A failed run parks its idea, and the session goes on.
3. **Synthesise.** One cheap-model call reads a script-built summary of the session (runs, canaries, cost against earlier sessions). It writes a journal entry, adds links between related ideas, and proposes at most 2 combined ideas.
4. **Commit and push** the records.

`schedule` uses Windows Task Scheduler (`schtasks`), or prints a cron line on macOS and Linux. The computer must be on, awake and logged in at that time. Output goes to `logs/night.log`.

You do not need to store logins. Claude Code keeps each account's login in its config folder (`~/.claude`, or `~/.claude-b` for the second account). Git keeps its own credentials (Windows Credential Manager or your OS keychain). Never put passwords or tokens in `config.json` or in the records.

## Cost and context

The design follows what current evidence says about agent cost:

- **One fresh session per stage**, with files as the handoff. Agent cost grows with the conversation history ([Trajectory Reduction, arXiv 2509.23586](https://arxiv.org/abs/2509.23586)), so no session carries another's history.
- **Retrieval, not the full history.** `records.py` builds a SQLite FTS5 (BM25) index with no LLM. Agents get the top 5 hits, capped at about 1,500 characters. BM25 beats grep on recall, and retrieval costs less than full-history prompts. Memory systems that need an LLM to build them get more expensive as they grow ([arXiv 2606.06448](https://arxiv.org/abs/2606.06448)). The digest is built by script for the same reason. LLM summaries lose detail.
- **Model routing by role.** Strong models where a mistake is expensive (scout, referee, tie-break), mid-tier models for tool-heavy work (novelty search, builder), and a cheap model for synthesis. Cost per task matters more than cost per token. A cheap model that fails and retries costs more.
- **Escalation only on disagreement.** The tie-break model runs only when the two novelty checks disagree.
- **`--safe-mode`** cut the fixed overhead per call by about 60% in our test (about 10k instead of 25k cached tokens). Your skills, plugins and CLAUDE.md are not loaded.

`metrics.csv` logs every call: role, agent, model, cost (USD-equivalent), tokens (with cache), web searches and seconds. Use it to compare sessions and to tune the role models in `config.json`.

## Setup

1. Install [Claude Code](https://code.claude.com) and log in.
2. Optional, a second Claude account for the referee. In PowerShell:
   ```
   $env:CLAUDE_CONFIG_DIR = "$HOME\.claude-b"
   claude
   ```
   Run `/login` with the second account, then exit. On macOS or Linux use `CLAUDE_CONFIG_DIR=~/.claude-b claude`. Without it, point the `claude-b` roles at `claude-a` in `config.json`. The builder and the referee must still be different agents, so use Codex or a second account for one of them.
3. Optional, Codex: `npm install -g @openai/codex`, then `codex login`. Set a role's agent to `codex` in `config.json`. If Codex is missing, those roles fall back to `claude-b`. The Codex call is not tested yet.
4. Copy `config.example.json` to `config.json`. Set `records` to the folder for your outputs, ideally a private git repo.
5. Run `py loop.py init`, then edit `CONTEXT.md` in the records folder.

### Several instances

You can run separate instances, for example one for personal research and one for work, each with its own records repo. Make a second config file with its own `records` and `task_name`. Then select it with the `RIGOUR_CONFIG` environment variable:

```
$env:RIGOUR_CONFIG = "C:\path\to\config-work.json"
py loop.py schedule 02:00 60
```

The scheduled task keeps its config. If a records folder links to repos on another host, add `links.json` to that folder, for example `{"gitea": "https://git.example.com/"}`. Then `gitea:owner/name` links pass the checks.

## Commands

```
py loop.py scout "nowcasting regional activity with free data"
py loop.py run <idea-id>
py loop.py canary 3
py loop.py calibration
py loop.py synthesise
py records.py search <records-folder> "<query>"
```

## Records layout

| Path | What it holds |
|---|---|
| `CONTEXT.md` | Goals, topics, your edge and the rules. The scout and the referee read it. |
| `ideas/<id>.md` | One idea: front matter (status, problems, links), then problem, idea, prior art, progress, lessons |
| `DIGEST.md` | One line per idea, built by script. The cheapest way for an agent to see the whole state. |
| `INDEX.md`, `graph.json` | Ideas by status, shared problems, and the links between ideas |
| `runs/<date>-<id>/` | Each novelty verdict, the referee's sealed tests, the build, the verdict and `result.json` |
| `journal/<date>.md` | One synthesis entry per session |
| `metrics.csv` | One row per agent call: cost, tokens, web searches, time |
| `calibration.csv` | One row per canary per agent and model: caught or not |
| `search.sqlite` | The BM25 index. It is rebuilt every time, so it is not committed. |

## Credits and related work

This project borrows ideas, not code, from these projects:

- [AI Scientist](https://www.nature.com/articles/s41586-026-10265-5) (Sakana AI): idea, experiment and review loop. Its novelty filter and multi-reviewer meta-review.
- [TrustResearcher](https://arxiv.org/abs/2510.20844): separate novelty and soundness reviewers.
- [claudexor](https://github.com/razzant/claudexor) (MIT): control plane for many Claude and Codex subscriptions, with races and cross-family review. A good backend if you run on macOS or Linux with several accounts.
- [Ouroboros](https://github.com/razzant/ouroboros): a persistent, self-developing agent built on claudexor.
- [omc-codex](https://github.com/jhcdev/omc-codex) (Apache-2.0): blind TDD between Claude and Codex.
- [claude-codex-collab](https://github.com/AlessioZazzarini/claude-codex-collab) (MIT) and [cross-review](https://github.com/lploc94/cross-review) (MIT): Claude and Codex on subscriptions, reviewing each other.
- [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc): OpenAI's Codex plugin for Claude Code.
- [agentmemory](https://github.com/rohitg00/agentmemory): BM25 and vector retrieval benchmarks for agent memory.
- [ponytail](https://github.com/DietrichGebert/ponytail) and [ste80-humanizer](https://github.com/Dodaios/ste80-humanizer): skills that suit the builder and the write-ups.

## Rules and limits

- Builders use free, public data only. Never give the loop licensed or private data, or credentials.
- Anthropic allows `claude -p` in your own scripts. It does not allow third-party tools to use your subscription login. Scripted use may count against a separate monthly credit pool. Check the current terms for your plan. Use one account per person. Do not share or resell access.
- `--restricted` keeps the file tools in the working folder, but the builder can still run Python, and Python can open any file. Run the loop on a machine and account where that is acceptable, or in a container.
- Canaries so far are known-existing ideas only. They measure misses, not false alarms on new ideas.
- The Codex call and the scheduler are not tested yet.

## Licence

MIT. See `LICENSE`.
