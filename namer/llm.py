"""LLM-backed name generation via OpenRouter.

OpenRouter exposes hundreds of models behind one OpenAI-compatible API,
so the user can pick whichever model they like from a dropdown.

Auth: set OPENROUTER_API_KEY in the environment, or put the key on the
first line of ~/.config/namer/openrouter_key. Uses only the standard
library — no extra packages needed.
"""

import json
import os
import re
import urllib.request
from pathlib import Path

API_BASE = "https://openrouter.ai/api/v1"
KEY_FILE = Path.home() / ".config" / "namer" / "openrouter_key"
TIMEOUT = 90

# Shown before (or if) the live model list loads. Any OpenRouter model id works.
FALLBACK_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
]

SYSTEM = """You are an expert namer. You generate name ideas for anything — code \
identifiers, fictional characters and places, technical paper titles, products, \
projects. Given a description and a context, produce distinctive, memorable, \
apt names. Avoid generic or overused patterns. Vary your approaches: metaphor, \
portmanteau, classical roots, sound symbolism, allusion.

Respond with ONLY a JSON object of the form:
{"names": [{"name": "...", "rationale": "..."}, ...]}"""

CONTEXT_GUIDANCE = {
    "Code": "Names are code identifiers. Follow programming conventions: offer a mix "
            "of camelCase, snake_case, and PascalCase as appropriate. Favor short, "
            "precise, unambiguous names a reviewer would approve of.",
    "Fiction": "Names for creative fiction: characters, places, factions, artifacts. "
               "Favor evocative sound and connotation over literal meaning. Consider "
               "etymology and how the name feels spoken aloud.",
    "Paper / Technical": "Names for papers, systems, algorithms, or datasets. Favor "
                         "pronounceable acronyms, classical roots, and names that hint "
                         "at the method. Think BERT, RAFT, Paxos.",
    "Product / Project": "Product or project names. Favor short, brandable, spellable "
                         "names. Flag any that are likely trademark-crowded.",
    "General": "General-purpose naming. Offer a diverse spread of styles.",
}


def get_api_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text().strip().splitlines()[0]
    except (OSError, IndexError):
        return None


def is_available() -> tuple[bool, str]:
    if get_api_key():
        return True, ""
    return False, (f"No OpenRouter key found. Set OPENROUTER_API_KEY, or put your "
                   f"key in {KEY_FILE}. Get one at openrouter.ai/keys.")


def _request(path: str, payload: dict | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/namer-app",
        "X-Title": "Namer",
    }
    key = get_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def list_models() -> list[str]:
    """Fetch available model ids from OpenRouter (no auth required)."""
    try:
        data = _request("/models")
        ids = [m["id"] for m in data.get("data", [])]
        return sorted(ids) or FALLBACK_MODELS
    except Exception:
        return FALLBACK_MODELS


def suggest(description: str, context: str, model: str,
            seed_words: list[str] | None = None, count: int = 12) -> list[tuple[str, str]]:
    """Return (name, rationale) pairs from the chosen model. Raises on API errors."""
    seed_note = ""
    if seed_words:
        seed_note = ("\n\nWord-association research turned up these related words — "
                     "use any that spark good ideas, ignore the rest: "
                     + ", ".join(seed_words[:20]))

    prompt = (
        f"Context: {context}. {CONTEXT_GUIDANCE.get(context, '')}\n\n"
        f"Thing to name: {description}{seed_note}\n\n"
        f"Give {count} name ideas."
    )

    data = _request("/chat/completions", {
        "model": model,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    })
    text = data["choices"][0]["message"]["content"]

    # Models sometimes wrap JSON in markdown fences or prose — extract the object.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Model returned no JSON: {text[:200]}")
    parsed = json.loads(match.group(0))
    return [(item["name"], item.get("rationale", "")) for item in parsed["names"]]
