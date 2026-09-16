"""Summary of Economic Projections (the 'dot plot' tables)."""
from datetime import date
from pathlib import Path

import pytest

from fomc_diff.sep import SepParseError, SepRow, diff_sep, parse_sep, sep_url

FIX = Path(__file__).parent / "fixtures"
JUN, SEP = date(2026, 6, 17), date(2026, 9, 16)


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


def _rows(name, d):
    return parse_sep(_html(name), d)


def _one(rows, variable, horizon):
    hits = [r for r in rows if r.variable == variable and r.horizon == horizon]
    assert len(hits) == 1, f"expected exactly one {variable}/{horizon}, got {len(hits)}"
    return hits[0]


def test_sep_url():
    assert sep_url(SEP) == (
        "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm")


def test_horizons_are_derived_from_the_header_not_positional():
    """June 2026 projects through 2028; September added 2029.

    A hardcoded column index would silently align September's 2027 with
    June's 2028 and report confident wrong deltas.
    """
    jun = {r.horizon for r in _rows("sep_20260617.html", JUN)}
    sep = {r.horizon for r in _rows("sep_20260916.html", SEP)}
    assert jun == {"2026", "2027", "2028", "longer_run"}
    assert sep == {"2026", "2027", "2028", "2029", "longer_run"}


def test_september_medians_match_the_published_table():
    rows = _rows("sep_20260916.html", SEP)
    assert _one(rows, "fed_funds", "2026").median == 4.1
    assert _one(rows, "fed_funds", "2027").median == 4.1
    assert _one(rows, "fed_funds", "2028").median == 3.9
    assert _one(rows, "fed_funds", "2029").median == 3.6
    assert _one(rows, "fed_funds", "longer_run").median == 3.2
    assert _one(rows, "pce_inflation", "2026").median == 3.7
    assert _one(rows, "unemployment", "2026").median == 4.1
    assert _one(rows, "gdp", "2026").median == 2.3


def test_june_medians_match_the_published_table():
    rows = _rows("sep_20260617.html", JUN)
    assert _one(rows, "fed_funds", "2026").median == 3.8
    assert _one(rows, "fed_funds", "2027").median == 3.6
    assert _one(rows, "fed_funds", "2028").median == 3.4
    assert _one(rows, "fed_funds", "longer_run").median == 3.1
    assert _one(rows, "unemployment", "2026").median == 4.3


def test_central_tendency_and_range_split_on_the_unicode_en_dash():
    """Cells read '2.2–2.4' with U+2013, not an ASCII hyphen.

    Same character family as the &#8211; that broke parse_vote on the live
    2026-09-16 statement.
    """
    r = _one(_rows("sep_20260916.html", SEP), "gdp", "2026")
    assert (r.ct_low, r.ct_high) == (2.2, 2.4)
    assert (r.range_low, r.range_high) == (2.1, 2.6)


def test_core_pce_longer_run_is_none_not_zero_and_does_not_raise():
    """The Fed publishes no longer-run core PCE projection. That cell is
    legitimately empty; it must come back None, never 0.0, never an exception."""
    rows = _rows("sep_20260916.html", SEP)
    hits = [r for r in rows if r.variable == "core_pce_inflation" and r.horizon == "longer_run"]
    if hits:                       # row present with an empty cell
        assert hits[0].median is None
    # absent entirely is also acceptable; what is forbidden is a 0.0


def test_all_five_variables_are_captured():
    rows = _rows("sep_20260916.html", SEP)
    assert {r.variable for r in rows} == {
        "gdp", "unemployment", "pce_inflation", "core_pce_inflation", "fed_funds"}


def test_diff_sep_reports_the_2027_dot_moving_half_a_point():
    """The finding posted on 2026-09-16: the 2027 median rose 0.5 in one quarter."""
    deltas = diff_sep(_rows("sep_20260617.html", JUN), _rows("sep_20260916.html", SEP))
    by_key = {(d.variable, d.horizon): d for d in deltas}
    assert by_key[("fed_funds", "2027")].delta == pytest.approx(0.5)
    assert by_key[("fed_funds", "2028")].delta == pytest.approx(0.5)
    assert by_key[("fed_funds", "2026")].delta == pytest.approx(0.3)
    assert by_key[("unemployment", "2026")].delta == pytest.approx(-0.2)


def test_diff_sep_skips_horizons_absent_from_one_side():
    """2029 exists only in September. It has no June counterpart, so it must be
    omitted rather than diffed against None or against longer_run."""
    deltas = diff_sep(_rows("sep_20260617.html", JUN), _rows("sep_20260916.html", SEP))
    assert all(d.horizon != "2029" for d in deltas)


def test_missing_header_raises():
    with pytest.raises(SepParseError):
        parse_sep("<html><body><p>no table here</p></body></html>", SEP)


def test_row_with_wrong_cell_count_raises_rather_than_misaligning():
    """A short data row would otherwise shift every value one horizon left.

    The header here is VALID (three identical groups of two horizons), so this
    reaches the arity guard rather than failing earlier on header validation.
    """
    html = (
        "<table>"
        "<tr><th>Variable</th><th>Median</th><th>Central Tendency</th><th>Range</th></tr>"
        "<tr><th>2026</th><th>2027</th>"
        "<th>2026</th><th>2027</th>"
        "<th>2026</th><th>2027</th></tr>"
        "<tr><td>Federal funds rate</td><td>4.1</td><td>4.1</td></tr>"
        "</table>"
    )
    with pytest.raises(SepParseError, match="horizons"):
        parse_sep(html, SEP)


def test_a_valid_minimal_table_parses_so_the_arity_test_is_not_vacuous():
    """Proves the synthetic shape above is otherwise parseable -- without this,
    the arity test could be passing because the table is malformed some other way."""
    html = (
        "<table>"
        "<tr><th>Variable</th><th>Median</th><th>Central Tendency</th><th>Range</th></tr>"
        "<tr><th>2026</th><th>2027</th>"
        "<th>2026</th><th>2027</th>"
        "<th>2026</th><th>2027</th></tr>"
        "<tr><td>Federal funds rate</td><td>4.1</td><td>4.4</td>"
        "<td>4.1–4.4</td><td>4.1–4.4</td>"
        "<td>3.9–4.4</td><td>3.9–4.4</td></tr>"
        "</table>"
    )
    rows = parse_sep(html, SEP)
    assert len(rows) == 2
    assert rows[0].median == 4.1 and rows[1].median == 4.4


def test_no_duplicate_rows_per_variable_and_horizon():
    """September's table restates June inline. If variable matching ever loosened,
    those rows would double every value. One row per pair, always."""
    rows = _rows("sep_20260916.html", SEP)
    seen = [(r.variable, r.horizon) for r in rows]
    assert len(seen) == len(set(seen)), "duplicate (variable, horizon) rows"
    assert len(rows) == 5 * 5, f"expected 5 variables x 5 horizons, got {len(rows)}"


def test_rows_carry_the_meeting_date():
    rows = _rows("sep_20260916.html", SEP)
    assert all(r.meeting_date == SEP for r in rows)
    assert isinstance(rows[0], SepRow)
