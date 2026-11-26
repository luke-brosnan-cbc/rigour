# rigour v2: a memory that learns, and a loop that pursues its best ideas

Status: built on branch `v2` (2026-11-26). Written against rigour commit `0735217`.
Reader: the model that will build it. Read all of this file before you change any code.

## 0. Rules for the builder

1. Work in `C:\dev\rigour`. Make one branch per phase (`v2/0-stats`, `v2/1-predict`, and so on). Push each branch. Do not merge. The user merges.
2. Plain git commits. No `Co-Authored-By` lines and no "Generated with" lines.
3. Standard library only. Add no dependencies. Python 3.10.
4. Put new pure logic in one new file, `memory.py`. Give it a `_selftest()` that runs under `if __name__ == "__main__":`, the same way `records.py` does. Keep the agent calls and the run flow in `loop.py`.
5. Old records must still work. A missing new file (for example `frontier.jsonl`) means "behave as before".
6. Agents never edit memory files. An agent writes a proposal (a JSON list of operations) in its own run folder. Python checks each operation and applies only the valid ones. It logs the rejected ones in the run folder.
7. Add at most three lines to each role prompt per phase. Short prompts cost fewer tokens on every call.
8. Do not change `seal()`, the `.sealed/` folder, `check_independence()` or the builder's file limits. They keep the referee honest.
9. Ask the user before any paid run. Selftests and `py records.py <records>` cost nothing.
10. After each phase, update `docs/GUIDE.md` in its current style: short sentences, active voice, no dashes. Add a dated Progress line to `ideas/research-agent.md` in the records repo.

The records repo is `C:\dev\rigour-idea-log`. Run selftests with `py memory.py` and `py records.py C:\dev\rigour-idea-log`.

## 1. What is wrong today

| Gap | Where in the code | Effect |
|---|---|---|
| The loop never pursues a winner | `untested()` in `loop.py` picks the oldest idea with status `idea` and no run | A run that ends `works` sets status `prototype`, and nothing happens next. The referee's lessons often list exact next steps (see `runs/20261126-0935-forecast-round-commentary-copilot/result.json`). No code acts on them. |
| `partial` runs wait for a human | `resume()` runs only when the user types it | Half-built ideas stall. |
| Lessons stay inside one idea | `record()` appends lessons to the idea file only | A lesson such as "bind each number to its role" never reaches the next referee for a different idea. |
| The loop cannot tell if it gets smarter | Triage says yes or no, with no forecast | There is no prediction to score, so no calibration and no learning signal. |
| Memory only grows | `digest()` in `records.py` writes one line for every idea, dropped ones included | 22 of 49 ideas are dropped. Their lines go into every scout and synth prompt. |
| Retrieval follows only direct links | `related()` expands one hop over `helps`, `related`, `blocked_by` | Two ideas that share a problem or a data source never meet unless someone links them by hand. |
| A stuck call burns up to an hour, out of sight | `call()` uses `subprocess.run(..., timeout=60 * max_call_minutes)` with output captured until the end | Every role gets the same 60-minute limit. On a timeout, `TimeoutExpired` fires before `_<role>.log` and `log_metrics()` run, so the spend and the transcript are lost. On 2026-11-26 the builder for `earnings-call-antitrust-prescreen` downloaded a 1.8 GB parquet file into `mvp/_download/` and then stalled, and it left no log. `judge_mvp()` would also have copied that file into `judge/mvp`, and `commit()` would have tried to push it. |
| Combination is rare | `synth` runs only if `auto_synthesis` is true (default false), and writes at most 2 combined ideas | The scout mostly starts from zero. |

Spend so far (from `metrics.csv`): 23.3 USD-equivalent over 114 calls. The largest items are `referee_judge` on Opus (4.74), `builder` (3.16) and `scout` (3.16 on Sonnet plus 2.28 for one Opus call).

## 2. What we borrow, and what each idea becomes

You do not need to read these sources. The table says what to build.

| Source | The idea | In rigour |
|---|---|---|
| Complementary learning systems (McClelland, McNaughton and O'Reilly 1995; Kumaran, Hassabis and McClelland 2016) | The hippocampus stores episodes fast. The cortex slowly extracts general rules from replayed episodes, mostly during sleep. | Runs are episodes. A consolidation step at the end of each session turns them into short general claims in `knowledge.jsonl` (Phase 3). |
| Prioritized experience replay (Schaul et al. 2015). Dopamine reward prediction error (Schultz 1997). Predictive coding. | Learn most from the events that surprised you. | Triage predicts the outcome. After the run, surprise = actual minus predicted. Consolidation reads the most surprising runs first and skips the rest (Phases 1 and 3). This also saves tokens. |
| Multi-armed bandits, UCB1 (Auer et al. 2002) | Balance "use the best arm" against "try arms you know little about". | One score per next step decides between testing a new idea and advancing a good one (Phase 2). |
| Agentic tree search in AI Scientist v2 (Sakana 2025) | Expand the most promising node of a search tree. | Each advance step is a child of the run before it. Old sealed tests stay, so a child cannot lose what its parent achieved (Phase 2). |
| ACE, Agentic Context Engineering (2025). Dynamic Cheatsheet (2025). | Keep a playbook of lessons. Change it by small itemised edits, never by full rewrites, because full rewrites slowly lose detail. | Consolidation outputs operations (`add`, `support`, `contra`, `merge`, `retire`). Python applies them (Phase 3). |
| ACT-R base-level activation (Anderson). Ebbinghaus forgetting curve. MemoryBank (2023). | Memory strength grows with use and decays with time. Weak memories fade. | Each claim has a score from its support, its contradictions and its age. The weakest claims retire when the store is full (Phase 3). |
| Hebbian learning | Connections that fire together get stronger. | The referee reports which claims held and which failed in each run. Python updates their counts with no extra call (Phase 3). |
| A-MEM (2025), Zettelkasten | Notes link to each other and change when new notes arrive. | Synth proposes links and merges between ideas (Phase 4). |
| Pattern separation and pattern completion | Keep similar memories apart when they differ. Join them when they are the same. | The duplicate filter separates. `merge_ideas()` joins (Phase 4). |
| HippoRAG and HippoRAG 2 (2024, 2025), spreading activation (Collins and Loftus 1975) | Retrieve by spreading activation from seed nodes over a knowledge graph (personalized PageRank). | `related()` seeds PageRank with the BM25 hits and walks the graph through shared problems and data (Phase 4). |
| FunSearch (2023), AlphaEvolve (2025), MAP-Elites (Mouret and Clune 2015), AI co-scientist evolution agent (2025) | Keep the best solution in each niche. Make new candidates by mutating and crossing the elites. | Every second scout call gets parent ideas from the archive and must write one crossover, one mutation and one fresh idea (Phase 5). |
| Generative Agents reflection (2023), sleep-time compute (2025) | Spend cheap compute between tasks to reorganise memory. | Consolidation runs once per session on a cheap model, not inside each run. |

## 3. The design in one picture

```
            +------------------- knowledge.jsonl (claims) <------ consolidate (end of session)
            |                         ^                                  ^
            v                         | held / failed                    | most surprising runs first
  scout -> ideas -> frontier -> choose() -> run_idea or advance -> judge -> record -> predictions.csv
    ^                  ^                                             |
    |                  +---------------- next_steps -----------------+
    +---- elites (best idea per niche), merges, links <-- synth
```

Three new files appear in the records repo. All of them are text, and all of them are optional:

- `predictions.csv`: one row per triaged run, with the predicted and the actual reward.
- `frontier.jsonl`: open next steps for ideas that already have a run.
- `knowledge.jsonl`: general claims learned from runs. `records.py` renders it to `KNOWLEDGE.md` for people to read.

## Phase 0: measure first (branch `v2/0-stats`)

Goal: a number that says if a change made the loop better. Build this before anything else.

1. In `memory.py`, add `reward(verdict: dict) -> float | None`:
   - `works`: `high` 1.0, `medium` 0.7, `low` 0.4 (from `useful`, default `medium`).
   - `partial`: half of the `works` value.
   - `fails`: 0.1.
   - `exists`, `skip`, `untestable`, `review`: 0.0.
   - `error`: `None` (leave it out of every average).
2. In `loop.py`, add the command `py loop.py stats [days]` (default 30). It reads `metrics.csv`, `runs/*/result.json` and `calibration.csv` and prints one row per day:
   - runs by verdict, total reward, USD-equivalent, reward per USD,
   - canary catch rate,
   - ideas dropped as near-duplicates (count Progress lines that contain "near-duplicate"),
   - mean tokens per call for each role.
3. Add the command to the docstring at the top of `loop.py` and to the guide.

Done when: `py loop.py stats` runs on the current records, and the counts for 2026-11-24 match a count by hand of `runs/20261124-*/result.json`.

## Phase 0b: stop runaway calls (branch `v2/0b-limits`)

Goal: no step can spend more than its share of time or tokens, and every call leaves a log and a metrics row, even one that is killed. Build this right after Phase 0. It is the cheapest saving in this plan.

1. Per-role limits. Each role in `config.example.json` gets `minutes` and, for Claude agents, `max_usd`. Starting values:

   | Role | minutes | max_usd |
   |---|---|---|
   | precheck, triage, synth | 5 | 0.10 |
   | novelty1, novelty2, tiebreak | 15 | 0.60 |
   | scout | 20 | 1.00 |
   | referee_spec, referee_judge | 20 | 1.00 |
   | builder | 30 | 1.20 |

   `max_call_minutes` stays as the overall ceiling. A role with no value uses the ceiling. For Claude, pass `--max-budget-usd <max_usd>` (the flag is listed in `claude --help`). Codex has no such flag, so it gets the time limit only.
2. Stream, do not wait. In `call()`, replace `subprocess.run` with `subprocess.Popen`. Write stdout to `_<role>.log` line by line as it arrives. Keep the lines in a list for `parse_claude()`.
3. Two watchdogs in the read loop:
   - Wall clock: kill the process after the role's `minutes`.
   - Idle: kill it after 8 minutes with no new output line. A hung download or a hung install looks like this.
   On Windows, kill the whole process tree (`taskkill /T /F /PID <pid>`), because the CLI starts child processes.
4. After a kill, still parse what came in, still call `log_metrics()` with `error` set to `timeout` or `idle`, and then raise `SystemExit` with a short message. `session()` already turns that into an `error` record for the idea, so the night goes on.
5. Data limit. Add one line to `roles/builder.md`: "Download at most 200 MB in total. If a source is bigger, take a sample or a subset and say so in `REPORT.md`. Keep downloads in `_data/`." Add the same limit to `roles/referee-spec.md` for its own checks.
6. Do not copy big files. In `judge_mvp()` and in `related()` (the copy of earlier MVPs), skip `_data/`, `_download/`, `.venv/` and any file over 50 MB. The referee can still read the originals in the run folder.
7. Do not commit big files. `init()` writes these lines to the records `.gitignore`, and the builder adds them to the existing records repo once: `_data/`, `_download/`, `*.parquet`, and `runs/*/mvp/build/`. Before `commit()` runs `git add -A`, check the staged files and leave out any file over 50 MB, with a printed warning.
8. Repeat offenders. If the same role times out on the same idea twice, park the idea with the lesson "role X timed out twice". Do not retry it automatically.
9. `stats` (Phase 0) shows, for each role, the median and the maximum seconds, and the count of `timeout` and `idle` errors.

Done when: a selftest starts a child Python process that prints one line and then sleeps, and checks that the idle watchdog kills it and that the log file holds the printed line. Use limits of a few seconds in the test. A second check confirms that a 60 MB dummy file in an `mvp` folder is not copied into `judge/mvp`.

## Phase 1: predict, then score (branch `v2/1-predict`)

Goal: a learning signal. The loop must state what it expects before it spends money.

1. In `roles/triage.md`, extend the JSON to:
   `{"build": true|false, "reason": "...", "p_works": 0.0-1.0, "useful_if_works": "high"|"medium"|"low"}`.
   Add one line: "`p_works` is your probability that the referee will say `works`."
2. In `run_idea()`, after the triage call, keep `predicted = p_works * value(useful_if_works)`, with the values from `reward()`. Store it in the run folder as `prediction.json`.
3. In `record()`, if `prediction.json` exists in the run folder, append a row to `predictions.csv`: `date, run, idea, predicted, actual, surprise`. Surprise is `actual - predicted`. A run that triage stopped gets actual 0.0, because no build happened.
4. `stats` prints the mean absolute error and the Brier score of `p_works` (outcome 1 if the verdict is `works`) over the last 20 rows.

Done when: a selftest feeds three fake verdicts and predictions through the row writer and checks the surprise values. The scoring code must handle an empty `predictions.csv`.

## Phase 2: a frontier, and pursuit of the best ideas (branch `v2/2-pursue`)

Goal: the loop advances its best ideas step by step, and stops when they plateau. This is the main change.

### 2a. The referee proposes next steps

In `roles/referee-judge.md`, add a field to `verdict.json`:

```
"next_steps": [{"step": "one sentence: a result the next build must show, testable in under an hour",
                "kind": "deepen" | "repair",
                "size": "S" | "M"}]
```

At most 3 items. `repair` fixes a defect from this run. `deepen` takes the idea one milestone further. Write `[]` for `fails`.

### 2b. The frontier file

In `record()`, append each next step to `frontier.jsonl` with these fields: `id` (`<idea-id>#<n>`), `idea`, `run` (the run that proposed it), `kind`, `step`, `size`, `created`, `status` (`open`), `result_run` (empty), `reward` (empty).

When a step is used, set `status` to `done` and fill `result_run` and `reward`. Rewrite the whole file each time. It stays small.

Untested ideas are frontier items too, with `kind` `test`. Do not store them. Compute them with `untested()`.

### 2c. Choose the next item

In `memory.py`, add `choose(items, runs_by_idea, total_runs)`. It returns the item with the highest score:

```
score = base + EXPLORE * sqrt(ln(total_runs + 1) / (runs_on_idea + 1))
base  = TEST_BASE                                      for a test item
base  = latest_reward_of_idea * DECAY ** runs_on_idea   for a deepen or repair item
```

`runs_on_idea` counts every judged run of that idea, the first test run included.

Put the constants at the top of `memory.py`: `EXPLORE = 0.3`, `TEST_BASE = 0.45`, `DECAY = 0.85`. Do not make them settings yet. A repair item gets `+0.1` if its idea's last verdict was `partial`, because a partial build is close to done.

Worked example with 47 runs so far: an untested idea scores about 1.04. A `works` idea with high usefulness and one run scores about 1.27, so the loop advances it. A `partial` idea with medium usefulness scores about 0.81 with the repair bonus, so new ideas go first. Put these three cases in the selftest.

### 2d. Advance an idea

Generalise `resume()` into `advance(idea_id, step=None)`:

- Allow the last verdict to be `works` or `partial`.
- If `step` is given, use its text in the `referee_spec` and `builder` tasks in place of the fixed repair text. The referee writes `tests/test_step_<n>.py` for this step only.
- Keep every earlier sealed test. A step that breaks an earlier passing test cannot score `works`. This is the ratchet: a child run never loses what its parent proved.
- Keep `py loop.py resume <id>` as a name that calls `advance(id)`.

### 2e. Plug it into the session

In `session()`, replace `run_idea(queue[0])` with:

1. Build the item list: open frontier items for the track, plus the test items from `untested(track)`.
2. `item = choose(...)`.
3. A test item goes to `run_idea()`. Any other item goes to `advance()`. Mark the frontier item `done` with the new reward.
4. Limit each idea to `2` advance steps per session (a constant). This stops one idea from taking the whole night.
5. Plateau rule: if the last 2 advance runs on an idea did not raise its reward, close its open items with status `plateau`. Add the Progress line "plateau: ready for a human decision" to the idea file.

Keep the scout trigger as it is: scout when fewer than 2 untested ideas wait.

### 2f. Show it

In `records.py`, if `frontier.jsonl` exists, add a section "Open next steps" to `DIGEST.md` with the top 10 open items, one line each. The scout then sees what the loop is pursuing.

Done when: the selftest covers `choose()` with the three cases above, the plateau rule, and the per-session limit. A dry check builds the item list from the real records and prints it, with no agent call.

## Phase 3: consolidation into general knowledge (branch `v2/3-knowledge`)

Goal: lessons from one run reach every later run that needs them, in a small, fixed token budget.

### 3a. The claim store

One JSON object per line in `knowledge.jsonl`:

```
{"id": "k17", "role": "referee", "text": "at most 240 characters", "evidence": ["<run folder name>"],
 "support": 2, "contra": 0, "created": "2026-11-26", "seen": "2026-11-26", "status": "live"}
```

`role` is one of `scout`, `triage`, `referee`, `builder`, `novelty`, `all`. `status` is `live` or `retired`. A merged claim gets `status` `retired` and a field `merged_into`.

Score, in `memory.py`:

```
score = (support + 1) / (support + contra + 2) * 0.98 ** days_since_seen
```

The first factor is the mean of a Beta distribution. The second factor is a forgetting curve.

Capacity: at most 60 live claims. When an operation would make 61, retire the claim with the lowest score.

`records.build()` renders the live claims to `KNOWLEDGE.md`, grouped by role and sorted by score, so a person can read and edit them. Do not add `knowledge.jsonl` to the BM25 index. Claims reach agents only through 3c.

### 3b. Consolidate at the end of each session

Extend the existing `synth` role and `synthesise()`. Do not add a new call.

- Input: the current live claims, plus the runs since the last synthesis, sorted by absolute surprise from `predictions.csv`, largest first. Runs with no prediction come after them. Give the agent the `lessons` and `evidence` of at most 6 runs. This is prioritized replay, and it keeps the prompt small.
- Output: a new file `knowledge_ops.json` with a list of operations:

```
{"op": "add",     "role": "...", "text": "...", "evidence": ["<run>"]}
{"op": "support", "id": "k3", "evidence": ["<run>"]}
{"op": "contra",  "id": "k9", "evidence": ["<run>"]}
{"op": "merge",   "ids": ["k3", "k9"], "text": "one claim that replaces both"}
{"op": "retire",  "id": "k4", "why": "..."}
```

- Python checks each operation: ids exist, each evidence run folder exists, text has at most 240 characters, role is valid, at most 5 `add` operations per call. It applies the valid ones and writes the rejected ones to `knowledge_rejected.json` in the synth run folder. `support` and `contra` add 1 to the count and set `seen` to today.
- Prompt lines for `roles/synth.md`: a claim must be general (true for more than one idea), checkable, and cite a run. "Bind each number to its role in the sentence" is a good claim. "The copilot works" is not.
- Change the default of `auto_synthesis` to `true` in `config.example.json`. It is one cheap call per session.

### 3c. Give each role its claims

Add `knowledge_pack(ws, role, query)` in `loop.py`. It writes `KNOWLEDGE.md` into the agent's folder. The pack holds the live claims for that role and for `all`, ranked by `score * (1 + word overlap with the idea)`. Cap it at 8 claims and 1,200 characters. Show the claim id on each line.

Call it for `scout`, `triage`, `referee_spec` and `builder`. Add one line to each of those role prompts: "Read `KNOWLEDGE.md`: lessons from earlier runs, with ids. Follow them unless this idea gives a reason not to."

### 3d. Learn from use, at no extra cost

In `roles/referee-judge.md`, add a field to `verdict.json`:
`"claims": {"held": ["k3"], "failed": ["k9"]}`. The judge reads `mvp/KNOWLEDGE.md` and lists the claims that this run confirmed or contradicted.

In `judge_mvp()`, apply them as `support` and `contra` operations. Ignore unknown ids.

Done when: the selftest covers the score, the capacity limit, each operation type, and the rejection of bad operations. One real session (ask the user first) produces `knowledge.jsonl` with at least one claim that cites a run.

## Phase 4: graph memory, with merges and spreading activation (branch `v2/4-graph`)

### 4a. Smaller digest

In `records.digest()`, keep one full line for each idea with status `idea`, `exploring`, `prototype`, `in-use` or `parked`. Put all `dropped` ideas on one line: `Dropped (ids only): a, b, c`. The near-duplicate filter still compares new ideas against every file, and BM25 still finds dropped ideas, so the scout loses nothing it needs. This saves about 4,000 characters in every scout and synth prompt today, and more as the records grow.

### 4b. Merge ideas

Synth may write `merges.json`: `[{"keep": "<id>", "drop": "<id>", "why": "..."}]`.

`merge_ideas(keep, drop)` in `loop.py`:

1. Reject the merge if either idea has status `prototype` or `in-use`, or if the word overlap from `words()` is below 0.2.
2. Append the Problem, Idea and Prior art sections of `drop` to `keep`, under `## Merged from <drop>`.
3. Join the `problems`, `data`, `related` and `helps` lists into `keep`.
4. Set `drop` to status `dropped`, with the Progress line "merged into `<keep>`".
5. In every other idea file, replace links to `drop` with `keep`.

Then call `rebuild()` so `records.check()` catches a broken link.

### 4c. Spreading activation in retrieval

Replace the one-hop expansion in `related()` with personalized PageRank in `memory.py`:

- The graph is `graph.json`: idea, problem, data and repo nodes. Treat every edge as undirected with weight 1.
- Seeds: the idea ids found in the BM25 hits, with weight `1 / rank`, normalised to sum to 1.
- Run 20 iterations of `p = 0.5 * seeds + 0.5 * spread(p)`, where `spread` splits each node's value equally over its neighbours.
- Take the 5 highest-scoring idea nodes that are not in the hits, and add their digest lines as `- linked: ...`, as now.
- Keep the 1,500-character cap.

Selftest: in a toy graph, an idea that shares a problem with a seed must outrank an idea with no path to the seed.

Done when: selftests pass, and `records.check()` reports no broken links after a test merge on a copy of the records folder.

## Phase 5: evolve new ideas from the best ones (branch `v2/5-evolve`)

1. `elites()` in `memory.py`: for each niche `(track, first problem)`, the idea with the highest latest reward. Ideas with no run do not count.
2. Every second scout call becomes an evolve call. Count the `*-scout*` run folders to decide. The task gives 2 or 3 parent elites from different niches. Sample them with probability proportional to reward. Add their lessons and their open frontier items.
3. The evolve task asks for exactly: one crossover (combine two parents), one mutation (change one thing about one parent: its user, its data or its method), and one fresh idea. Each child lists its parents in `related`.
4. Children go through the same duplicate filter, novelty checks and triage as any idea.
5. `stats` compares the mean reward of evolved ideas (they have parents in `related` and come from an evolve run) with fresh ideas.

Rule for the user: after about 20 evolved ideas have runs, keep evolve mode only if their mean reward is at least that of fresh ideas.

## Not now

| Idea | Why not yet | Revisit when |
|---|---|---|
| Embeddings or a vector database | 49 ideas and 47 runs. BM25 plus PageRank covers this size with no dependency. | Over about 500 documents, or `stats` shows retrieval misses. |
| Hebbian weights on idea edges | No signal yet tells which retrieved idea helped a run. | Phase 3d data shows which claims matter. |
| LLM Elo tournaments between ideas (AI co-scientist) | Real verdicts are better evidence, and a tournament costs many calls. | The frontier has too many untested ideas to run. |
| Full Monte Carlo tree search | The bandit plus advance chains already gives depth. | Ideas branch into several rival next steps often. |
| Skip `novelty2` when `novelty1` finds a match | Canaries measure missed kills only. Nothing measures wrong kills of new ideas yet. | rigour has known-new canaries as well as known-old ones. |
| A Sonnet judge in place of Opus | The judge is the most expensive role, but no one has measured judge accuracy. | Judge canaries exist: planted MVPs with known defects. |
| Fine-tuning, agent debate, agents that edit memory directly | Cost and risk with no measured need. | Never, for the last one. |

## How to tell if it worked

Run `py loop.py stats` before Phase 1 and after about three sessions with Phases 1 to 3. Look for:

- higher reward per USD,
- at least 30% of runs are advance steps, and at least half of those raise their idea's reward,
- lower mean absolute error for triage predictions,
- no fall in the canary catch rate,
- fewer near-duplicate drops per scout call,
- fewer input tokens per scout call.

The sample is small (a few runs per night). Read the numbers as a direction, not as proof.

## Order and size

| Phase | Branch | Rough size | Depends on |
|---|---|---|---|
| 0 Stats | `v2/0-stats` | about 60 lines | none |
| 0b Limits | `v2/0b-limits` | about 80 lines and 2 prompt lines | 0 (for the stats part only) |
| 1 Predict | `v2/1-predict` | about 40 lines and 2 prompt lines | 0 |
| 2 Pursue | `v2/2-pursue` | about 150 lines and 4 prompt lines | 0, 1 |
| 3 Knowledge | `v2/3-knowledge` | about 150 lines and 6 prompt lines | 1 |
| 4 Graph | `v2/4-graph` | about 100 lines | none, but merge after 3 |
| 5 Evolve | `v2/5-evolve` | about 60 lines | 2 |

Phase 0b stops the waste on stuck steps. Phases 0 to 2 give the "pursue the best idea" behaviour. Phase 3 gives the learning memory. Stop after Phase 3 and measure before you build Phases 4 and 5.
