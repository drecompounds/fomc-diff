"""First/last appearance of tracked phrases across the corpus."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .parse import Paragraph


@dataclass(frozen=True)
class PhraseRow:
    phrase: str
    first_seen: str
    last_seen: str
    n_meetings: int


def phrase_index(by_date: dict[date, list[Paragraph]],
                 phrases: list[str]) -> list[PhraseRow]:
    rows: list[PhraseRow] = []
    for phrase in phrases:
        needle = phrase.lower()
        hits = sorted(
            d for d, paras in by_date.items()
            if any(needle in p.text.lower() for p in paras)
        )
        if not hits:
            continue
        rows.append(PhraseRow(phrase, hits[0].isoformat(),
                              hits[-1].isoformat(), len(hits)))
    return rows
