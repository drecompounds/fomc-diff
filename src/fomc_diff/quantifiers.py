"""Graded hedge counts from FOMC minutes.

Order matters: the alternation is leftmost-first, so 'almost all' must precede
'all' or every 'almost all participants' silently also books an 'all'.
"""
from __future__ import annotations

import re
from collections import Counter

QUANTIFIERS = (
    "almost all",
    "a number of",
    "a couple of",
    "a few",
    "all",
    "most",
    "many",
    "several",
    "some",
)

_PATTERN = re.compile(
    r"\b(" + "|".join(q.replace(" ", r"\s+") for q in QUANTIFIERS) + r")\s+"
    r"(participants|members)\b",
    re.I,
)


def count_quantifiers(text: str) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    for m in _PATTERN.finditer(text):
        quant = re.sub(r"\s+", " ", m.group(1).lower())
        population = m.group(2).lower()
        counts[(population, quant)] += 1
    return dict(counts)
