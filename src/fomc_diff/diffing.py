"""Deterministic paragraph and word diffs between two statements."""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .parse import Paragraph


class DuplicateRoleError(ValueError):
    """Raised when a statement has two paragraphs sharing the same role.

    diff_statements aligns paragraphs by role via a role -> text dict; two
    paragraphs sharing a role would silently collapse into one entry (the
    dict keeps only the last), losing a paragraph with no error. This is
    reachable: ZIRP-era statements (2009-2015) carry both a decision
    paragraph and a forward-guidance paragraph, each containing "target
    range for the federal funds rate", so both tag `policy`.
    """


def _check_no_duplicate_roles(paragraphs: list[Paragraph], side: str) -> None:
    seen: set[str] = set()
    for p in paragraphs:
        if p.role in seen:
            raise DuplicateRoleError(
                f"duplicate role {p.role!r} in {side} statement "
                f"(paragraph index {p.index}); diff_statements cannot align "
                "paragraphs by role when a role appears more than once"
            )
        seen.add(p.role)


@dataclass(frozen=True)
class DiffRow:
    role: str
    change_type: str
    words_added: int
    words_removed: int
    word_diff: str


def word_diff(a: str, b: str) -> str:
    wa, wb = a.split(), b.split()
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb).get_opcodes():
        if tag == "equal":
            continue
        removed = " ".join(wa[i1:i2])
        added = " ".join(wb[j1:j2])
        if removed:
            parts.append(f"[-{removed}-]")
        if added:
            parts.append(f"[+{added}+]")
    return " ".join(parts)


def _counts(a: str, b: str) -> tuple[int, int]:
    wa, wb = a.split(), b.split()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb).get_opcodes():
        if tag == "equal":
            continue
        removed += i2 - i1
        added += j2 - j1
    return added, removed


def diff_statements(a: list[Paragraph], b: list[Paragraph]) -> list[DiffRow]:
    """Align by role, so a paragraph moving position is not read as a rewrite."""
    _check_no_duplicate_roles(a, "old")
    _check_no_duplicate_roles(b, "new")

    # dict.fromkeys (not set) preserves first-seen order deterministically;
    # a future "simplification" to set() would reintroduce nondeterministic
    # row order.
    roles = list(dict.fromkeys([p.role for p in a] + [p.role for p in b]))
    a_by = {p.role: p.text for p in a}
    b_by = {p.role: p.text for p in b}

    rows: list[DiffRow] = []
    for role in roles:
        old, new = a_by.get(role), b_by.get(role)
        if old is None and new is not None:
            rows.append(DiffRow(role, "added", len(new.split()), 0, f"[+{new}+]"))
        elif old is not None and new is None:
            rows.append(DiffRow(role, "removed", 0, len(old.split()), f"[-{old}-]"))
        elif old == new:
            rows.append(DiffRow(role, "unchanged", 0, 0, ""))
        else:
            added, removed = _counts(old, new)
            rows.append(DiffRow(role, "changed", added, removed, word_diff(old, new)))
    return rows
