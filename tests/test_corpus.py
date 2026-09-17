"""Corpus-wide gates.

The three gates below used to run only over the 21 hand-picked fixtures in
tests/fixtures/. That is why a mutation that gutted the fused-paragraph
exemption (exempting 19 of 21 fixtures instead of the one real fused
statement) and a mutation that deleted an `_ECONOMY_OPENINGS` anchor used by
4 real statements both left the fixture-level suite green. These tests read
the SHIPPED DATASET -- data/statements.csv, 89 documents / 479 rows -- and
recompute each paragraph's role live via `role_for`/`_opens_with_economic_
assessment`, rather than trusting the CSV's own `role` column, so a
regression in the classifier itself is caught even though the CSV is a
static, committed file.
"""
from __future__ import annotations

import collections
import csv
from pathlib import Path

from fomc_diff.parse import UNIQUE_ROLES, _opens_with_economic_assessment, role_for

REPO_ROOT = Path(__file__).parent.parent
STATEMENTS_CSV = REPO_ROOT / "data" / "statements.csv"


def _load_rows() -> list[dict]:
    if not STATEMENTS_CSV.exists():
        raise FileNotFoundError(
            f"{STATEMENTS_CSV} is missing. The corpus gates in this module "
            "must run against the shipped dataset, not fixtures, and must "
            "fail loudly rather than skip when it is absent."
        )
    with STATEMENTS_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _by_meeting(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        grouped[row["meeting_date"]].append(row)
    return grouped


def test_every_decision_statement_has_exactly_one_economy_paragraph():
    """Two documented exemptions, both by condition:
      - Desk directives (operational statements) carry no economic
        assessment at all.
      - The one statement that FUSES its assessment and its decision into
        one paragraph (2020-03-03) expresses only `policy` for it.

    Roles are recomputed from the row's own text via `role_for`, not read
    from the CSV's `role` column, so deleting any single `_ECONOMY_OPENINGS`
    anchor (including "Available indicators suggest", which 4 real
    statements depend on) turns this red even though the committed CSV
    itself is untouched.
    """
    for meeting_date, rows in _by_meeting(_load_rows()).items():
        classified = [(r, role_for(r["text"])) for r in rows]
        roles = [role for _, role in classified]
        if "directive" in roles:
            continue
        policy_text = next(
            (r["text"] for r, role in classified if role == "policy"), None)
        if policy_text is not None and _opens_with_economic_assessment(policy_text):
            continue          # fused paragraph; see docstring
        assert roles.count("economy") == 1, f"{meeting_date}: {roles}"


def test_the_fused_exemption_applies_to_exactly_one_meeting():
    """Locks the fused-paragraph exemption to the one real statement it
    covers (2020-03-03). Widening `_opens_with_economic_assessment` -- the
    single source of truth the exemption relies on -- to match more policy
    paragraphs turns this red as soon as a second meeting is counted."""
    fused = []
    for meeting_date, rows in _by_meeting(_load_rows()).items():
        policy_text = next(
            (r["text"] for r in rows if role_for(r["text"]) == "policy"), None)
        if policy_text is not None and _opens_with_economic_assessment(policy_text):
            fused.append(meeting_date)
    assert fused == ["2020-03-03"], fused


def test_no_recurring_paragraph_is_unclassified():
    """What must never be unclassified is a paragraph the Fed prints over and
    over, because that means an anchor has rotted. Real one-off episodic
    content (COVID, Ukraine, the 2023 banking-stress paragraphs) is allowed
    to recur a handful of times -- the threshold is 8, not 5: "The U.S.
    banking system is sound and resilient..." appears 6 times and "Russia's
    war against Ukraine..." 5 times in the real corpus, and neither is a rotted
    anchor."""
    counts = collections.Counter()
    for row in _load_rows():
        if row["role"] == "unclassified":
            counts[row["text"][:55]] += 1
    recurring = {t: n for t, n in counts.items() if n >= 8}
    assert not recurring, f"recurring unclassified paragraphs: {recurring}"


def test_no_duplicate_unique_roles_in_the_corpus():
    for meeting_date, rows in _by_meeting(_load_rows()).items():
        counts = collections.Counter(r["role"] for r in rows)
        dupes = {r: counts[r] for r in UNIQUE_ROLES if counts[r] > 1}
        assert not dupes, f"{meeting_date}: {dupes}"
