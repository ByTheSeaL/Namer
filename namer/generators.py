"""Local, offline name generators.

Everything here runs instantly with no network: keyword extraction,
portmanteaus, affix mashing, and context-appropriate casing.
"""

import itertools
import random
import re

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "for", "to", "in", "on", "at", "by", "with", "from", "and",
    "or", "but", "not", "it", "its", "this", "that", "these", "those",
    "i", "we", "you", "he", "she", "they", "my", "our", "your", "their",
    "want", "need", "like", "something", "thing", "some", "which", "will",
    "can", "could", "should", "would", "as", "if", "so", "do", "does",
    "have", "has", "had", "about", "into", "than", "then", "very", "really",
}

PREFIXES = ["neo", "meta", "omni", "poly", "uni", "hyper", "micro", "auto", "syn"]
SUFFIXES = ["ify", "ly", "io", "eon", "ora", "ium", "ex", "ette", "arium", "scape"]

# name -> (word_joiner, capitalization function)
CONTEXTS = ("Code", "Fiction", "Paper / Technical", "Product / Project", "General")


def extract_keywords(description: str) -> list[str]:
    """Pull the meaningful words out of a free-text description."""
    words = re.findall(r"[a-zA-Z]{3,}", description.lower())
    seen: list[str] = []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen


def portmanteau(a: str, b: str) -> str | None:
    """Merge two words on an overlapping letter sequence, or at syllable-ish cut points."""
    a, b = a.lower(), b.lower()
    if a == b:
        return None
    # Prefer a real overlap (end of a == start of b), longest first
    for size in range(min(len(a), len(b)) - 1, 1, -1):
        if a.endswith(b[:size]):
            return a + b[size:]
    # Fallback: front of a + back of b, cut near vowel boundaries
    cut_a = max(2, len(a) * 2 // 3)
    cut_b = min(len(b) - 2, len(b) // 3)
    blend = a[:cut_a] + b[cut_b:]
    return blend if 4 <= len(blend) <= 14 else None


def _case_for_context(name_words: list[str], context: str) -> str:
    if context == "Code":
        # Alternate between camelCase and snake_case for variety
        if random.random() < 0.5:
            return name_words[0] + "".join(w.title() for w in name_words[1:])
        return "_".join(name_words)
    if context in ("Fiction", "Product / Project"):
        return "".join(w.title() for w in name_words)
    if context == "Paper / Technical":
        return "-".join(w.upper() if len(w) <= 4 else w.title() for w in name_words[:1]) + (
            "" if len(name_words) == 1 else " " + " ".join(w.title() for w in name_words[1:])
        )
    return " ".join(w.title() for w in name_words)


def generate(keywords: list[str], context: str, extra_words: list[str] | None = None,
             limit: int = 24) -> list[tuple[str, str]]:
    """Generate (name, rationale) pairs from keywords plus optional associated words.

    extra_words are association results (e.g. from Datamuse) mixed in as raw material.
    """
    pool = list(keywords)
    if extra_words:
        pool.extend(w for w in extra_words if w not in pool)
    pool = [w for w in pool if w.isalpha()][:14]
    if not pool:
        return []

    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: str, why: str):
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            results.append((name, why))

    pairs = list(itertools.permutations(pool, 2))
    random.shuffle(pairs)

    for a, b in pairs:
        if len(results) >= limit:
            break
        style = random.random()
        if style < 0.4:
            blend = portmanteau(a, b)
            if blend:
                add(blend.title(), f"portmanteau of “{a}” + “{b}”")
        elif style < 0.8:
            add(_case_for_context([a, b], context), f"“{a}” + “{b}”")
        else:
            if random.random() < 0.5:
                add((random.choice(PREFIXES) + a).title(), f"prefix + “{a}”")
            else:
                root = a[:-1] if a.endswith("e") else a
                add((root + random.choice(SUFFIXES)).title(), f"“{a}” + suffix")

    # Single-word plays if the pool is small
    for w in pool[:4]:
        if len(results) >= limit:
            break
        root = w[:-1] if w.endswith("e") else w
        add((root + random.choice(SUFFIXES)).title(), f"“{w}” + suffix")

    return results[:limit]
