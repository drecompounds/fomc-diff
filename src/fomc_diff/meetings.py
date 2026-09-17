"""Structured facts extracted from a statement: vote, target range, dissent."""
from __future__ import annotations

import html as _html
import re

from .errors import FomcParseError
from .parse import ArticleContainerError, parse_statement


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
# (2008-2015), which read "...at 0 to 1/4 percent". The whole-plus-fraction
# form reuses _DASH: the Fed writes "1<U+2011>1/2" as often as "1-1/2",
# sometimes both in the same sentence.
_NUM = rf"\d+{_DASH}\d+/\d+|\d+/\d+|\d+"
# A hold reads "...federal funds rate AT x to y percent"; a hike or cut reads
# "...federal funds rate BY 1/4 percentage point TO x to y percent". Both must
# parse, or every meeting that actually moved rates is unreadable. 2020-03-03
# additionally writes a comma before "to" ("...percentage point, to 1 to
# 1-1/4 percent"), so the optional comma must be allowed here too.
_RANGE = re.compile(
    rf"target range for the federal funds rate\s+"
    rf"(?:by\s+[\d/\- ]+percentage\s+points?,?\s+)?"
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

    Each dissent group is 'Name[ and Name], who <prose>' or, on 2016-09-21 and
    2016-11-02, 'Name[, Name,] and Name, each of whom <prose>'. The prose is
    full of capitalised words ('Committee'), so names must be taken from
    BEFORE the relative-clause opener rather than matched across the whole
    clause. Anchored on a leading comma so it can't eat a comma inside a name;
    "of whom" is optional and "who"/"whom" both close it off with \b so it
    cannot match e.g. "who" inside a longer word.
    """
    total = 0
    for group in segment.split(";"):
        group = re.sub(r"^\s*and\s+", "", group.strip())
        head = re.split(r",\s*(?:each\s+of\s+)?whom?\b", group)[0]
        head = _TITLES.sub("", head).rstrip(". ")
        if not head:
            continue
        total += len([p for p in re.split(r"\s+and\s+|,", head) if p.strip()])
    return total


def parse_fraction(s: str) -> float:
    """'3-1/2' -> 3.5. '1/4' -> 0.25 (bare fraction). Plain integers pass
    through.

    Splits on _DASH, not a bare ASCII "-": the Fed writes the whole/fraction
    separator as U+2011 (non-breaking hyphen) as often as ASCII, sometimes
    both in one sentence ("at 1-1/2 to 1-3/4 percent").
    """
    s = s.strip()
    if "/" not in s:
        return float(s)
    if re.search(_DASH, s):
        whole, frac = re.split(_DASH, s, maxsplit=1)
    else:
        whole, frac = "0", s
    num, den = frac.split("/")
    return float(whole) + float(num) / float(den)


def parse_vote(html: str) -> tuple[int, int]:
    """Vote counts, from the printed line when the Fed prints one, else by
    counting the names it lists.

    'by a N-M vote' appears only from 2026. For 2016-2025 the Committee prints
    a named roll instead, so the count must be derived.

    `_VOTE` is searched over the article's own cleaned paragraph text, not
    the raw page: a `<div id="nav">` or similar boilerplate block elsewhere
    on the page can carry an unrelated "approved by a N-M vote" phrase (e.g.
    a link's surrounding text) that would otherwise short-circuit past this
    statement's actual, named roll. The raw page is used only as a fallback
    when the page has no recognisable article container at all, so a bare
    string like "<p>by a 9 - 3 vote</p>" (no <div id="article">) still works.
    """
    # Raw Fed HTML encodes the vote dash as an entity (&#8211;), which no dash
    # character class can match. Unescape first or every real document looks
    # like it has no vote line. Confirmed live on the 2026-09-16 statement.
    text = _html.unescape(html)
    try:
        paras = parse_statement(html)
    except ArticleContainerError:
        m = _VOTE.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))
        raise MeetingParseError(
            "no vote found: neither a printed 'by a N-M vote' line nor a "
            "'Voting for' roll is present")

    m = _VOTE.search(" ".join(p.text for p in paras))
    if m:
        return int(m.group(1)), int(m.group(2))

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
    """Accepts raw HTML or plain text.

    Raw HTML is routed through parse_statement first: the Fed puts
    "<strong> </strong>" INSIDE the phrase (live in the 2026-09-16 statement),
    and a regex run against raw markup cannot match across it.

    Only the cleaned `policy`/`directive` paragraph text is ever searched --
    never the raw page. A page whose article has no policy/directive
    paragraph must raise, not fall back to searching a footer or nav block
    that happens to carry plausible-looking target-range text unrelated to
    this statement's actual decision. `ArticleContainerError` (no
    recognisable article container at all) is likewise never swallowed: a
    structurally broken page is a different failure than a well-formed one
    that simply lacks the paragraph, and both must be loud.
    """
    haystack = text
    if "<" in text:
        paras = parse_statement(text)
        haystack = " ".join(
            p.text for p in paras if p.role in ("policy", "directive"))
    m = _RANGE.search(haystack)
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
    """Decision comes from the numbers, never from prose.

    Raises when there is no previous meeting to compare against, rather than
    defaulting to 'hold': "no prior meeting" and "no change from the prior
    meeting" are different facts, and conflating them made the corpus's very
    first row (2016-01-27) 'hold' by default instead of by measurement.
    Callers that have a documented prior pass its upper bound instead of
    None (see backfill.SEED_PRIOR_UPPER).
    """
    if prev_upper is None:
        raise MeetingParseError(
            "no previous meeting to derive a decision from; pass a "
            "documented prior target-range upper bound instead of None "
            "rather than defaulting to 'hold'"
        )
    if cur_upper == prev_upper:
        return "hold"
    return "hike" if cur_upper > prev_upper else "cut"
