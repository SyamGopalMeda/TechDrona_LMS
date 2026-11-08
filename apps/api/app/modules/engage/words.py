"""Word-cloud term normalisation and a basic profanity-safe filter.

``normalise_terms("  Large  Language-Model!! ", max_words=2)`` → ``["large language-model"]``.

* NFKC, lower case, punctuation stripped from both ends of every word (inner ``-``/``'``/``.``/
  ``+``/``#`` kept so ``c++``, ``c#``, ``gpt-4`` and ``node.js`` survive), whitespace collapsed;
* one submission is one term (a short phrase of at most ``max_words`` words, default 1; longer
  input keeps the first ``max_words`` words); comma-separated input yields up to ``max_words``
  separate terms instead;
* a term is at most 40 characters.

``is_blocked(term)`` is a deliberately small, conservative block list (whole-word match, with
common character substitutions undone). Blocked terms are stored (the participant's own answer)
but flagged ``filtered`` and never shown in a cloud or a count.
"""

from __future__ import annotations

import re
import unicodedata

MAX_TERM_LEN = 40
_EDGE = re.compile(r"^[^\w+#]+|[^\w+#]+$", re.UNICODE)
_SPACE = re.compile(r"\s+")
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"}
)

# Whole words only (after leet folding). Kept short on purpose: a basic safety net for a room
# display, not a moderation system. Presenters can still hide the cloud.
_BLOCKED = frozenset(
    {
        "fuck",
        "fucking",
        "fucker",
        "motherfucker",
        "shit",
        "bullshit",
        "bitch",
        "bastard",
        "asshole",
        "dick",
        "cunt",
        "slut",
        "whore",
        "nigger",
        "nigga",
        "faggot",
        "retard",
        "porn",
        "rape",
        "rapist",
        "chutiya",
        "madarchod",
        "bhenchod",
        "behenchod",
        "gandu",
        "randi",
        "bhosdike",
        "lavda",
        "lauda",
    }
)


def _clean_word(w: str) -> str:
    return _EDGE.sub("", w)


def _phrase(raw: str, max_words: int) -> str:
    words = [c for c in (_clean_word(w) for w in _SPACE.split(raw.strip())) if c]
    return " ".join(words[:max_words])[:MAX_TERM_LEN].strip()


def normalise_terms(raw: str, max_words: int | None = None) -> list[str]:
    n = max(1, min(int(max_words or 1), 5))
    text = unicodedata.normalize("NFKC", raw).lower()
    parts = [p for p in text.split(",")] if "," in text else [text]
    out: list[str] = []
    for p in parts:
        term = _phrase(p, n if len(parts) == 1 else 5)
        if term and term not in out:
            out.append(term)
        if len(out) >= n:
            break
    return out


def is_blocked(term: str) -> bool:
    folded = term.lower().translate(_LEET)
    words = re.findall(r"[a-z]+", folded)
    if any(w in _BLOCKED for w in words):
        return True
    squashed = re.sub(r"[^a-z]", "", folded)
    return squashed in _BLOCKED
