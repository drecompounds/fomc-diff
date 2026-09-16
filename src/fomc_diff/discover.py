"""Resolve FOMC statement URLs from the Fed's own listing pages.

The statement URL suffix is not an identity. monetary20081216a.htm is a Term
Auction Facility result, not the December 2008 statement; monetary20160127b.htm
is the Statement on Longer-Run Goals, published the same day as the January
statement. This module never constructs a statement URL from a date -- it reads
what the Fed labelled as a statement.
"""
from __future__ import annotations

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


# Task 2 functions (stubs for now)

def listing_urls(through_year: int) -> list[str]:
    """Generate the list of Fed listing page URLs to fetch."""
    raise NotImplementedError()


def build_corpus(pages: dict[str, str], current_year: int) -> dict[date, str]:
    """Merge every listing page into one date-to-URL map, and sanity-check it."""
    raise NotImplementedError()
