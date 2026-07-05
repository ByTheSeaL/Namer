"""Datamuse API client — free word-association source, no API key required.

https://www.datamuse.com/api/  (100k requests/day, no signup)
Uses only the standard library so the app stays dependency-free.
"""

import json
import urllib.parse
import urllib.request

BASE = "https://api.datamuse.com/words"
TIMEOUT = 6  # seconds — keep the UI snappy even if the network is down


def _query(params: dict) -> list[dict]:
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Namer/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def associations(keywords: list[str], max_per_query: int = 12) -> list[str]:
    """Return words associated with the given keywords, best first.

    Combines "means like" (semantic) and "triggered by" (statistical
    association) queries. Network errors return an empty list — callers
    treat Datamuse as a best-effort enrichment, never a hard dependency.
    """
    if not keywords:
        return []
    phrase = " ".join(keywords[:6])
    words: list[str] = []
    seen = set(k.lower() for k in keywords)

    queries = [
        {"ml": phrase, "max": max_per_query},                       # means like the phrase
        {"rel_trg": keywords[0], "max": max_per_query // 2},        # associated with top keyword
    ]
    if len(keywords) > 1:
        queries.append({"rel_trg": keywords[1], "max": max_per_query // 2})

    for params in queries:
        try:
            for item in _query(params):
                w = item.get("word", "")
                if w.isalpha() and len(w) >= 3 and w.lower() not in seen:
                    seen.add(w.lower())
                    words.append(w)
        except Exception:
            continue  # offline or rate-limited — fall back to local-only
    return words
