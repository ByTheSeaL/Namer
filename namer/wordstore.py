"""Persistent store of uncommon words the user has typed, for autocomplete.

SQLite database at ~/.config/namer/words.sqlite3 (stdlib only). Words are
learned from descriptions when the user generates names; common words
(stopwords, short words) are excluded. Completion prefers frequently and
recently used words.
"""

import re
import sqlite3
import time
from pathlib import Path

from .constants import STOPWORDS

DB_PATH = Path.home() / ".config" / "namer" / "words.sqlite3"
MIN_WORD_LEN = 4
MIN_PREFIX_LEN = 2

# Frequent English words not in the description-keyword stopword list but
# too common to be useful completions.
COMMON = STOPWORDS | {
    "when", "where", "what", "there", "here", "them", "then", "they",
    "just", "also", "only", "make", "makes", "made", "gets", "goes",
    "each", "every", "other", "another", "more", "most", "much", "many",
    "time", "times", "well", "good", "type", "kind", "sort", "part",
    "over", "under", "after", "before", "between", "through", "while",
}


class WordStore:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS words ("
            "  word TEXT PRIMARY KEY,"
            "  count INTEGER NOT NULL DEFAULT 1,"
            "  last_used REAL NOT NULL)")
        self._db.commit()

    def learn(self, text: str) -> int:
        """Record the uncommon words in text. Returns how many were stored."""
        words = {
            w for w in re.findall(r"[a-zA-Z]+", text.lower())
            if len(w) >= MIN_WORD_LEN and w not in COMMON
        }
        now = time.time()
        for w in words:
            self._db.execute(
                "INSERT INTO words (word, count, last_used) VALUES (?, 1, ?) "
                "ON CONFLICT(word) DO UPDATE SET count = count + 1, last_used = ?",
                (w, now, now))
        self._db.commit()
        return len(words)

    def complete(self, prefix: str) -> str | None:
        """Best completion for prefix: most used, then most recent."""
        prefix = prefix.lower()
        if len(prefix) < MIN_PREFIX_LEN:
            return None
        row = self._db.execute(
            "SELECT word FROM words WHERE word LIKE ? AND word != ? "
            "ORDER BY count DESC, last_used DESC LIMIT 1",
            (prefix + "%", prefix)).fetchone()
        return row[0] if row else None

    def close(self):
        self._db.close()
