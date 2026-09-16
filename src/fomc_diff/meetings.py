"""Structured facts extracted from a statement: vote, target range, dissent."""
from __future__ import annotations

import re

_DASH = r"[‐-―\-]"
_VOTE = re.compile(rf"by a (\d+)\s*{_DASH}\s*(\d+)\s*vote", re.I)
_NUM = r"\d+(?:-\d+/\d+)?"
_RANGE = re.compile(
    rf"target range for the federal funds rate at ({_NUM}) to ({_NUM}) percent",
    re.I)
_DISSENT = re.compile(r"were (.+?), who (.+)$", re.S)
_DIRECTIONS = ("raise", "lower", "maintain")


def parse_fraction(s: str) -> float:
    """'3-1/2' -> 3.5. Plain integers pass through."""
    s = s.strip()
    if "/" not in s:
        return float(s)
    whole, frac = s.split("-", 1)
    num, den = frac.split("/")
    return float(whole) + float(num) / float(den)


def parse_vote(html: str) -> tuple[int, int]:
    m = _VOTE.search(html)
    if not m:
        raise ValueError("no vote line found")
    return int(m.group(1)), int(m.group(2))


def parse_target_range(text: str) -> tuple[float, float]:
    m = _RANGE.search(text)
    if not m:
        raise ValueError("no target range found")
    return parse_fraction(m.group(1)), parse_fraction(m.group(2))


def parse_dissent(text: str) -> tuple[list[str], str]:
    m = _DISSENT.search(text)
    if not m:
        raise ValueError("no dissent clause found")
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
