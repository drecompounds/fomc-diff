"""Structured facts extracted from a statement: vote, target range, dissent."""
from __future__ import annotations

import html as _html
import re

from .errors import FomcParseError
from .parse import parse_statement


class MeetingParseError(FomcParseError):
    """Raised when an expected vote, target-range, or dissent line is
    missing from a statement (e.g. Fed HTML drift), as opposed to a bug."""


# The character class is [U+2010-U+2015, ASCII "-"]. The Unicode range
# U+2010-U+2015 covers the dash variants the Fed's HTML actually uses
# (hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal
# bar). The trailing ASCII "\-" is load-bearing: U+002D (plain "-") sorts
# BELOW U+2010, so it is NOT included in that range — removing it breaks
# plain "by a 12-0 vote".
_DASH = r"[‐-―\-]"
_VOTE = re.compile(rf"by a (\d+)\s*{_DASH}\s*(\d+)\s*vote", re.I)
# Matches a whole number ("5"), a whole-plus-fraction ("3-1/2"), or a bare
# fraction ("1/4") — the last is required for ZIRP-era statements
# (2008-2015), which read "...at 0 to 1/4 percent".
_NUM = r"\d+-\d+/\d+|\d+/\d+|\d+"
# A hold reads "...federal funds rate AT x to y percent"; a hike or cut reads
# "...federal funds rate BY 1/4 percentage point TO x to y percent". Both must
# parse, or every meeting that actually moved rates is unreadable.
_RANGE = re.compile(
    rf"target range for the federal funds rate\s+"
    rf"(?:by\s+[\d/\- ]+percentage\s+points?\s+)?"
    rf"(?:at|to)\s+({_NUM})\s+to\s+({_NUM})\s+percent",
    re.I)
_DISSENT = re.compile(r"were (.+?), who (.+)$", re.S)
_DIRECTIONS = ("raise", "lower", "maintain")

_TITLES = re.compile(
    r",\s*(?:Vice\s+Chairman|Vice\s+Chair|Chairman|Chair)\b", re.I)
_VOTE_FOR_OPEN = re.compile(
    r"Voting for the (?:FOMC )?monetary policy action (?:were|was):?\s*", re.I)
_VOTE_AGAINST_OPEN = re.compile(
    r"Voting against (?:the|this) action (?:were|was)\s*", re.I)


def _count_names(segment: str) -> int:
    """Count people in a 'for' list. Titles are appositives, not voters."""
    seg = _TITLES.sub("", segment)
    seg = seg.rstrip(". ")
    parts = re.split(r";|,| and ", seg)
    return len([p for p in parts if p.strip()])


def _count_dissenters(segment: str) -> int:
    """Count people in an 'against' clause.

    Each dissent group is 'Name[ and Name], who <prose>'. The prose is full of
    capitalised words ('Committee'), so names must be taken from BEFORE the
    ', who' rather than matched across the whole clause.
    """
    total = 0
    for group in segment.split(";"):
        group = re.sub(r"^\s*and\s+", "", group.strip())
        head = re.split(r",\s*who\b", group)[0]
        head = _TITLES.sub("", head).rstrip(". ")
        if not head:
            continue
        total += len([p for p in re.split(r"\s+and\s+|,", head) if p.strip()])
    return total


def parse_fraction(s: str) -> float:
    """'3-1/2' -> 3.5. '1/4' -> 0.25 (bare fraction). Plain integers pass
    through."""
    s = s.strip()
    if "/" not in s:
        return float(s)
    if "-" in s:
        whole, frac = s.split("-", 1)
    else:
        whole, frac = "0", s
    num, den = frac.split("/")
    return float(whole) + float(num) / float(den)


def parse_vote(html: str) -> tuple[int, int]:
    """Vote counts, from the printed line when the Fed prints one, else by
    counting the names it lists.

    'by a N-M vote' appears only from 2026. For 2016-2025 the Committee prints
    a named roll instead, so the count must be derived.
    """
    # Raw Fed HTML encodes the vote dash as an entity (&#8211;), which no dash
    # character class can match. Unescape first or every real document looks
    # like it has no vote line. Confirmed live on the 2026-09-16 statement.
    text = _html.unescape(html)
    m = _VOTE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))

    paras = parse_statement(html)
    for_text = next((p.text for p in paras if p.role == "vote_for"), None)
    against_text = next((p.text for p in paras if p.role == "vote_against"), None)
    if for_text is None and against_text is None:
        raise MeetingParseError(
            "no vote found: neither a printed 'by a N-M vote' line nor a "
            "'Voting for' roll is present")

    n_for = 0
    if for_text is not None:
        body = _VOTE_FOR_OPEN.split(for_text, maxsplit=1)[-1]
        # A combined paragraph carries the against-clause too; split it off.
        halves = re.split(r"Voting against", body, maxsplit=1, flags=re.I)
        n_for = _count_names(halves[0])
        if len(halves) > 1 and against_text is None:
            against_text = "Voting against" + halves[1]

    n_against = 0
    if against_text is not None:
        clause = _VOTE_AGAINST_OPEN.split(against_text, maxsplit=1)[-1]
        n_against = _count_dissenters(clause)
    return n_for, n_against


def parse_target_range(text: str) -> tuple[float, float]:
    m = _RANGE.search(text)
    if not m:
        raise MeetingParseError("no target range found")
    return parse_fraction(m.group(1)), parse_fraction(m.group(2))


def parse_dissent(text: str) -> tuple[list[str], str]:
    m = _DISSENT.search(text)
    if not m:
        raise MeetingParseError("no dissent clause found")
    raw_names, tail = m.group(1), m.group(2)
    names = [n.strip() for n in re.split(r",\s*and\s+|,\s*|\s+and\s+", raw_names)
             if n.strip()]
    direction = "unclear"
    for d in _DIRECTIONS:
        if re.search(rf"preferred to {d}\b", tail):
            direction = d
            break
    return names, direction


def derive_decision(prev_upper: float | None, cur_upper: float) -> str:
    """Decision comes from the numbers, never from prose."""
    if prev_upper is None or cur_upper == prev_upper:
        return "hold"
    return "hike" if cur_upper > prev_upper else "cut"
