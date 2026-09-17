from pathlib import Path
import pytest
from fomc_diff.meetings import (
    parse_fraction, parse_vote, parse_target_range, parse_dissent,
    derive_decision, MeetingParseError,
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
    assert [p.role for p in paras] == ["vote", "policy", "economy", "inflation"]
    assert parse_vote(raw) == (12, 0)
    policy = [p.text for p in paras if p.role == "policy"][0]
    assert parse_target_range(policy) == (3.75, 4.0)


# --- Task 5: vote counts from a named roll when no line is printed --------

@pytest.mark.parametrize("name,expected", [
    ("statement_20190918.html", (7, 3)),
    ("statement_20211215.html", (11, 0)),
    ("statement_20250917.html", (11, 1)),
    ("statement_20200916.html", (8, 2)),
    ("statement_20160316.html", (9, 1)),
    ("statement_20160921.html", (7, 3)),   # "each of whom", three dissenters
    ("statement_20161102.html", (8, 2)),   # "each of whom", two dissenters
])
def test_named_list_vote_counts(name, expected):
    """Counts verified by hand from the fixture text. No statement carries both
    a printed count and a named list, so there is nothing to cross-check
    against -- these numbers are the ground truth."""
    assert parse_vote(_html(name)) == expected


def test_unanimous_vote_is_a_fact_not_a_parse_failure():
    """2021-12-15 has no against-clause. Zero dissents must come back as 0, not
    raise, and not be confused with 'could not find the vote'."""
    assert parse_vote(_html("statement_20211215.html")) == (11, 0)


def test_titles_are_not_counted_as_voters():
    """'Jerome H. Powell, Chair, John C. Williams, Vice Chair' is two people.
    Counting comma-separated segments naively makes it four."""
    assert parse_vote(_html("statement_20190918.html"))[0] == 7


def test_counted_era_still_uses_the_printed_line():
    """2026 prints 'by a 9-3 vote'. That branch must not regress."""
    assert parse_vote(_html("statement_20260729.html")) == (9, 3)


def test_each_of_whom_does_not_inflate_the_dissent_count():
    """2016-09-21 and 2016-11-02 introduce the dissenters with 'each of whom'
    rather than 'who'. Splitting only on ', who' leaves the trailing prose in
    the name list, where it counts as one extra dissenter -- a wrong number in
    the project's headline metric, not a crash."""
    assert parse_vote(_html("statement_20160921.html")) == (7, 3)
    assert parse_vote(_html("statement_20161102.html")) == (8, 2)


# --- Task 6: widen target-range parsing across eras ------------------------

@pytest.mark.parametrize("name,expected", [
    ("statement_20200129.html", (1.5, 1.75)),
    ("statement_20200303.html", (1.0, 1.25)),
    ("statement_20211215.html", (0.0, 0.25)),
    ("statement_20250917.html", (4.0, 4.25)),
    ("statement_20260916.html", (3.75, 4.0)),
])
def test_target_range_across_eras(name, expected):
    """Two real causes, both measured. 2020-01-29 and 2025-09-17 write the
    fraction with U+2011 NON-BREAKING HYPHEN, which the ASCII-only _NUM
    rejects. 2026-09-16 is pure ASCII but carries '<strong> </strong>' INSIDE
    the phrase, which breaks a regex run against raw HTML.

    2021-12-15 (ZIRP, '0 to 1/4 percent') is in this list as a REGRESSION
    guard: it already passes today, and the spec was wrong to blame it."""
    assert parse_target_range(_html(name)) == expected


def test_non_breaking_hyphen_is_read_as_a_fraction():
    """Isolates cause 1 from cause 2, so a fix for one cannot appear to fix
    both. U+2011 must parse identically to ASCII hyphen."""
    from fomc_diff.meetings import parse_fraction
    assert parse_fraction("1‑1/2") == 1.5
    assert parse_fraction("1-1/2") == 1.5


def test_inline_markup_inside_the_phrase_does_not_defeat_the_match():
    """Isolates cause 2. This exact shape is live in the 2026-09-16 statement."""
    html = ('<div id="article"><p>The Committee decided to raise the target '
            'range for the federal funds rate by 1/4 percentage point'
            '<strong> </strong>to 3-3/4<strong> </strong>to 4 percent.</p>'
            '<p>Economic activity is expanding.</p>'
            '<p>Inflation remains elevated.</p></div>')
    assert parse_target_range(html) == (3.75, 4.0)


def test_unparseable_range_raises_rather_than_returning_zero():
    """A range of 0 to 0 is a plausible-looking wrong answer, and ZIRP makes it
    look legitimate. Absence must raise."""
    with pytest.raises(MeetingParseError):
        parse_target_range("<html><body><p>No range here.</p></body></html>")
