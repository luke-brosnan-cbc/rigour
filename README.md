<p align="center"><img src="docs/logo.svg" alt="rigour" width="300"></p>

<p align="center"><b>An overnight research loop that tries to kill your ideas before you build them.</b></p>

rigour runs on the Claude Code and Codex CLIs, on the subscriptions you already pay for. It scouts ideas, checks each one against papers, code and products, and builds a small MVP of the survivors. A separate referee then judges each build against tests it wrote and sealed before the build started. Every verdict, test and lesson lands in your own records repo, so the next night starts smarter than the last.

<p align="center"><img src="docs/pipeline.svg" alt="Scout, novelty checks, triage, referee writes sealed tests, builder, referee judges, records repo feeding the next scout" width="900"></p>

## It checks its own judges

A 2026 survey of AI-scientist systems found that 38% run a novelty check and none tests if that check works ([arXiv 2608.05179](https://arxiv.org/abs/2608.05179)). rigour tests it. It plants ideas that already exist, known as canaries, and records how often each agent catches them. You get a catch rate per model, not a promise.

The agents cannot mark their own homework. Each role is a fresh, isolated session. The builder never sees the tests, cannot leave its folder, and a hash stops the run if anyone changes the tests.

## It spends where it counts

Search APIs are free and agents are not. Before any agent searches the web, rigour queries arXiv, Semantic Scholar and GitHub directly, and a small model reads the results. An obvious match ends the check for a fraction of a cent. A word-overlap filter drops duplicate ideas with no model at all, and a quick triage stops ideas that a build would not teach anything about. The expensive hour of building only goes to ideas that earn it.

## Your research stays yours

rigour is only the engine. Your goals, tracks, settings and results live in a records repo that you own: a local folder or a private GitHub repo. Split your interests into tracks, such as work and side projects, and run each one on its own. Everything is plain Markdown, so you, other tools and other models can read it.

## Get started

You need [Claude Code](https://code.claude.com). [Codex](https://github.com/openai/codex) is optional and adds a second model family for more independent checks. Clone the repo, tell it where your records live, and run:

```
py loop.py init
py loop.py auto 3
```

The **[guide](docs/GUIDE.md)** covers setup, settings, tracks, scheduling, budgets and every command.

## Credits

rigour borrows ideas, not code, from [AI Scientist](https://www.nature.com/articles/s41586-026-10265-5) (cheap similarity checks before costly work), [AI-Researcher](https://github.com/NoviScl/AI-Researcher) (LLM-free deduplication), [TrustResearcher](https://arxiv.org/abs/2510.20844), [claudexor](https://github.com/razzant/claudexor), [omc-codex](https://github.com/jhcdev/omc-codex), [cross-review](https://github.com/lploc94/cross-review), [agentmemory](https://github.com/rohitg00/agentmemory) and [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Tools like [CORAL](https://github.com/Human-Agent-Society/CORAL) and [helix](https://github.com/VectorInstitute/helix) optimise a metric you choose. rigour works one level up: it decides which ideas are new and worth a metric at all.

MIT licence.
