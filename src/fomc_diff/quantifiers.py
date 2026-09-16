"""Graded hedge counts from FOMC minutes.

The substring trap and the guard: in "Almost all participants agreed",
the word boundary \b prevents "all" from matching at the inner offset because
it would start in the middle of "Almost". But if "almost all" is removed from
the tuple, no quantifier matches at offset 0, so finditer advances and \ball\b
then matches at offset 7, booking a spurious ("participants", "all").

The invariant: "almost all" must exist as a tuple entry, or the phrase silently
also counts toward bare "all". Word boundaries provide the overlap prevention;
deletion detection requires the entry to be present.
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


def _build_pattern(quantifiers: tuple[str, ...]) -> re.Pattern[str]:
    """Build the regex pattern from a quantifiers tuple."""
    return re.compile(
        r"\b(" + "|".join(q.replace(" ", r"\s+") for q in quantifiers) + r")\s+"
        r"(participants|members)\b",
        re.I,
    )


_PATTERN = _build_pattern(QUANTIFIERS)


def count_quantifiers(text: str) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    for m in _PATTERN.finditer(text):
        quant = re.sub(r"\s+", " ", m.group(1).lower())
        population = m.group(2).lower()
        counts[(population, quant)] += 1
    return dict(counts)
