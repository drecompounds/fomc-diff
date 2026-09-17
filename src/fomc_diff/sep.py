"""Summary of Economic Projections -- the quarterly 'dot plot' tables.

Same thesis as the statement work: the numbers carry information the prose does
not. Everything here is parsed, never inferred.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import date

from .dashes import UNICODE_DASHES
from .errors import FomcParseError

BASE = "https://www.federalreserve.gov"

# Cells separate a low/high pair with U+2013 EN DASH as often as an ASCII
# hyphen -- same character family as the &#8211; that made parse_vote find no
# vote line on the live 2026-09-16 statement. The trailing ASCII "\-" is
# explicit and load-bearing, same as meetings._DASH: without it, a pair
# written with a plain hyphen ("2.2-2.4") raises instead of parsing.
_PAIR_DASH = rf"[{UNICODE_DASHES}\-]"

_VARIABLES = {
    "change in real gdp": "gdp",
    "unemployment rate": "unemployment",
    "pce inflation": "pce_inflation",
    "core pce inflation": "core_pce_inflation",
    "federal funds rate": "fed_funds",
}

# September's table restates the prior release inline on rows labelled
# "June projection". They are filtered by _VARIABLES below -- that label
# matches no variable -- so there is deliberately no separate guard here.
# A test asserts one row per (variable, horizon) to keep it that way.

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_FOOTNOTE = re.compile(r"\s*\d+$")


class SepParseError(FomcParseError):
    """The projections table is missing, or a row does not line up with the
    horizons declared in its header."""


@dataclass(frozen=True)
class SepRow:
    meeting_date: date
    variable: str
    horizon: str
    median: float | None
    ct_low: float | None
    ct_high: float | None
    range_low: float | None
    range_high: float | None


@dataclass(frozen=True)
class SepDelta:
    variable: str
    horizon: str
    before: float
    after: float
    delta: float


def sep_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/fomcprojtabl{d.strftime('%Y%m%d')}.htm"


def _cells(row_html: str) -> list[str]:
    out = []
    for c in _CELL.findall(row_html):
        t = _html.unescape(_TAG.sub(" ", c)).replace(" ", " ")
        out.append(_WS.sub(" ", t).strip())
    return out


def _horizon(label: str) -> str:
    lab = label.strip().lower()
    if lab.startswith("longer"):
        return "longer_run"
    return lab


def _number(cell: str) -> float | None:
    """An empty cell is a real absence (the Fed publishes no longer-run core
    PCE projection). It must be None -- never 0.0, which would read as a
    forecast of zero."""
    cell = cell.strip()
    if not cell or cell in {"-", "–", "—"}:
        return None
    try:
        return float(cell)
    except ValueError as exc:
        raise SepParseError(f"unparseable projection value {cell!r}") from exc


def _pair(cell: str) -> tuple[float | None, float | None]:
    """'2.2-2.4' -> (2.2, 2.4). A lone '2.0' means the low and high coincide,
    which the Fed prints when every participant agrees."""
    cell = cell.strip()
    if not cell:
        return None, None
    parts = re.split(_PAIR_DASH, cell)
    if len(parts) == 1:
        v = _number(parts[0])
        return v, v
    if len(parts) != 2:
        raise SepParseError(f"cannot split projection pair {cell!r}")
    return _number(parts[0]), _number(parts[1])


def _find_table(html: str) -> tuple[str, list[str]]:
    """Return the projections table and its horizon labels, taken from the
    header row rather than by position: June 2026 runs through 2028, September
    added 2029, so a fixed column index would misalign the two releases."""
    for body in _TABLE.findall(html):
        rows = _ROW.findall(body)
        if len(rows) < 3:
            continue
        head = [c.lower() for c in _cells(rows[0])]
        if not head or "variable" not in head[0]:
            continue
        if not any("median" in c for c in head):
            continue
        years = _cells(rows[1])
        if not years or len(years) % 3 != 0:
            continue
        n = len(years) // 3
        groups = [years[0:n], years[n:2 * n], years[2 * n:3 * n]]
        if groups[0] != groups[1] or groups[1] != groups[2]:
            raise SepParseError(
                "median/central-tendency/range headers disagree on horizons: "
                f"{groups!r}")
        return body, [_horizon(y) for y in groups[0]]
    raise SepParseError("no projections table found (expected a Variable/Median header)")


def parse_sep(html: str, meeting_date: date) -> list[SepRow]:
    body, horizons = _find_table(html)
    n = len(horizons)
    expected = 1 + 3 * n

    out: list[SepRow] = []
    for row_html in _ROW.findall(body)[2:]:
        cs = _cells(row_html)
        if not cs:
            continue
        label = _FOOTNOTE.sub("", cs[0]).strip()
        if not label:
            continue
        key = _VARIABLES.get(label.lower())
        if key is None:
            continue
        if len(cs) != expected:
            raise SepParseError(
                f"{label!r} has {len(cs)} cells but the header declares {n} "
                f"horizons ({expected} expected); refusing to guess the alignment")
        for i, horizon in enumerate(horizons):
            ct_lo, ct_hi = _pair(cs[1 + n + i])
            rg_lo, rg_hi = _pair(cs[1 + 2 * n + i])
            out.append(SepRow(meeting_date, key, horizon, _number(cs[1 + i]),
                              ct_lo, ct_hi, rg_lo, rg_hi))
    if not out:
        raise SepParseError("projections table matched no known variables")
    return out


def diff_sep(before: list[SepRow], after: list[SepRow]) -> list[SepDelta]:
    """Median deltas for (variable, horizon) pairs present in BOTH releases.

    A horizon that only one side projects -- 2029 appears in September 2026 and
    not in June -- is omitted. Diffing it against the other side's longer-run
    column would be the classic positional misalignment this module exists to
    avoid.
    """
    b = {(r.variable, r.horizon): r.median for r in before if r.median is not None}
    a = {(r.variable, r.horizon): r.median for r in after if r.median is not None}
    out = []
    for key in sorted(b.keys() & a.keys()):
        out.append(SepDelta(key[0], key[1], b[key], a[key], round(a[key] - b[key], 10)))
    return out
