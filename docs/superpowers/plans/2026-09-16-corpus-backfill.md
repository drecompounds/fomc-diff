# Corpus Backfill 2016-2026 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch, parse, and commit every FOMC policy statement from 2016-01-27 to 2026-09-16 as a reproducible CSV dataset.

**Architecture:** A new `discover.py` reads the Fed's own listing pages to resolve statement URLs by label, replacing date-to-URL guessing. `parse.py` gains vote roles and a narrowed policy anchor. `meetings.py` gains a name-counting vote branch for the 2016-2025 era. `backfill.py` drives the whole corpus into CSVs.

**Tech Stack:** Python 3.11+, stdlib only (`re`, `html`, `urllib`, `csv`, `dataclasses`). pytest for tests. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-16-corpus-backfill-2016-2026-design.md`

## Global Constraints

- **Stdlib only.** No new runtime dependencies. No BeautifulSoup, no requests.
- **Empty is never quiet.** A parse that cannot find what it seeks raises a `FomcParseError` subclass. Never return a plausible wrong value; never write an empty table. This includes *confidently short* output — see Defect 1 in the spec.
- **All file I/O uses `encoding="utf-8"` explicitly.** Windows default is cp1252 and will corrupt or crash on Fed content. Cached raw documents are read and written as **bytes**.
- **No emoji or non-ASCII decoration in source files.** Fed text contains U+2010, U+2011, U+2013 and NBSP; preserve those in data, never introduce new ones in code.
- **Never construct a statement URL from a date.** Resolve via `discover.py`. `statement_url()` stays for the existing tests but is not used by the backfill.
- **Fetching is 1 request/second, cached.** Tests never hit the network; they use fixtures in `tests/fixtures/`.
- **Every new test must name the specific failure it detects** in its docstring, and must be disable-proofed by breaking the code it names.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/fomc_diff/discover.py` | **New.** Listing pages to `{meeting_date: url}`. The only module that decides what counts as a statement. |
| `src/fomc_diff/parse.py` | Modify. Vote roles, narrowed `policy` anchor, expanded taxonomy. |
| `src/fomc_diff/meetings.py` | Modify. Named-list vote branch, widened target range. |
| `src/fomc_diff/backfill.py` | **New.** Corpus driver, writes the CSVs. |
| `tests/test_discover.py` | **New.** |
| `tests/test_parse.py`, `tests/test_meetings.py` | Modify. |
| `tests/test_backfill.py` | **New.** |

Fixtures already committed and available:

`listing_fomchistorical2016.html`, `listing_fomccalendars.html`,
`statement_20160316.html`, `statement_20190918.html`, `statement_20191011.html`,
`statement_20200129.html`, `statement_20200303.html`, `statement_20200323.html`,
`statement_20200916.html`, `statement_20211215.html`, `statement_20250917.html`,
`statement_20260617.html`, `statement_20260729.html`, `statement_20260916.html`

---

### Task 1: `discover.py` — resolve statements by label

**Files:**
- Create: `src/fomc_diff/discover.py`
- Create: `tests/test_discover.py`

**Interfaces:**
- Consumes: `fomc_diff.errors.FomcParseError`
- Produces: `class DiscoveryError(FomcParseError)`, `def statement_links(html: str) -> dict[date, str]`, `STATEMENT_LABELS`, `KNOWN_NON_STATEMENT_LABELS`

**Context:** The `a.htm` suffix means "first press release that day," not "the policy statement." `monetary20160127b.htm` is the Statement on Longer-Run Goals published the same day as the January statement. The anchor label on the Fed's own listing page is the only reliable identity signal.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from pathlib import Path

import pytest

from fomc_diff.discover import DiscoveryError, statement_links

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_january_2016_resolves_to_the_statement_not_the_longer_run_goals():
    """monetary20160127b.htm is the Statement on Longer-Run Goals, published the
    same day. Choosing by URL suffix would be a coin flip; choosing by label is
    not. This is the wrong-document guard."""
    links = statement_links(_html("listing_fomchistorical2016.html"))
    url = links[date(2016, 1, 27)]
    assert url.endswith("monetary20160127a.htm")
    assert "20160127b" not in url


def test_historical_page_yields_eight_statements_for_2016():
    links = statement_links(_html("listing_fomchistorical2016.html"))
    assert len([d for d in links if d.year == 2016]) == 8


def test_current_calendar_uses_the_html_label():
    """The historical pages label statement links 'Statement'; the current
    calendar labels the same thing 'HTML'. Accepting only one silently empties
    half the corpus."""
    links = statement_links(_html("listing_fomccalendars.html"))
    assert date(2026, 9, 16) in links
    assert links[date(2026, 9, 16)].endswith("monetary20260916a.htm")


def test_unknown_label_raises_rather_than_guessing():
    """A ninth Fed document type must be a red test, not a silent inclusion or
    a silent omission."""
    html = ('<a href="/newsevents/pressreleases/monetary20260101a.htm">'
            'Some New Document Type</a>')
    with pytest.raises(DiscoveryError, match="unrecognised label"):
        statement_links(html)


def test_known_non_statement_labels_are_dropped_silently():
    html = ('<a href="/newsevents/pressreleases/monetary20260101b.htm">'
            'Statement on Longer-Run Goals and Monetary Policy Strategy</a>')
    assert statement_links(html) == {}


def test_urls_are_absolute():
    links = statement_links(_html("listing_fomchistorical2016.html"))
    assert all(u.startswith("https://www.federalreserve.gov/") for u in links.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/test_discover.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'fomc_diff.discover'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/test_discover.py -q`
Expected: 6 passed

- [ ] **Step 5: Disable-proof**

Temporarily change `STATEMENT_LABELS` to `frozenset({"Statement"})`. Confirm `test_current_calendar_uses_the_html_label` fails. Then remove the `raise DiscoveryError` and confirm `test_unknown_label_raises_rather_than_guessing` fails. Restore both.

- [ ] **Step 6: Commit**

```bash
git add src/fomc_diff/discover.py tests/test_discover.py
git commit -m "Add discover.py: resolve statements by label, not URL suffix"
```

---

### Task 2: `discover.py` — corpus assembly and count guard

**Files:**
- Modify: `src/fomc_diff/discover.py`
- Modify: `tests/test_discover.py`

**Interfaces:**
- Consumes: `statement_links` from Task 1
- Produces: `def listing_urls(through_year: int) -> list[str]`, `def build_corpus(pages: dict[str, str], current_year: int) -> dict[date, str]`

**Context:** `build_corpus` takes already-fetched page HTML (keyed by URL) so it stays offline and testable. The caller does the fetching.

- [ ] **Step 1: Write the failing test**

```python
def test_build_corpus_merges_both_page_shapes():
    pages = {
        "hist2016": _html("listing_fomchistorical2016.html"),
        "calendars": _html("listing_fomccalendars.html"),
    }
    corpus = build_corpus(pages, current_year=2026)
    assert len([d for d in corpus if d.year == 2016]) == 8
    assert len([d for d in corpus if d.year == 2026]) == 6


def test_a_complete_year_short_of_eight_statements_raises():
    """Eight scheduled meetings a year is a fact about the FOMC. A listing-page
    layout change that silently halved the corpus would otherwise be invisible
    until someone noticed the dataset was thin."""
    pages = {"only_one": '<a href="/newsevents/pressreleases/monetary20200101a.htm">Statement</a>'}
    with pytest.raises(DiscoveryError, match="2020"):
        build_corpus(pages, current_year=2026)


def test_the_in_progress_year_is_exempt_from_the_count_guard():
    """2026 has six statements so far and must not raise for it."""
    pages = {"only_one": '<a href="/newsevents/pressreleases/monetary20260101a.htm">Statement</a>'}
    assert len(build_corpus(pages, current_year=2026)) == 1


def test_listing_urls_covers_the_whole_span():
    urls = listing_urls(through_year=2026)
    assert any("fomchistorical2016.htm" in u for u in urls)
    assert any("fomchistorical2020.htm" in u for u in urls)
    assert any("fomccalendars.htm" in u for u in urls)
    assert not any("fomchistorical2021.htm" in u for u in urls)
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL, `ImportError: cannot import name 'build_corpus'`

- [ ] **Step 3: Implement**

```python
import collections

FIRST_YEAR = 2016
LAST_HISTORICAL_YEAR = 2020   # 2021+ live on fomccalendars.htm
MIN_MEETINGS_PER_YEAR = 8


def listing_urls(through_year: int) -> list[str]:
    urls = [f"{BASE}/monetarypolicy/fomchistorical{y}.htm"
            for y in range(FIRST_YEAR, LAST_HISTORICAL_YEAR + 1)]
    if through_year > LAST_HISTORICAL_YEAR:
        urls.append(f"{BASE}/monetarypolicy/fomccalendars.htm")
    return urls


def build_corpus(pages: dict[str, str], current_year: int) -> dict[date, str]:
    """Merge every listing page into one date-to-URL map, and sanity-check it.

    `pages` maps an identifier to already-fetched HTML, so this stays offline.
    """
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
        if year >= current_year:
            continue          # in progress, incomplete by definition
        if n < MIN_MEETINGS_PER_YEAR:
            raise DiscoveryError(
                f"{year} yielded only {n} statements; the FOMC holds at least "
                f"{MIN_MEETINGS_PER_YEAR} scheduled meetings a year, so the "
                "listing page shape has probably changed")
    return corpus
```

- [ ] **Step 4: Run to verify pass**

Expected: 10 passed in `tests/test_discover.py`

- [ ] **Step 5: Disable-proof**

Remove the `if n < MIN_MEETINGS_PER_YEAR: raise`. Confirm `test_a_complete_year_short_of_eight_statements_raises` fails. Restore.

- [ ] **Step 6: Commit**

```bash
git add src/fomc_diff/discover.py tests/test_discover.py
git commit -m "Add corpus assembly with per-year count guard"
```

---

### Task 3: `parse.py` — vote roles ahead of policy

**Files:**
- Modify: `src/fomc_diff/parse.py:115-129` (`role_for`)
- Modify: `tests/test_parse.py`

**Interfaces:**
- Produces: roles `vote_for` and `vote_against`, replacing `dissent`

**Context:** In 2016-2025 "Voting for" and "Voting against" are one paragraph, and it contains "target range for the federal funds rate" because the dissenter's preferred alternative names it. `role_for` therefore tagged it `policy`. In 2020-09-16 they are two paragraphs. In 2026 only the dissent paragraph appears. Two roles handle all three shapes.

The existing `dissent` role is renamed to `vote_against`. Update the existing `test_roles_assigned_by_anchor_not_position` and `test_september_2026_fixture_end_to_end` accordingly.

- [ ] **Step 1: Write the failing test**

```python
def test_combined_voting_paragraph_is_a_vote_not_a_policy_paragraph():
    """2019-09-18 puts 'Voting for' and 'Voting against' in ONE paragraph, and
    that paragraph contains 'target range for the federal funds rate' because
    Bullard's preferred alternative names it. Tagged policy, it collides with
    the real policy paragraph and the dissent is never seen."""
    paras = parse_statement(_html("statement_20190918.html"))
    voting = [p for p in paras if p.text.startswith("Voting")]
    assert len(voting) == 1
    assert voting[0].role == "vote_for"
    assert all(p.role != "policy" for p in voting)


def test_split_voting_paragraphs_get_distinct_roles():
    """2020-09-16 splits them into two paragraphs. One role for both would
    produce a duplicate and break role-aligned diffing."""
    roles = [p.role for p in parse_statement(_html("statement_20200916.html"))
             if p.text.startswith("Voting")]
    assert roles == ["vote_for", "vote_against"]


def test_2026_standalone_dissent_is_vote_against():
    roles = [p.role for p in parse_statement(_html("statement_20260729.html"))]
    assert "vote_against" in roles


def test_no_duplicate_vote_roles_anywhere_in_the_fixtures():
    import collections
    for name in ("statement_20190918.html", "statement_20200916.html",
                 "statement_20211215.html", "statement_20250917.html",
                 "statement_20160316.html", "statement_20260729.html"):
        counts = collections.Counter(
            p.role for p in parse_statement(_html(name)))
        assert counts["vote_for"] <= 1, name
        assert counts["vote_against"] <= 1, name
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL on `voting[0].role == "vote_for"` (currently `policy`)

- [ ] **Step 3: Implement** — replace the top of `role_for`

```python
def role_for(text: str) -> str:
    # The vote-announcement line ("...approved the following statement for
    # release by a 9-3 vote:") is where parse_vote reads the count.
    if "approved the following statement for release" in text:
        return "vote"
    # BOTH vote checks MUST precede `policy`. In 2016-2025 the voting paragraph
    # contains "target range for the federal funds rate", because the
    # dissenter's preferred alternative names it -- so `policy` would swallow
    # the entire vote record. This is the same trap that already required
    # dissent-before-policy; its scope was simply too narrow.
    if text.startswith("Voting for"):
        return "vote_for"
    if text.startswith("Voting against"):
        return "vote_against"
    if "target range for the federal funds rate" in text:
        return "policy"
    if text.startswith("Inflation"):
        return "inflation"
    if "Economic activity" in text:
        return "economy"
    return "unclassified"
```

Then update the two existing tests that name `dissent`:
- `tests/test_parse.py::test_roles_assigned_by_anchor_not_position` — last element becomes `"vote_against"`
- the `role_for` parametrize case `("Voting against the monetary policy action were Beth M. Hammack.", "dissent")` becomes `"vote_against"`

- [ ] **Step 4: Run the FULL suite**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q`

`tests/test_diffing.py:32-33` references the old role name and MUST be updated:

```python
    assert by_role["vote_against"].change_type == "added"
    assert "Hammack" in by_role["vote_against"].word_diff
```

(`tests/test_quantifiers.py:34` contains the word "dissented" in fixture prose — that is unrelated and must NOT be touched.)

Expected after that edit: all pass.

- [ ] **Step 5: Disable-proof**

Move the two vote checks BELOW the `policy` check. Confirm `test_combined_voting_paragraph_is_a_vote_not_a_policy_paragraph` fails. Restore.

- [ ] **Step 6: Commit**

```bash
git add src/fomc_diff/parse.py tests/
git commit -m "Split vote roles and check them before policy"
```

---

### Task 4: `parse.py` — narrow `policy`, widen the taxonomy

**Files:**
- Modify: `src/fomc_diff/parse.py`
- Modify: `tests/test_parse.py`

**Interfaces:**
- Produces: roles `directive`, `guidance`, `mandate`, `balance_sheet`, `outlook_risk`, `commitment`

**Context:** 34 documents carry two paragraphs containing "target range for the federal funds rate": the decision, and the reaction function ("In determining the timing and size of future adjustments to..."). They are different paragraphs, not duplicates. `policy` must require a decision verb.

Use a regex `Committee decided\s+(?:today\s+)?to` for whitespace robustness. **Note:** an earlier version of this plan claimed the literal substring `"Committee decided to"` misses 2020-03-03's "decided today to lower". That is false — "to" is a prefix of "today", so the literal matches coincidentally. Do not write a disable-proof asserting otherwise; it cannot go red.

**This task carries the one open design question in the spec: the `economy` anchor.** Its wording varies ("Information received since the Federal Open Market Committee met in...", "Recent indicators suggest that...", "Indicators of economic activity and employment...", "Available indicators suggest..."). Too loose and it collides with other paragraphs; too tight and it misses eras. Steps 3-4 iterate until Step 5's two corpus-level tests pass. Those tests are the gate, not a guess made up front.

- [ ] **Step 1: Write the failing test**

```python
import collections

UNIQUE_ROLES = ("policy", "economy", "inflation", "vote_for", "vote_against")


def test_reaction_function_is_guidance_not_a_second_policy_paragraph():
    """2016-03-16 has both 'the Committee decided to maintain the target
    range...' and 'In determining the timing and size of future adjustments to
    the target range...'. Both match the bare anchor phrase."""
    paras = parse_statement(_html("statement_20160316.html"))
    assert len([p for p in paras if p.role == "policy"]) == 1
    assert any(p.role == "guidance" for p in paras)


def test_decided_today_still_counts_as_a_decision():
    """2020-03-03 reads 'decided TODAY to lower'. A literal 'Committee decided
    to' substring misses the emergency 50bp cut entirely."""
    paras = parse_statement(_html("statement_20200303.html"))
    policy = [p for p in paras if p.role == "policy"]
    assert len(policy) == 1
    assert "1/2 percentage point" in policy[0].text


def test_desk_directives_are_not_policy_decisions():
    """2019-10-11 (reserve management) and 2020-03-23 (unlimited purchases) are
    operational directives with no rate decision. Tagging them policy would
    file them as rate decisions in the spine."""
    for name in ("statement_20191011.html", "statement_20200323.html"):
        roles = [p.role for p in parse_statement(_html(name))]
        assert "directive" in roles, name


def test_no_duplicate_unique_roles_in_any_fixture():
    """Anchor collisions are the defect class this task exists to remove."""
    for f in sorted(FIX.glob("statement_*.html")):
        counts = collections.Counter(
            p.role for p in parse_statement(f.read_text(encoding="utf-8")))
        dupes = {r: counts[r] for r in UNIQUE_ROLES if counts[r] > 1}
        assert not dupes, f"{f.name}: {dupes}"


def test_recurring_paragraphs_are_all_classified():
    """Replaces the original spec's 'zero unclassified' test, which can never
    pass -- COVID, Ukraine and the 2023 banking-stress paragraphs are genuine
    one-offs. What must never be unclassified is a paragraph the Fed prints
    over and over, because that means an anchor has rotted."""
    openings = collections.Counter()
    for f in sorted(FIX.glob("statement_*.html")):
        for p in parse_statement(f.read_text(encoding="utf-8")):
            if p.role == "unclassified":
                openings[p.text[:55]] += 1
    recurring = {t: n for t, n in openings.items() if n >= 5}
    assert not recurring, f"recurring unclassified paragraphs: {recurring}"
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL on the duplicate-`policy` and `directive` assertions.

- [ ] **Step 3: Implement the anchors**

```python
# "decided to" is not enough: 2020-03-03 reads "decided TODAY to lower".
_DECIDED = re.compile(r"Committee\s+decided\s+(?:today\s+)?to", re.I)
_DIRECTS = re.compile(r"directs the Desk", re.I)
```

and in `role_for`, after the vote checks:

```python
    if _DECIDED.search(text) and "target range for the federal funds rate" in text:
        return "policy"
    if _DIRECTS.search(text):
        return "directive"
    if ("In determining the timing and size of future adjustments" in text
            or "In assessing the appropriate stance of monetary policy" in text):
        return "guidance"
    if "path of the economy" in text:
        return "outlook_risk"
    if "committed to using its full range of tools" in text:
        return "commitment"
    if ("seeks to achieve maximum employment" in text
            or "Consistent with its statutory mandate" in text):
        return "mandate"
    if "reinvest" in text or "holdings of Treasury securities" in text:
        return "balance_sheet"
    if "Economic activity" in text:
        return "economy"
    if text.startswith("Inflation"):
        return "inflation"
    return "unclassified"
```

- [ ] **Step 4: Calibrate the `economy` anchor**

Run the two corpus-level tests. Widen the `economy` anchor until
`test_recurring_paragraphs_are_all_classified` passes **without**
`test_no_duplicate_unique_roles_in_any_fixture` regressing. Candidate
openings to cover, all observed: "Information received since the Federal Open
Market Committee met in", "Recent indicators suggest", "Recent indicators point
to", "Indicators of economic activity and employment", "Available indicators
suggest", "Economic activity". Prefer an explicit tuple of opening phrases over
a loose substring — a loose `"economic activity" in text` collides on 9
documents.

- [ ] **Step 5: Run the FULL suite**

Expected: all pass.

- [ ] **Step 6: Disable-proof**

Change `_DECIDED` back to the literal `"Committee decided to" in text`. Confirm `test_decided_today_still_counts_as_a_decision` fails. Then remove the `directive` branch and confirm `test_desk_directives_are_not_policy_decisions` fails. Restore both.

- [ ] **Step 7: Commit**

```bash
git add src/fomc_diff/parse.py tests/test_parse.py
git commit -m "Narrow the policy anchor and widen the role taxonomy"
```

---

### Task 5: `meetings.py` — count names when no vote line is printed

**Files:**
- Modify: `src/fomc_diff/meetings.py`
- Modify: `tests/test_meetings.py`

**Interfaces:**
- Consumes: `parse_statement`, roles `vote_for`/`vote_against` from Tasks 3-4
- Produces: `parse_vote(html) -> tuple[int, int]` (unchanged signature, new branch)

**Context:** `by a N-M vote` is absent from every statement 2016-2025 and present in only 3 of 6 in 2026. It is a 2026 novelty, not a pre-2016 boundary. There is NO document carrying both forms, so the two branches cannot be cross-validated against each other — counts below are verified **by hand** from the fixture text.

Hand-verified ground truth:

| Fixture | For | Against | Shape |
|---|---|---|---|
| `statement_20190918.html` | 7 | 3 | combined paragraph; 3 dissenters in 2 clauses |
| `statement_20211215.html` | 11 | 0 | no against-clause at all |
| `statement_20250917.html` | 11 | 1 | singular "Voting against this action **was**" |
| `statement_20200916.html` | 8 | 2 | vote_for and vote_against in separate paragraphs |
| `statement_20160316.html` | 9 | 1 | "Voting for the **FOMC** monetary policy action were**:**" |

Separator hazards, all present in the fixtures:
- 2019 mixes separators: `"Powell, Chair, John C. Williams, Vice Chair; Bowman; ..."` — a comma after "Chair", semicolons elsewhere
- 2016 adds "FOMC" and a trailing colon to the opening phrase
- titles `Chair`, `Vice Chair`, `Vice Chairman`, `Chairman` are appositives, never separate voters
- the against side embeds prose: `"James Bullard, who preferred ... percent; and Esther L. George and Eric S. Rosengren, who preferred ..."`. Counting capitalised words there over-counts on "Committee". Split on `;`, take the text **before** `", who"`, then split on `" and "`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from fomc_diff.meetings import parse_vote

@pytest.mark.parametrize("name,expected", [
    ("statement_20190918.html", (7, 3)),
    ("statement_20211215.html", (11, 0)),
    ("statement_20250917.html", (11, 1)),
    ("statement_20200916.html", (8, 2)),
    ("statement_20160316.html", (9, 1)),
])
def test_named_list_vote_counts(name, expected):
    """Counts verified by hand from the fixture text. No statement carries both
    a printed count and a named list, so there is nothing to cross-check
    against -- these numbers are the ground truth."""
    assert parse_vote(_html(name)) == expected


def test_unanimous_vote_is_a_fact_not_a_parse_failure():
    """2021-12-15 has no against-clause. Zero dissents must come back as 0, not
    raise, and not be confused with 'could not find the vote'."""
    assert parse_vote(_html("statement_20211215.html")) == (11, 0)


def test_titles_are_not_counted_as_voters():
    """'Jerome H. Powell, Chair, John C. Williams, Vice Chair' is two people.
    Counting comma-separated segments naively makes it four."""
    assert parse_vote(_html("statement_20190918.html"))[0] == 7


def test_counted_era_still_uses_the_printed_line():
    """2026 prints 'by a 9-3 vote'. That branch must not regress."""
    assert parse_vote(_html("statement_20260729.html")) == (9, 3)
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL, `MeetingParseError` on every named-list fixture.

- [ ] **Step 3: Implement**

```python
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


def parse_vote(html: str) -> tuple[int, int]:
    """Vote counts, from the printed line when the Fed prints one, else by
    counting the names it lists.

    'by a N-M vote' appears only from 2026. For 2016-2025 the Committee prints
    a named roll instead, so the count must be derived.
    """
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
```

- [ ] **Step 4: Run to verify pass**

Expected: all parametrized cases pass. If a count is off by one, print the split segments and compare against the hand-verified table above — do not adjust the expected values.

- [ ] **Step 5: Disable-proof**

Remove the `_TITLES.sub` call in `_count_names`. Confirm `test_titles_are_not_counted_as_voters` fails (7 becomes 9). Restore. Then make `_count_dissenters` return `len(segment.split(";"))`. Confirm the 2019 case fails (3 becomes 2). Restore.

- [ ] **Step 6: Commit**

```bash
git add src/fomc_diff/meetings.py tests/test_meetings.py
git commit -m "Derive vote counts from the named roll for 2016-2025"
```

---

### Task 6: `meetings.py` — widen the target range parser

**Files:**
- Modify: `src/fomc_diff/meetings.py` (`_RANGE`)
- Modify: `tests/test_meetings.py`

**Context:** `parse_target_range` fails on 15 of 89 documents. The spec's stated cause — ZIRP's "0 to 1/4 percent" — is **wrong**; 2021-12-15 parses correctly today. The two real causes, both measured:

1. **U+2011 NON-BREAKING HYPHEN.** The Fed writes "1‑1/2" and "4‑1/4" with U+2011, not ASCII hyphen, inconsistently and sometimes twice in one sentence ("at 1‑1/2 to 1-3/4 percent" mixes both). `_NUM` admits only `\d+-\d+/\d+` with ASCII `-`, and `parse_fraction` splits on ASCII `-` too. **Both** must accept the U+2010-U+2015 family. `meetings.py` already has a `_DASH` class for exactly this reason on `_VOTE`; reuse it rather than writing a second one.

2. **Inline markup.** `parse_target_range` takes **raw HTML**, and 2026-09-16 reads `rate by 1/4 percentage point<strong> </strong>to 3-3/4<strong> </strong>to 4 percent`. The tags sit inside the phrase and break the match even though the text is pure ASCII.

Cause 2 is the important one: it is the third occurrence of the same defect class (`parse_vote` needed `_html.unescape`; `sep.py` needed the en-dash class). **Fix it structurally** — `parse_target_range` should read the `policy` paragraph's already-cleaned text via `parse_statement` rather than raw HTML, the same way Task 5's `parse_vote` named branch does. Keep accepting a raw-HTML string at the public boundary so existing callers do not break.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("name,expected", [
    ("statement_20200129.html", (1.5, 1.75)),
    ("statement_20200303.html", (1.0, 1.25)),
    ("statement_20211215.html", (0.0, 0.25)),
    ("statement_20250917.html", (4.0, 4.25)),
    ("statement_20260916.html", (3.75, 4.0)),
])
def test_target_range_across_eras(name, expected):
    """Two real causes, both measured. 2020-01-29 and 2025-09-17 write the
    fraction with U+2011 NON-BREAKING HYPHEN, which the ASCII-only _NUM
    rejects. 2026-09-16 is pure ASCII but carries '<strong> </strong>' INSIDE
    the phrase, which breaks a regex run against raw HTML.

    2021-12-15 (ZIRP, '0 to 1/4 percent') is in this list as a REGRESSION
    guard: it already passes today, and the spec was wrong to blame it."""
    assert parse_target_range(_html(name)) == expected


def test_non_breaking_hyphen_is_read_as_a_fraction():
    """Isolates cause 1 from cause 2, so a fix for one cannot appear to fix
    both. U+2011 must parse identically to ASCII hyphen."""
    from fomc_diff.meetings import parse_fraction
    assert parse_fraction("1‑1/2") == 1.5
    assert parse_fraction("1-1/2") == 1.5


def test_inline_markup_inside_the_phrase_does_not_defeat_the_match():
    """Isolates cause 2. This exact shape is live in the 2026-09-16 statement."""
    html = ('<div id="article"><p>The Committee decided to raise the target '
            'range for the federal funds rate by 1/4 percentage point'
            '<strong> </strong>to 3-3/4<strong> </strong>to 4 percent.</p>'
            '<p>Economic activity is expanding.</p>'
            '<p>Inflation remains elevated.</p></div>')
    assert parse_target_range(html) == (3.75, 4.0)


def test_unparseable_range_raises_rather_than_returning_zero():
    """A range of 0 to 0 is a plausible-looking wrong answer, and ZIRP makes it
    look legitimate. Absence must raise."""
    with pytest.raises(MeetingParseError):
        parse_target_range("<html><body><p>No range here.</p></body></html>")
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL on at least the ZIRP and 2020 cases.

- [ ] **Step 3: Implement**

1. Reuse the existing `_DASH` class in `meetings.py` (already `[U+2010-U+2015, ASCII -]`, with a comment explaining why the trailing ASCII `\-` is load-bearing) inside `_NUM`, so `\d+-\d+/\d+` becomes dash-family-aware. **Do not write a second dash class.**
2. Make `parse_fraction` split on the same `_DASH` class instead of ASCII `-`.
3. Make `parse_target_range` read the `policy` paragraph's cleaned text:

```python
def parse_target_range(text: str) -> tuple[float, float]:
    """Accepts raw HTML or plain text.

    Raw HTML is routed through parse_statement first: the Fed puts
    "<strong> </strong>" INSIDE the phrase (live in the 2026-09-16 statement),
    and a regex run against raw markup cannot match across it.
    """
    haystack = text
    if "<" in text:
        try:
            paras = parse_statement(text)
        except ArticleContainerError:
            paras = []
        haystack = " ".join(
            p.text for p in paras if p.role in ("policy", "directive")) or text
    m = _RANGE.search(haystack)
    if not m:
        raise MeetingParseError("no target range found")
    return parse_fraction(m.group(1)), parse_fraction(m.group(2))
```

Note `parse_statement` is already imported by Task 5; `parse.py` imports nothing from `meetings.py`, so there is no import cycle.

- [ ] **Step 4: Run the FULL suite** — expected: all pass.

- [ ] **Step 5: Disable-proof — each cause separately**

Revert `_NUM` to ASCII-only `-`; confirm `test_non_breaking_hyphen_is_read_as_a_fraction` and the 2025-09-17 case fail, while 2026-09-16 still passes. Restore. Then make `parse_target_range` search `text` directly again; confirm `test_inline_markup_inside_the_phrase_does_not_defeat_the_match` and 2026-09-16 fail, while 2025-09-17 still passes. Restore.

Proving them independently matters: a single fix that made all five pass would leave you unable to tell which cause it addressed.

- [ ] **Step 6: Commit**

```bash
git add src/fomc_diff/meetings.py tests/test_meetings.py
git commit -m "Widen target range parsing across eras"
```

---

### Task 7: `backfill.py` — drive the corpus into CSVs

**Files:**
- Create: `src/fomc_diff/backfill.py`
- Create: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `discover.build_corpus`, `discover.listing_urls`, `fetch.fetch`, `parse.parse_statement`, `diffing.diff_statements`, `meetings.parse_vote`, `meetings.parse_target_range`, `meetings.derive_decision`
- Produces: `def build_rows(documents: dict[date, str]) -> tuple[list, list, list]`, `def run(cache_dir, out_dir, *, current_year) -> None`

**Context:** `build_rows` takes `{date: html}` so it is fully offline and testable. `run` does discovery, fetching and writing. `statement_type` is `operational` when a statement has a `directive` paragraph and no `policy` paragraph, else `decision`. Only `decision` rows require a vote and a target range.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from fomc_diff.backfill import build_rows

def _docs(*stamps):
    return {date(int(s[:4]), int(s[4:6]), int(s[6:])):
            _html(f"statement_{s}.html") for s in stamps}


def test_operational_statements_are_labelled_and_need_no_vote():
    """2020-03-23 is a Desk directive with no rate decision. Requiring a policy
    paragraph would either raise on it or file it as a rate decision."""
    meetings, _, _ = build_rows(_docs("20200323"))
    assert meetings[0]["statement_type"] == "operational"
    assert meetings[0]["vote_for"] is None


def test_decision_statements_carry_vote_and_range():
    meetings, _, _ = build_rows(_docs("20250917"))
    row = meetings[0]
    assert row["statement_type"] == "decision"
    assert (row["vote_for"], row["vote_against"]) == (11, 1)
    assert (row["target_lower"], row["target_upper"]) == (4.0, 4.25)


def test_a_decision_row_missing_its_policy_paragraph_raises():
    """The narrowed policy anchor must fail loudly in a new era, not write a
    row with empty columns."""
    import pytest
    from fomc_diff.errors import FomcParseError
    with pytest.raises(FomcParseError):
        build_rows({date(2026, 1, 1): "<div id=\"article\"><p>The Committee "
                                      "met and adjourned promptly.</p>"
                                      "<p>Nothing else happened at all.</p>"
                                      "<p>A third filler paragraph.</p></div>"})


def test_decision_is_derived_from_the_range_not_the_prose():
    meetings, _, _ = build_rows(_docs("20250917", "20260916"))
    by_date = {m["meeting_date"]: m for m in meetings}
    assert by_date[date(2026, 9, 16)]["decision"] == "hike"


def test_diffs_are_produced_for_consecutive_pairs_only():
    _, _, diffs = build_rows(_docs("20260617", "20260729", "20260916"))
    pairs = {(d["from_date"], d["to_date"]) for d in diffs}
    assert (date(2026, 6, 17), date(2026, 9, 16)) not in pairs
    assert (date(2026, 6, 17), date(2026, 7, 29)) in pairs


def test_statements_table_has_one_row_per_paragraph():
    meetings, statements, _ = build_rows(_docs("20250917"))
    assert len(statements) == len(parse_statement(_html("statement_20250917.html")))
    assert all(s["meeting_date"] == date(2025, 9, 17) for s in statements)
```

- [ ] **Step 2: Run to verify it fails**

Expected: `ModuleNotFoundError: No module named 'fomc_diff.backfill'`

- [ ] **Step 3: Implement**

Write `build_rows` to, for each date in sorted order: parse paragraphs; determine `statement_type`; for `decision` rows parse vote and range and raise via `FomcParseError` if the `policy` paragraph is absent; derive `decision` by comparing `target_upper` to the previous **decision** row; emit `statements` rows per paragraph; and emit `diffs` rows for each consecutive pair via `diff_statements`. Then write `run()` to call `listing_urls`/`fetch`/`build_corpus`, fetch each statement, and write the four CSVs via `tables.py` (which already refuses to write an empty table).

- [ ] **Step 4: Run the FULL suite** — expected: all pass.

- [ ] **Step 5: Add the year-contiguity check to `run()`**

Pre-flight Finding 1: `build_corpus`'s per-year minimum counts only years that
APPEAR. A year missing entirely — a listing page that failed to fetch, or whose
layout changed so no anchor matched — produces no key, so the guard never
inspects it. `run()` is the only caller that knows the full intended page set,
so the check belongs here:

```python
years = {d.year for d in corpus}
expected = set(range(discover.FIRST_YEAR, current_year + 1))
missing = expected - years
if missing:
    raise DiscoveryError(
        f"no statements discovered for {sorted(missing)}; a listing page "
        "probably failed to parse. Refusing to write a corpus with a hole in it.")
```

```python
def test_a_missing_year_is_refused_rather_than_written():
    """A year absent entirely produces no per-year count, so build_corpus's
    minimum cannot see it. Without this, a failed listing page ships a corpus
    with a silent hole."""
    import pytest
    from fomc_diff.discover import DiscoveryError
    with pytest.raises(DiscoveryError, match="2017"):
        _run_with_corpus({date(2016, 3, 16): "...", date(2026, 9, 16): "..."})
```

- [ ] **Step 6: Disable-proof**

Make `statement_type` always `"decision"`. Confirm `test_operational_statements_are_labelled_and_need_no_vote` fails. Restore. Then remove the contiguity check and confirm `test_a_missing_year_is_refused_rather_than_written` fails. Restore.

- [ ] **Step 7: Run the real backfill and commit the data**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m fomc_diff.backfill --out data/
```
Expect 89 meetings. Verify `data/meetings.csv` has 89 rows plus a header, and that no column is wholly empty.

```bash
git add src/fomc_diff/backfill.py tests/test_backfill.py data/
git commit -m "Add backfill driver and the committed 2016-2026 dataset"
```

---

### Task 8: README — correct the claims the corpus refuted

**Files:**
- Modify: `README.md`

**Context:** Three statements in the README are now wrong or overstated.

- [ ] **Step 1: Make the edits**

1. **"Pre-2016 statement format"** in the "Not built yet" list is wrong and the item is now done. The named-list vote format runs **2016-2025**; the printed count is the 2026 novelty. Remove the item and say so in the status section.
2. **"Duplicate-role alignment"** item: resolved by the narrowed anchors and split vote roles. Remove.
3. **"Empty is never quiet"** must be qualified. It held for parses that raised, but `_is_boilerplate` deleted the lead paragraph of 86 of 89 documents and the 2020-03-03 rate decision outright — output that was neither empty nor loud, but *confidently short*. State that plainly and note the minimum-paragraph guard that now backs the claim. This is the project's credibility; do not soften it.
4. Update **Status**: corpus is 2016-2026, 89 statements, N tests.
5. Update the **module table** with `discover.py` and `backfill.py`.
6. Add a **Dataset** section describing the four CSVs and their columns.

- [ ] **Step 2: Verify the claims**

Every number in the README must match the suite and the committed CSVs. Run the suite and `wc -l data/*.csv` and reconcile.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Correct README claims the corpus refuted"
```

---

## Self-Review

**Spec coverage.** Defect 1 fixed pre-plan (`ce04e7d`). Defect 2 -> Tasks 1-2. Defect 3 -> Task 3. Defect 4 -> Task 5. Defect 5 -> Task 4. `statement_type` -> Task 7. Spec tests 4/5/6 -> Task 1-2; 7/8 -> Tasks 3, 5; 9/10 -> Task 4; 11 -> Task 7; 12 -> Task 7 Step 6. Spec tests 1/2/3 landed in `ce04e7d`.

**Type consistency.** `statement_links` and `build_corpus` both return `dict[date, str]`. `parse_vote` keeps `tuple[int, int]`. `build_rows` returns three lists of dicts, consumed only by `run`.

**Known gap carried deliberately.** The `economy` anchor is not specified as a literal in Task 4; it is calibrated in Step 4 against two corpus-level gate tests. This is the one place the plan asks for judgment rather than transcription, and it is called out in the task so the implementer does not treat it as an oversight.

**Renaming risk.** Task 3 renames the `dissent` role to `vote_against`. `test_diffing.py` and `test_phrases.py` may reference it; Task 3 Step 4 runs the full suite specifically to catch that.
