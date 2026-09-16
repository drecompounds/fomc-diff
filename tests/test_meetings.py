from pathlib import Path
import pytest
from fomc_diff.meetings import (
    parse_fraction, parse_vote, parse_target_range, parse_dissent,
    derive_decision,
)

FIX = Path(__file__).parent / "fixtures"
def _html(name): return (FIX / name).read_text(encoding="utf-8")

@pytest.mark.parametrize("s,expected", [
    ("3-1/2", 3.5), ("3-3/4", 3.75), ("5", 5.0), ("0-1/4", 0.25),
])
def test_parse_fraction(s, expected):
    assert parse_fraction(s) == expected

def test_parse_vote_handles_en_dash_with_spaces():
    assert parse_vote(_html("statement_20260729.html")) == (9, 3)
    assert parse_vote(_html("statement_20260617.html")) == (12, 0)

def test_parse_target_range():
    text = ("The Committee decided to maintain the target range for the federal "
            "funds rate at 3-1/2 to 3-3/4 percent, in support of the dual mandate.")
    assert parse_target_range(text) == (3.5, 3.75)

def test_parse_dissent_names_and_direction():
    text = ("Voting against the monetary policy action were Beth M. Hammack, "
            "Neel Kashkari, and Lorie K. Logan, who preferred to raise the "
            "target range for the federal funds rate by 1/4 percentage point "
            "at this meeting.")
    names, direction = parse_dissent(text)
    assert names == ["Beth M. Hammack", "Neel Kashkari", "Lorie K. Logan"]
    assert direction == "raise"

def test_parse_dissent_unrecognised_direction_is_unclear_not_dropped():
    text = "Voting against the monetary policy action were Jane Doe, who abstained."
    names, direction = parse_dissent(text)
    assert names == ["Jane Doe"]
    assert direction == "unclear"

@pytest.mark.parametrize("prev,cur,expected", [
    (3.75, 4.0, "hike"), (3.75, 3.5, "cut"), (3.75, 3.75, "hold"),
    (None, 3.75, "hold"),
])
def test_derive_decision(prev, cur, expected):
    assert derive_decision(prev, cur) == expected
