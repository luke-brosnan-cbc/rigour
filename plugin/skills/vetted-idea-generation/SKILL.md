---
name: "vetted-idea-generation"
description: "Use when asked for project, research, repo, package or side-project ideas. Generates many candidates, tries to kill each with prior-art searches, and presents only survivors."
---

# Vetted idea generation

Goal: never pitch an idea that turns out to be already done. The user should only ever see ideas that survived a real attempt to kill them.

## Rules

- Do not show any idea before it has passed the kill check below.
- Never say "this is narrower than I thought" later. Settle novelty before presenting.
- If an idea fails, drop it. Do not pitch it with caveats.
- If too few survive, generate more and check again. Do not stop at "no ideas".
- Minimum survivors: keep running rounds until at least 1 idea survives for each role or area the user asked for (or the number they asked for). Budget: up to 6 rounds. Only report "none survived" after the budget is spent, and then report what was tried and the next strategy.
- Change strategy between rounds. Do not keep generating the same kind of idea. If round 1 used generic combinations, round 2 must use an "unfair edge": data, domain knowledge or tooling that the crowded field (e.g. ML researchers) does not have or does not use.
- Do not build novelty on one new preprint the user would just implement or extend. Those are the ideas most likely to be done already.

## Step 1: Generate wide (do not show the user)

Write 15-25 candidates. Use these sources of novelty, not just recall of recent papers:
- Combinations: a mature method from field A with a dataset or problem from field B; two well-known tools joined into something new.
- Unresolved known problems: long-open GitHub issues with many reactions, recurring practitioner complaints, limitations stated in widely cited papers.
- Data: a public source not yet used for this question, or a useful dataset that does not exist in clean form. A clean dataset alone is rarely enough. It needs a question or tool on top.
- Ports: methods that exist in R, Stata or Matlab but not in Python, but only after checking the Python gap.

### Edge sources to use in later rounds
- Niche or awkward data: new regulatory releases, official statistics, policy changes with a clear date (natural experiments).
- Domain methods unknown in the target field: econometrics, survey statistics, official-statistics practice, index-number theory applied to ML, or the reverse.
- Neglected tooling: methods that only exist in R, Stata, Matlab or Java in a niche ML researchers ignore.
- Fields that move fast (LLMs, AI research) need more rounds and fresher searches (last 3-6 months). Prefer ideas whose edge does not depend on speed.

## Step 2: Kill check (for every candidate)

Aim to kill the idea. Use at least 3 phrasings and synonyms per idea. Search:
- Papers: arXiv, Semantic Scholar or OpenAlex, Google Scholar, SSRN, NBER, RePEc/IDEAS, central bank working papers.
- Code: GitHub (repos and code search), PyPI, CRAN, Hugging Face, Kaggle notebooks and datasets.
- Products: commercial tools, data vendors, Product Hunt.
- Blogs and Substack.
Check the last 12 months with extra care.

Kill the idea if a public paper, repo, package, dataset or product already does the core thing, even if it is less polished.

## Step 3: Present survivors only

For each survivor:
- Name and a plain one-paragraph description.
- Type of novelty (combination, unresolved problem, data, port).
- Closest things found, with links, and exactly what each one lacks.
- Kill log: main queries and places searched.
- Roles it signals for, data needed (free or paid), minimum version in weekends, stretch goals, deliverable, main risks.

You may list killed ideas in one line each with the reason, so the user knows what to avoid.

Write in plain, direct English with short sentences.