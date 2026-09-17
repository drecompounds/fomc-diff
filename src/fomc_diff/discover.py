"""Resolve FOMC statement URLs from the Fed's own listing pages.

The statement URL suffix is not an identity. monetary20081216a.htm is a Term
Auction Facility result, not the December 2008 statement; monetary20160127b.htm
is the Statement on Longer-Run Goals, published the same day as the January
statement. This module never constructs a statement URL from a date -- it reads
what the Fed labelled as a statement.
"""
from __future__ import annotations

import collections
import html as _html
import re
from datetime import date

from .errors import FomcParseError

BASE = "https://www.federalreserve.gov"

# The historical pages label statement links "Statement"; the current calendar
# labels the identical thing "HTML". Both are verified against the live pages.
STATEMENT_LABELS = frozenset({"Statement", "HTML"})

# Every other label observed adjacent to a monetary*.htm link. Listing these
# explicitly is what lets an unrecognised label raise instead of being guessed
# at in either direction.
KNOWN_NON_STATEMENT_LABELS = frozenset({
    "Statement on Longer-Run Goals and Monetary Policy Strategy",
    "Press Release",
    "Addendum to the Policy Normalization Principles and Plans",
    "Statement Regarding Monetary Policy Implementation and Balance Sheet Normalization",
    "Balance Sheet Normalization Principles and Plans",
    "Principles for Reducing the Size of the Federal Reserve's Balance Sheet",
    "Plans for Reducing the Size of the Federal Reserve's Balance Sheet",
    "Implementation Note",
    "Minutes",
    "PDF",
})

_LINK = re.compile(
    r'<a\s+href="([^"]*?monetary(\d{8})[a-z]\.htm)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class DiscoveryError(FomcParseError):
    """A listing page carried a document type this module does not recognise."""


def _label(raw: str) -> str:
    return _WS.sub(" ", _html.unescape(_TAG.sub(" ", raw))).strip()


def statement_links(html: str) -> dict[date, str]:
    """Map meeting date to statement URL for every statement on this page."""
    out: dict[date, str] = {}
    for href, stamp, raw_label in _LINK.findall(html):
        label = _label(raw_label)
        if label in KNOWN_NON_STATEMENT_LABELS:
            continue
        if label not in STATEMENT_LABELS:
            raise DiscoveryError(
                f"unrecognised label {label!r} on {href!r}; refusing to guess "
                "whether it is a policy statement"
            )
        d = date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
        # First occurrence wins. A date listed twice is never resolved by
        # dict-overwrite, which would silently prefer the last link on the page.
        out.setdefault(d, href if href.startswith("http") else BASE + href)
    return out


# Task 2: Corpus assembly and count guard

FIRST_YEAR = 2016
LAST_HISTORICAL_YEAR = 2020   # 2021+ live on fomccalendars.htm
MIN_MEETINGS_PER_YEAR = 8


def listing_urls(through_year: int) -> list[str]:
    urls = [f"{BASE}/monetarypolicy/fomchistorical{y}.htm"
            for y in range(FIRST_YEAR, LAST_HISTORICAL_YEAR + 1)]
    if through_year > LAST_HISTORICAL_YEAR:
        urls.append(f"{BASE}/monetarypolicy/fomccalendars.htm")
    return urls


def _elapsed_quarters(year: int, today: date) -> int:
    """How many quarters of `year` have started, as of `today`.

    A year strictly before `today.year` is fully elapsed (4). A year in
    progress counts the quarter `today` currently sits in as started. Used
    as a partial floor for the current year, which cannot be held to the
    full-year MIN_MEETINGS_PER_YEAR minimum -- it isn't over yet -- but must
    not be exempt from any floor at all.
    """
    if today.year > year:
        return 4
    return (today.month - 1) // 3 + 1


def build_corpus(
    pages: dict[str, str], current_year: int, today: date | None = None,
) -> dict[date, str]:
    """Merge every listing page into one date-to-URL map, and sanity-check it.

    `pages` maps an identifier to already-fetched HTML, so this stays offline.
    `today` defaults to the real date; tests pass it explicitly to keep the
    in-progress-year floor deterministic.
    """
    today = today or date.today()
    corpus: dict[date, str] = {}
    for html in pages.values():
        for d, url in statement_links(html).items():
            corpus.setdefault(d, url)
    if not corpus:
        raise DiscoveryError(
            "no statements discovered; the listing pages are the single point "
            "of failure for the backfill and must never yield an empty corpus")

    per_year = collections.Counter(d.year for d in corpus)
    for year, n in sorted(per_year.items()):
        if year > current_year:
            continue          # future year; should not happen, harmless
        if year == current_year:
            # In progress, so the full-year minimum does not apply -- but the
            # FOMC meets roughly twice a quarter, so a completely truncated
            # listing page (all but one entry lost) must still be caught
            # rather than passing silently just because the year isn't over.
            floor = _elapsed_quarters(year, today)
            if n < floor:
                raise DiscoveryError(
                    f"{year} (in progress) yielded only {n} statement(s) "
                    f"through {today.isoformat()}, fewer than the {floor} "
                    "elapsed quarter(s) warrant at roughly one meeting per "
                    "quarter; the listing page may have been truncated")
            continue
        if n < MIN_MEETINGS_PER_YEAR:
            raise DiscoveryError(
                f"{year} yielded only {n} statements; the FOMC holds at least "
                f"{MIN_MEETINGS_PER_YEAR} scheduled meetings a year, so the "
                "listing page shape has probably changed")
    return corpus
