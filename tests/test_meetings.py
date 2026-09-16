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
    ("1/4", 0.25), ("3/4", 0.75),
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

def test_parse_target_range_zirp_era_bare_fraction_from_zero():
    text = ("The Committee decided to maintain the target range for the "
            "federal funds rate at 0 to 1/4 percent.")
    assert parse_target_range(text) == (0.0, 0.25)

def test_parse_target_range_zirp_era_bare_fraction_to_bare_fraction():
    text = ("The Committee decided to maintain the target range for the "
            "federal funds rate at 1/4 to 1/2 percent.")
    assert parse_target_range(text) == (0.25, 0.5)

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


# --- regressions found on the live 2026-09-16 statement -------------------

def test_parse_vote_handles_entity_encoded_dash():
    """The Fed's raw HTML writes the vote dash as &#8211;, not a literal en dash.

    parse_vote reads raw HTML, so without unescaping it silently finds no vote
    line on every real document. Confirmed live on 2026-09-16.
    """
    raw = '<p>approved ... for release by a 12 &#8211; 0 vote:</p>'
    assert parse_vote(raw) == (12, 0)


def test_parse_vote_still_handles_literal_dash():
    assert parse_vote("<p>by a 9 – 3 vote</p>") == (9, 3)
    assert parse_vote("<p>by a 12-0 vote</p>") == (12, 0)


def test_parse_target_range_handles_hike_phrasing():
    """A hike reads 'raise ... by 1/4 percentage point TO x to y percent',
    not 'maintain ... AT x to y percent'. Confirmed live on 2026-09-16."""
    text = ("The Committee decided to raise the target range for the federal funds "
            "rate by 1/4 percentage point to 3-3/4 to 4 percent, in support of the "
            "Federal Reserve's dual mandate.")
    assert parse_target_range(text) == (3.75, 4.0)


def test_parse_target_range_still_handles_hold_phrasing():
    text = ("The Committee decided to maintain the target range for the federal "
            "funds rate at 3-1/2 to 3-3/4 percent.")
    assert parse_target_range(text) == (3.5, 3.75)


def test_september_2026_fixture_end_to_end():
    from pathlib import Path
    from fomc_diff.parse import parse_statement
    raw = (Path(__file__).parent / "fixtures" / "statement_20260916.html").read_text(encoding="utf-8")
    paras = parse_statement(raw)
    assert [p.role for p in paras] == ["policy", "economy", "inflation"]
    assert parse_vote(raw) == (12, 0)
    policy = [p.text for p in paras if p.role == "policy"][0]
    assert parse_target_range(policy) == (3.75, 4.0)
