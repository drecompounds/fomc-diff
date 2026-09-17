from datetime import date
from pathlib import Path

import pytest

from fomc_diff import backfill
from fomc_diff.backfill import build_rows
from fomc_diff.discover import DiscoveryError
from fomc_diff.errors import FomcParseError
from fomc_diff.parse import parse_statement

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


def _docs(*stamps):
    return {date(int(s[:4]), int(s[4:6]), int(s[6:])):
            _html(f"statement_{s}.html") for s in stamps}


def test_operational_statements_are_labelled_and_need_no_vote():
    """2020-03-23 is a Desk directive with no rate decision. Requiring a
    policy paragraph would either raise on it or file it as a rate
    decision."""
    meetings, _, _ = build_rows(_docs("20200323"))
    assert meetings[0]["statement_type"] == "operational"
    assert meetings[0]["vote_for"] is None


def test_decision_statements_carry_vote_and_range():
    meetings, _, _ = build_rows(_docs("20250917"))
    row = meetings[0]
    assert row["statement_type"] == "decision"
    assert (row["vote_for"], row["vote_against"]) == (11, 1)
    assert (row["target_lower"], row["target_upper"]) == (4.0, 4.25)


def test_a_decision_row_missing_its_policy_paragraph_raises():
    """The narrowed policy anchor must fail loudly in a new era, not write a
    row with empty columns."""
    with pytest.raises(FomcParseError):
        build_rows({date(2026, 1, 1): "<div id=\"article\"><p>The Committee "
                                      "met and adjourned promptly.</p>"
                                      "<p>Nothing else happened at all.</p>"
                                      "<p>A third filler paragraph.</p></div>"})


def test_decision_is_derived_from_the_range_not_the_prose():
    """The brief's own draft of this test asserted 'hike' here. The actual
    fixtures put 2025-09-17 at (4.0, 4.25) and 2026-09-16 at (3.75, 4.0) --
    see test_meetings.py's test_target_range_across_eras, part of the
    existing 125-test baseline. Fed to build_rows with no meetings in
    between, that is a fall in the upper bound, i.e. a 'cut', not a 'hike'.
    (2026-09-16 IS a real hike relative to its true immediately-preceding
    meeting, 2026-07-29 at (3.5, 3.75); the brief's draft skipped that
    meeting and got the direction over the longer span backwards.) The
    point of the test survives unchanged: decision must come from comparing
    target_upper values, not from parsing "raise"/"lower" out of the prose."""
    meetings, _, _ = build_rows(_docs("20250917", "20260916"))
    by_date = {m["meeting_date"]: m for m in meetings}
    assert by_date[date(2026, 9, 16)]["decision"] == "cut"


def test_diffs_are_produced_for_consecutive_pairs_only():
    _, _, diffs = build_rows(_docs("20260617", "20260729", "20260916"))
    pairs = {(d["from_date"], d["to_date"]) for d in diffs}
    assert (date(2026, 6, 17), date(2026, 9, 16)) not in pairs
    assert (date(2026, 6, 17), date(2026, 7, 29)) in pairs


def test_statements_table_has_one_row_per_paragraph():
    meetings, statements, _ = build_rows(_docs("20250917"))
    assert len(statements) == len(parse_statement(_html("statement_20250917.html")))
    assert all(s["meeting_date"] == date(2025, 9, 17) for s in statements)


# --- run()'s year-contiguity guard ----------------------------------------
#
# build_corpus's per-year minimum only inspects years that appear as keys in
# the merged corpus. A year missing entirely produces no key, so that guard
# never sees it -- run() is the only caller that knows the full intended
# page range (discover.FIRST_YEAR..current_year), so it must check
# contiguity itself. These tests stub fetch/build_corpus so they stay
# offline: they exercise run()'s own check, not the network or HTML
# parsing.

class _FakeFetchResult:
    def __init__(self, url, path):
        self.url = url
        self.path = path
        self.sha256 = "0" * 64
        self.fetched_at = "2026-01-01T00:00:00+00:00"
        self.from_cache = True


def _stub_network(monkeypatch, tmp_path, corpus):
    """Make run() skip discovery/fetching and hand it `corpus` directly."""
    dummy = tmp_path / "dummy.html"
    dummy.write_bytes(b"<div id=\"article\"><p>placeholder</p></div>")
    monkeypatch.setattr(backfill, "listing_urls", lambda through_year: ["fake-listing"])
    monkeypatch.setattr(backfill, "fetch",
                         lambda url, cache_dir: _FakeFetchResult(url, dummy))
    monkeypatch.setattr(backfill, "build_corpus",
                         lambda pages, current_year: corpus)


def test_a_missing_year_is_refused_rather_than_written(monkeypatch, tmp_path):
    """A year absent entirely produces no per-year count, so build_corpus's
    minimum cannot see it. Without this, a failed listing page ships a
    corpus with a silent hole."""
    corpus = {date(2016, 3, 16): "url-a", date(2026, 9, 16): "url-b"}
    _stub_network(monkeypatch, tmp_path, corpus)
    with pytest.raises(DiscoveryError, match="2017"):
        backfill.run(tmp_path, tmp_path, current_year=2026)


def test_a_fully_contiguous_corpus_is_accepted(monkeypatch, tmp_path):
    """Sanity check for the guard above: a corpus with every year present
    (2016..current_year) must NOT raise on contiguity grounds."""
    corpus = {date(y, 1, 1): f"url-{y}" for y in range(2016, 2027)}
    _stub_network(monkeypatch, tmp_path, corpus)
    # Each stubbed document is a single unclassified paragraph, so every
    # date parses as a "decision" statement type missing a policy paragraph
    # -- build_rows() correctly raises past the contiguity check. DiscoveryError
    # IS a FomcParseError, so assert the error is specifically NOT a
    # DiscoveryError to prove the failure came from build_rows, not from the
    # contiguity guard rejecting a corpus it should have accepted.
    with pytest.raises(FomcParseError) as exc_info:
        backfill.run(tmp_path, tmp_path, current_year=2026)
    assert not isinstance(exc_info.value, DiscoveryError)
