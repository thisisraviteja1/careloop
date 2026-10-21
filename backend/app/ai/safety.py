"""Output checks applied to every piece of model text before anyone sees it.

Per the Ring Computer Vision Guidelines, model output is never treated as ground truth,
every text output is checked against a keyword block list, and a deterministic fallback is
used whenever a check fails.
"""

from __future__ import annotations

import re

# Words alerts must never use (CLAUDE.md "Alert message rules").
FORBIDDEN_WORDS = ("fall", "fallen", "falls", "fell", "emergency", "unconscious", "collapsed",
                   "injured", "injury", "dead", "death", "died", "hurt")
# Further block-list terms: medical speculation and alarming language.
BLOCKLIST = ("ambulance", "hospital", "medical", "stroke", "heart attack", "blood", "bleeding",
             "accident", "danger", "dangerous", "urgent", "panic", "motionless")

_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in FORBIDDEN_WORDS + BLOCKLIST)
                      + r")\b", re.IGNORECASE)


def blocked_terms(text: str) -> list[str]:
    """Block-listed words found in `text` (case-insensitive, whole words)."""
    return sorted({m.group(1).lower() for m in _PATTERN.finditer(text)})


def word_count(text: str) -> int:
    return len(text.split())
