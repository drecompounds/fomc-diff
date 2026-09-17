"""Corpus-wide gate: dissents.csv and meetings.csv must mutually check.

This reads the SHIPPED DATASET -- data/meetings.csv and data/dissents.csv --
rather than a hand-picked fixture, so a real-corpus mismatch (an against-
clause shape that build_rows's invariant check missed) is caught even though
the committed CSVs themselves are static files. See test_corpus.py for the
same pattern applied to statements.csv.
"""
from __future__ import annotations

import collections
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MEETINGS_CSV = REPO_ROOT / "data" / "meetings.csv"
DISSENTS_CSV = REPO_ROOT / "data" / "dissents.csv"

_VALID_DIRECTIONS = {"lower", "raise", "maintain", "unclear"}


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. This gate must run against the shipped "
            "dataset, not a fixture, and must fail loudly rather than skip "
            "when it is absent."
        )
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_dissent_row_count_matches_vote_against_for_every_meeting():
    meetings = _load(MEETINGS_CSV)
    dissent_counts = collections.Counter(row["meeting_date"] for row in _load(DISSENTS_CSV))
    for row in meetings:
        if row["vote_against"] in ("", None):
            continue  # operational statement: no vote at all
        expected = int(row["vote_against"])
        actual = dissent_counts.get(row["meeting_date"], 0)
        assert actual == expected, (
            f"{row['meeting_date']}: vote_against={expected} but "
            f"dissents.csv has {actual} row(s)"
        )


def test_every_dissent_direction_is_a_known_value():
    """`unclear` is a legitimate recorded value; anything else outside the
    four-word vocabulary is a fabricated or malformed direction."""
    for row in _load(DISSENTS_CSV):
        assert row["direction"] in _VALID_DIRECTIONS, row


def test_no_dissent_row_has_a_blank_name():
    for row in _load(DISSENTS_CSV):
        assert row["name"].strip(), row
