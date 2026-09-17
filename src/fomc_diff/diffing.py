"""Deterministic paragraph and word diffs between two statements."""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .parse import Paragraph, UNIQUE_ROLES


class DuplicateRoleError(ValueError):
    """Raised when a statement has two paragraphs sharing a UNIQUE_ROLES role.

    diff_statements aligns paragraphs by role via a role -> text dict; two
    paragraphs sharing a role would silently collapse into one entry (the
    dict keeps only the last), losing a paragraph with no error. This is
    reachable: ZIRP-era statements (2009-2015) carry both a decision
    paragraph and a forward-guidance paragraph, each containing "target
    range for the federal funds rate", so both tag `policy`.

    The check only covers UNIQUE_ROLES (policy, economy, inflation,
    vote_for, vote_against) -- roles the taxonomy guarantees appear at most
    once when the parse is correct, so a second one signals a real anchor
    collision. Every other role (unclassified, guidance, balance_sheet,
    mandate, ...) legitimately repeats within a statement -- episodic
    paragraphs (COVID, Ukraine, the 2023 banking-stress response) recur, and
    an expansive statement carries several balance-sheet paragraphs -- so
    those are exempt from this guard and indexed for alignment instead (see
    diff_statements' occurrence keying).
    """


def _check_no_duplicate_roles(paragraphs: list[Paragraph], side: str) -> None:
    seen: set[str] = set()
    for p in paragraphs:
        if p.role not in UNIQUE_ROLES:
            continue
        if p.role in seen:
            raise DuplicateRoleError(
                f"duplicate role {p.role!r} in {side} statement "
                f"(paragraph index {p.index}); diff_statements cannot align "
                "paragraphs by role when a role appears more than once"
            )
        seen.add(p.role)


def _keyed_roles(paragraphs: list[Paragraph]) -> list[tuple[str, str]]:
    """Return (alignment_key, text) pairs for `paragraphs`.

    A role's first occurrence keys as the bare role name; the second keys as
    `role#1`, the third as `role#2`, and so on. Bare-first-then-suffixed (not
    always-suffixed, and not suffixed only past some count) is what lets a
    role appearing once in one statement and twice in the other still align
    on its first occurrence: both sides' first paragraph keys as the bare
    role regardless of how many more of that role either side has.
    """
    counts: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    for p in paragraphs:
        n = counts.get(p.role, 0)
        key = p.role if n == 0 else f"{p.role}#{n}"
        counts[p.role] = n + 1
        out.append((key, p.text))
    return out


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
    """Align by role, so a paragraph moving position is not read as a rewrite.

    A role that repeats within a statement is aligned by occurrence: the
    first paragraph with that role keys as the bare role, the second as
    `role#1`, and so on (see _keyed_roles). DiffRow.role carries that key, so
    a repeated role shows up in output as e.g. `unclassified` and
    `unclassified#1` -- visible, not silently merged.
    """
    _check_no_duplicate_roles(a, "old")
    _check_no_duplicate_roles(b, "new")

    a_keyed = _keyed_roles(a)
    b_keyed = _keyed_roles(b)

    # dict.fromkeys (not set) preserves first-seen order deterministically;
    # a future "simplification" to set() would reintroduce nondeterministic
    # row order.
    roles = list(dict.fromkeys([k for k, _ in a_keyed] + [k for k, _ in b_keyed]))
    a_by = dict(a_keyed)
    b_by = dict(b_keyed)

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
