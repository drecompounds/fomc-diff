"""Structured facts extracted from a statement: vote, target range, dissent."""
from __future__ import annotations

import html as _html
import re

from .dashes import UNICODE_DASHES
from .errors import FomcParseError
from .parse import ArticleContainerError, parse_statement


class MeetingParseError(FomcParseError):
    """Raised when an expected vote, target-range, or dissent line is
    missing from a statement (e.g. Fed HTML drift), as opposed to a bug."""


# The character class is [U+2010-U+2015, ASCII "-"]. UNICODE_DASHES covers
# the Unicode dash variants the Fed's HTML actually uses (hyphen,
# non-breaking hyphen, figure dash, en dash, em dash, horizontal bar). The
# trailing ASCII "\-" is load-bearing and explicit here: U+002D (plain "-")
# sorts BELOW U+2010, so it is NOT included in that range — removing it
# breaks plain "by a 12-0 vote".
_DASH = rf"[{UNICODE_DASHES}\-]"
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
# Where an against-clause's group-splitting begins: after "Voting against
# ... was/were", optionally followed by a colon (2016's "were:"). Deliberately
# NOT anchored to "the action"/"this action" the way _VOTE_AGAINST_OPEN is --
# 2026 statements write "Voting against the monetary policy action", and a
# non-greedy ".*?" reaches the first "was"/"were" regardless of what sits
# between "against" and it.
_DISSENT_OPEN = re.compile(r"Voting against\b.*?\b(?:were|was):?\s*", re.I | re.S)
# Real corpus trigger phrases for a dissenter's OWN stated rate preference,
# read off the actual "Voting against" clauses across 2011-2026 (not
# guessed): "preferred/prefers [at this meeting] to raise/lower/reduce/
# maintain" and "preferred no change". "reduce" is 2020-03-15's word for
# "lower". Deliberately anchored on "preferred"/"prefers" immediately
# governing the rate verb -- a dissenter who "supported maintaining the
# target range but did not support inclusion of an easing bias" (2026-04-29)
# or "expects that it will be appropriate to maintain" (2020-09-16) is NOT
# stating a rate preference at all; loosening this to a bare "maintain"/
# "raise"/"lower" substring search would fabricate a direction for them.
_DIRECTION_RE = re.compile(
    r"prefer(?:red|s)\s+(?:at this meeting\s+)?"
    r"(?:to\s+(raise|lower|reduce|maintain)\b|(no\s+change)\b)",
    re.I)
_DIRECTION_WORD = {"raise": "raise", "lower": "lower", "reduce": "lower", "maintain": "maintain"}

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


def _split_dissent_groups(segment: str) -> list[tuple[str, str]]:
    """Split an against-clause segment (already past 'were'/'was') into one
    (head, tail) pair per dissent group.

    Each dissent group is 'Name[ and Name], who <prose>' or, on 2016-09-21 and
    2016-11-02, 'Name[, Name,] and Name, each of whom <prose>', with multiple
    groups joined by ';' when a meeting's dissenters split into more than one
    direction (2019-09-18, 2026-04-29). The prose is full of capitalised words
    ('Committee'), so names must be taken from BEFORE the relative-clause
    opener rather than matched across the whole clause. The cut is anchored on
    a leading comma so it can't eat a comma inside a name; "of whom" is
    optional and "who"/"whom" both close it off with \\b so it cannot match
    e.g. "who" inside a longer word.

    `head` is the raw name text (titles still embedded, caller's job to
    strip); `tail` is everything after the relative-clause opener, which is
    where a dissenter's own preferred direction is stated (or absent, when
    it's `unclear`). A group with no relative-clause opener at all yields
    `tail = ""`.

    This is the ONE place that group-splitting rule lives: `_count_dissenters`
    (a vote count) and `parse_dissent` (names + direction) both call it rather
    than each carrying its own copy -- two divergent copies of this rule
    already produced a wrong vote count once (2016's "each of whom").
    """
    groups = []
    for group in segment.split(";"):
        group = re.sub(r"^\s*and\s+", "", group.strip())
        parts = re.split(r",\s*(?:each\s+of\s+)?whom?\b", group, maxsplit=1)
        head = parts[0]
        tail = parts[1] if len(parts) > 1 else ""
        groups.append((head, tail))
    return groups


def _group_names(head: str) -> list[str]:
    """Names from one dissent group's head text, titles stripped."""
    head = _TITLES.sub("", head).rstrip(". ")
    return [p.strip() for p in re.split(r"\s+and\s+|,", head) if p.strip()]


def _count_dissenters(segment: str) -> int:
    """Count people in an 'against' clause. See `_split_dissent_groups`."""
    return sum(len(_group_names(head)) for head, _tail in _split_dissent_groups(segment))


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


def dissent_clause(paras: list) -> str | None:
    """The raw 'Voting against ...' clause text for a statement's
    paragraphs, or None when the statement has no against-clause (a
    unanimous vote).

    Most statements print the against-clause as its own 'vote_against'
    paragraph, but ~10 (2016, 2019, 2025) weld it onto the end of the
    'vote_for' paragraph instead -- split off here by finding the literal
    "Voting against" that `role_for` only recognises when it OPENS a
    paragraph.
    """
    against_text = next((p.text for p in paras if p.role == "vote_against"), None)
    if against_text is not None:
        return against_text
    for_text = next((p.text for p in paras if p.role == "vote_for"), None)
    if for_text is not None:
        halves = re.split(r"Voting against", for_text, maxsplit=1, flags=re.I)
        if len(halves) > 1:
            return "Voting against" + halves[1]
    return None


def parse_dissent(text: str) -> list[tuple[str, str]]:
    """One (name, direction) row per dissenter in an against-clause.

    Dissents within a single meeting can point in opposite directions
    (2019-09-18: Bullard preferred to lower while George and Rosengren
    preferred to maintain) -- this is why the return shape is a row per
    dissenter, not one direction per clause. `direction` is `unclear`,
    never a guess, when a group's own prose states no rate preference at
    all (2026-04-29's second group objects to bias-language inclusion, not
    the rate; 2020-09-16's Kaplan and Kashkari object to forward-guidance
    wording).
    """
    m = _DISSENT_OPEN.search(text)
    if not m:
        raise MeetingParseError("no dissent clause found")
    segment = text[m.end():]
    rows: list[tuple[str, str]] = []
    for head, tail in _split_dissent_groups(segment):
        names = _group_names(head)
        if not names:
            continue
        direction = _classify_direction(tail)
        rows.extend((name, direction) for name in names)
    if not rows:
        raise MeetingParseError("no dissenters found in against-clause")
    return rows


def _classify_direction(tail: str) -> str:
    m = _DIRECTION_RE.search(tail)
    if not m:
        return "unclear"
    word = m.group(1)
    if word is None:
        return "maintain"  # matched the "no change" alternative
    return _DIRECTION_WORD[word.lower()]


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
