"""Cheap prior-art search: public APIs, no LLM. Each source returns hits as {source, title, url, text}.

    py search.py "lag-augmented local projections python"

Keys are optional and come from environment variables only: S2_API_KEY (Semantic Scholar),
OPENALEX_API_KEY (OpenAlex, which needs a key for more than a few calls a day) and GITHUB_TOKEN.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

STOP = set("a an and are as at be by for from in into is it of on or the to with without using via its this that "
           "python package tool tools library small new open".split())
AGENT = {"User-Agent": "rigour-prior-art-check"}


def keywords(text: str, n: int = 6) -> list[str]:
    """The first n content words of a title, in order."""
    seen = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+-]*", text):
        if w.lower() not in STOP and len(w) > 2 and w.lower() not in (s.lower() for s in seen):
            seen.append(w)
    return seen[:n]


def get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**AGENT, **(headers or {})})
    for wait in (2, 4, 8, 0):  # exponential backoff on 429, as the Semantic Scholar and arXiv terms ask
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or not wait:
                raise
            time.sleep(wait)


def narrowing(fetch, words: list[str], k: int, start: int) -> list[dict]:
    """AND-style search: drop keywords from the end until something matches, down to three."""
    for n in range(min(start, len(words)), 2, -1):  # stop at 3: two words match almost anything
        if hits := fetch(words[:n], k):
            return hits
    return []


def arxiv(words: list[str], k: int) -> list[dict]:
    q = " AND ".join(f"all:{w}" for w in words)
    xml = get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": q, "max_results": k}))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    return [{"source": "arxiv", "title": " ".join(e.findtext("a:title", "", ns).split()),
             "url": e.findtext("a:id", "", ns), "text": " ".join(e.findtext("a:summary", "", ns).split())}
            for e in ET.fromstring(xml).findall("a:entry", ns)]


def semantic_scholar(words: list[str], k: int) -> list[dict]:
    key = os.environ.get("S2_API_KEY")
    data = json.loads(get("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
        {"query": " ".join(words), "limit": k, "fields": "title,abstract,url,year"}), {"x-api-key": key} if key else None))
    return [{"source": "semantic_scholar", "title": p.get("title") or "", "url": p.get("url") or "",
             "text": p.get("abstract") or ""} for p in data.get("data") or []]


def openalex(words: list[str], k: int) -> list[dict]:
    params = {"search": " ".join(words), "per-page": k}
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    data = json.loads(get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    out = []
    for w in data.get("results") or []:
        inv = w.get("abstract_inverted_index") or {}  # OpenAlex stores abstracts as word -> positions
        text = " ".join(word for _, word in sorted((i, word) for word, pos in inv.items() for i in pos))
        out.append({"source": "openalex", "title": w.get("title") or "", "url": w.get("id") or "", "text": text})
    return out


def github(words: list[str], k: int) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    data = json.loads(get("https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": " ".join(words), "per_page": k, "sort": "stars"}),
        {"Authorization": f"Bearer {token}"} if token else None))
    return [{"source": "github", "title": r["full_name"], "url": r["html_url"],
             "text": f"{r.get('description') or ''} ({r.get('stargazers_count', 0)} stars, {r.get('language') or '?'})"}
            for r in data.get("items") or []]


SOURCES = {"arxiv": lambda w, k: narrowing(arxiv, w, k, 4), "semantic_scholar": semantic_scholar, "openalex": openalex,
           "github": lambda w, k: narrowing(github, w, k, 3)}


def search(query: str, sources: list[str] | None = None, k: int = 5) -> list[dict]:
    """Top k hits per source. A source that fails (rate limit, no network) is skipped, never fatal."""
    words, hits = keywords(query), []
    for name in ["arxiv", "semantic_scholar", "github"] if sources is None else sources:  # [] turns the search off
        try:
            hits += SOURCES[name](words, k)
        except Exception as e:  # noqa: BLE001  a cheap pre-check must not stop a run
            print(f"  prior-art search: {name} skipped ({type(e).__name__}: {e})", file=sys.stderr)
    for h in hits:
        h["text"] = h["text"][:600]
    return hits


if __name__ == "__main__":
    assert keywords("A Python package for shift-share (Bartik) regressions") == ["shift-share", "Bartik", "regressions"]
    for h in search(" ".join(sys.argv[1:]) or "lag-augmented local projections"):
        print(f"[{h['source']}] {h['title']}  {h['url']}\n    {h['text'][:300]}")
