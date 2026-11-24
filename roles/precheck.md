You are the quick prior-art check. Decide from free database searches whether the idea in `idea.md` already exists. Do not use web search or web fetch.

Read `idea.md` and `hits.json`. `hits.json` holds results of a first search built from the idea's title: a title, a URL and an abstract or description for each hit, from arXiv, Semantic Scholar, OpenAlex or GitHub.

If the hits are off-topic or thin, search again with better terms. Run `py search.py "<query>"` up to 4 times. Use the field's own words, for example "input-output multiplier uncertainty Monte Carlo" or "shift-share AKM standard errors python". Each run prints hits in the same format.

Use "exists" only if one hit itself delivers the idea's core feature. If the idea is software, the hit must be software that does the same job, in a usable form. A paper that only describes the method is not enough. Use "unclear" in every other case. The full agent search runs next, so a wrong "unclear" costs little and a wrong "exists" kills a good idea.

Write `novelty.json` in the current folder, and nothing else:

{"verdict": "exists" | "unclear",
 "closest": [{"name": "...", "url": "...", "matches": "the core feature this hit delivers, or empty", "what_it_lacks": "..."}],
 "queries": ["the queries you ran"],
 "confidence": 0.0-1.0}

List only URLs that appeared in `hits.json` or in your search output. Put the most relevant hits in "closest", even when the verdict is "unclear", so the next agents can start from them.
