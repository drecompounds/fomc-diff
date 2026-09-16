# fomc-diff Corpus and Diff Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reproducible FOMC corpus (2008→present) and the deterministic engine over it, so that dissent counts, statement diffs, phrase history, and minutes quantifiers are all computable from committed data.

**Architecture:** Three stages that never run backwards — `fetch` writes cached HTML plus committed plain text and a SHA manifest; `parse` turns text into role-tagged paragraphs and seven CSV tables; `derive` computes diffs, phrase history, and quantifier counts. Re-running any later stage never touches the network.

**Tech Stack:** Python 3.11+, stdlib only for the core (`re`, `difflib`, `hashlib`, `csv`, `dataclasses`, `urllib`), `requests` for fetching, `pytest` for tests. No pandas in the core path — CSV writing is stdlib so the dataset has no dependency to reproduce.

**Spec:** `docs/superpowers/specs/2026-09-16-fomc-diff-design.md`

## Global Constraints

- Python 3.11 or higher.
- Core parsing/diffing imports stdlib only. `requests` is permitted in `fetch.py` alone.
- Every file written with `encoding="utf-8"` explicitly. No emoji in any parsed or generated data file.
- All CSV writes use `newline=""` and `lineterminator="\n"` so the committed data is stable across platforms.
- Fetching is rate-limited to 1 request/second and always checks the cache first.
- No secrets anywhere. FRED is keyless; this plan adds no API key.
- Dates are `datetime.date`; serialized as ISO `YYYY-MM-DD` in every table.
- A zero-row parse is an error, never an empty file. See Task 8.

---

### Task 1: Project scaffold and URL builders

**Files:**
- Create: `pyproject.toml`
- Create: `src/fomc_diff/__init__.py`
- Create: `src/fomc_diff/fetch.py`
- Test: `tests/test_fetch_urls.py`

**Interfaces:**
- Consumes: nothing
- Produces: `statement_url(d: date) -> str`, `minutes_url(d: date) -> str`, `minutes_pdf_url(d: date) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_urls.py
from datetime import date
from fomc_diff.fetch import statement_url, minutes_url, minutes_pdf_url

BASE = "https://www.federalreserve.gov"

def test_statement_url():
    assert statement_url(date(2026, 7, 29)) == (
        f"{BASE}/newsevents/pressreleases/monetary20260729a.htm")

def test_minutes_url():
    assert minutes_url(date(2026, 7, 29)) == (
        f"{BASE}/monetarypolicy/fomcminutes20260729.htm")

def test_minutes_pdf_url():
    assert minutes_pdf_url(date(2015, 9, 17)) == (
        f"{BASE}/monetarypolicy/files/fomcminutes20150917.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_urls.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "fomc-diff"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/fomc_diff/__init__.py
"""Deterministic FOMC statement and minutes corpus."""
```

```python
# src/fomc_diff/fetch.py
"""Fetch FOMC documents. The only module permitted to touch the network."""
from __future__ import annotations

from datetime import date

BASE = "https://www.federalreserve.gov"


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d")


def statement_url(d: date) -> str:
    return f"{BASE}/newsevents/pressreleases/monetary{_stamp(d)}a.htm"


def minutes_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/fomcminutes{_stamp(d)}.htm"


def minutes_pdf_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/files/fomcminutes{_stamp(d)}.pdf"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_urls.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/fomc_diff/__init__.py src/fomc_diff/fetch.py tests/test_fetch_urls.py
git commit -m "feat: project scaffold and FOMC document URL builders"
```

---

### Task 2: Cached fetch with SHA manifest

**Files:**
- Modify: `src/fomc_diff/fetch.py`
- Test: `tests/test_fetch_cache.py`

**Interfaces:**
- Consumes: `statement_url` from Task 1
- Produces: `FetchResult` dataclass with fields `url: str`, `path: Path`, `sha256: str`, `fetched_at: str`, `from_cache: bool`; and `fetch(url: str, cache_dir: Path, *, session=None, sleep=time.sleep) -> FetchResult`

Note the injected `sleep` parameter — tests pass a no-op so the suite never actually waits, and a hang can never masquerade as a slow test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_cache.py
import hashlib
from pathlib import Path
from fomc_diff.fetch import fetch

HTML = "<html><body><p>hello</p></body></html>"

class FakeResponse:
    status_code = 200
    text = HTML
    content = HTML.encode("utf-8")
    def raise_for_status(self): pass

class FakeSession:
    def __init__(self): self.calls = 0
    def get(self, url, timeout=30, headers=None):
        self.calls += 1
        return FakeResponse()

def test_fetch_writes_file_and_sha(tmp_path: Path):
    s = FakeSession()
    r = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r.from_cache is False
    assert r.path.exists()
    assert r.sha256 == hashlib.sha256(HTML.encode("utf-8")).hexdigest()
    assert s.calls == 1

def test_second_fetch_uses_cache_and_makes_no_request(tmp_path: Path):
    s = FakeSession()
    fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is True
    assert s.calls == 1, "cache hit must not issue a second request"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_cache.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/fomc_diff/fetch.py`:

```python
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

UA = "fomc-diff/0.1 (open data project; contact via GitHub issues)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    from_cache: bool


def _cache_name(url: str) -> str:
    return Path(urlparse(url).path).name


def fetch(url: str, cache_dir: Path, *, session=None, sleep=time.sleep) -> FetchResult:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / _cache_name(url)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if path.exists():
        body = path.read_text(encoding="utf-8")
        return FetchResult(url, path,
                           hashlib.sha256(body.encode("utf-8")).hexdigest(),
                           now, True)

    if session is None:
        import requests
        session = requests.Session()

    sleep(1.0)  # 1 req/sec, applied before every real request
    resp = session.get(url, timeout=30, headers={"User-Agent": UA})
    resp.raise_for_status()
    body = resp.text
    path.write_text(body, encoding="utf-8")
    return FetchResult(url, path,
                       hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       now, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_cache.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/fetch.py tests/test_fetch_cache.py
git commit -m "feat: cached fetch with sha256 manifest fields"
```

---

### Task 3: Paragraph extraction and role anchors

**Files:**
- Create: `src/fomc_diff/parse.py`
- Create: `tests/fixtures/statement_20260729.html` (copy the real file, see Step 0)
- Create: `tests/fixtures/statement_20260617.html`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: nothing
- Produces: `extract_paragraphs(html: str) -> list[str]`, `role_for(text: str) -> str`, `Paragraph` dataclass with `index: int`, `role: str`, `text: str`, `sha256: str`, and `parse_statement(html: str) -> list[Paragraph]`

Valid roles: `policy`, `economy`, `inflation`, `dissent`, `unclassified`. Boilerplate (the date line, the "For release at" line, media-contact line, implementation-note line) is dropped before role assignment.

- [ ] **Step 0: Save the two real fixtures**

```bash
mkdir -p tests/fixtures
curl -sL -A "Mozilla/5.0" \
  "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm" \
  -o tests/fixtures/statement_20260729.html
curl -sL -A "Mozilla/5.0" \
  "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm" \
  -o tests/fixtures/statement_20260617.html
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parse.py
from pathlib import Path
import pytest
from fomc_diff.parse import extract_paragraphs, role_for, parse_statement

FIX = Path(__file__).parent / "fixtures"

def _html(name): return (FIX / name).read_text(encoding="utf-8")

def test_july_has_four_body_paragraphs():
    paras = parse_statement(_html("statement_20260729.html"))
    assert len(paras) == 4

def test_june_has_three_body_paragraphs():
    paras = parse_statement(_html("statement_20260617.html"))
    assert len(paras) == 3

def test_roles_assigned_by_anchor_not_position():
    paras = parse_statement(_html("statement_20260729.html"))
    assert [p.role for p in paras] == ["policy", "economy", "inflation", "dissent"]

def test_no_unclassified_paragraphs_in_either_fixture():
    for name in ("statement_20260729.html", "statement_20260617.html"):
        paras = parse_statement(_html(name))
        bad = [p.text for p in paras if p.role == "unclassified"]
        assert bad == [], f"{name} produced unclassified paragraphs: {bad}"

def test_boilerplate_is_dropped():
    paras = parse_statement(_html("statement_20260729.html"))
    joined = " ".join(p.text for p in paras)
    assert "media inquiries" not in joined.lower()
    assert "Implementation Note" not in joined

@pytest.mark.parametrize("text,expected", [
    ("The Committee decided to maintain the target range for the federal "
     "funds rate at 3-1/2 to 3-3/4 percent.", "policy"),
    ("Economic activity is expanding at a solid pace.", "economy"),
    ("Inflation remains elevated relative to the Committee's 2 percent goal.",
     "inflation"),
    ("Voting against the monetary policy action were Beth M. Hammack.",
     "dissent"),
    ("The Committee went bowling.", "unclassified"),
])
def test_role_for(text, expected):
    assert role_for(text) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.parse'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/parse.py
"""HTML -> role-tagged paragraphs. Stdlib only; never touches the network."""
from __future__ import annotations

import hashlib
import html as html_mod
import re
from dataclasses import dataclass

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_DATE_LINE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
_DROP_PREFIXES = (
    "For release at",
    "For media inquiries",
    "Implementation Note",
    "Last Update",
    "Share",
)


@dataclass(frozen=True)
class Paragraph:
    index: int
    role: str
    text: str
    sha256: str


def extract_paragraphs(html: str) -> list[str]:
    out: list[str] = []
    for raw in _P.findall(html):
        text = html_mod.unescape(_TAG.sub(" ", raw))
        text = text.replace(" ", " ")
        text = _WS.sub(" ", text).strip()
        if text:
            out.append(text)
    return out


def _is_boilerplate(text: str) -> bool:
    if _DATE_LINE.match(text):
        return True
    return any(text.startswith(p) for p in _DROP_PREFIXES)


def role_for(text: str) -> str:
    if text.startswith("Voting against"):
        return "dissent"
    if "target range for the federal funds rate" in text:
        return "policy"
    if text.startswith("Inflation"):
        return "inflation"
    if "Economic activity" in text:
        return "economy"
    return "unclassified"


def parse_statement(html: str) -> list[Paragraph]:
    paras = [p for p in extract_paragraphs(html) if not _is_boilerplate(p)]
    return [
        Paragraph(i, role_for(t), t,
                  hashlib.sha256(t.encode("utf-8")).hexdigest())
        for i, t in enumerate(paras)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parse.py -v`
Expected: 9 passed

If `test_boilerplate_is_dropped` fails because the vote line ("The Federal Open Market Committee approved the following statement...") survives, that line begins with `"For release at"` in the real fixture and is already covered — confirm by printing the parsed paragraphs before adding any new prefix.

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/parse.py tests/test_parse.py tests/fixtures/
git commit -m "feat: paragraph extraction with anchor-based role assignment"
```

---

### Task 4: Vote, target range, and dissent extraction

**Files:**
- Create: `src/fomc_diff/meetings.py`
- Test: `tests/test_meetings.py`

**Interfaces:**
- Consumes: `Paragraph` from Task 3
- Produces: `parse_fraction(s: str) -> float`, `parse_vote(html: str) -> tuple[int, int]`, `parse_target_range(text: str) -> tuple[float, float]`, `parse_dissent(text: str) -> tuple[list[str], str]`, `derive_decision(prev_upper: float | None, cur_upper: float) -> str`

The Fed writes rates as fractions (`3-1/2`, `3-3/4`) and the vote with an en-dash and surrounding spaces (`by a 12 – 0 vote`). Both are handled explicitly below; both are the kind of thing that silently returns the wrong number if guessed at.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meetings.py
from pathlib import Path
import pytest
from fomc_diff.meetings import (
    parse_fraction, parse_vote, parse_target_range, parse_dissent,
    derive_decision,
)

FIX = Path(__file__).parent / "fixtures"
def _html(name): return (FIX / name).read_text(encoding="utf-8")

@pytest.mark.parametrize("s,expected", [
    ("3-1/2", 3.5), ("3-3/4", 3.75), ("5", 5.0), ("0-1/4", 0.25),
])
def test_parse_fraction(s, expected):
    assert parse_fraction(s) == expected

def test_parse_vote_handles_en_dash_with_spaces():
    assert parse_vote(_html("statement_20260729.html")) == (9, 3)
    assert parse_vote(_html("statement_20260617.html")) == (12, 0)

def test_parse_target_range():
    text = ("The Committee decided to maintain the target range for the federal "
            "funds rate at 3-1/2 to 3-3/4 percent, in support of the dual mandate.")
    assert parse_target_range(text) == (3.5, 3.75)

def test_parse_dissent_names_and_direction():
    text = ("Voting against the monetary policy action were Beth M. Hammack, "
            "Neel Kashkari, and Lorie K. Logan, who preferred to raise the "
            "target range for the federal funds rate by 1/4 percentage point "
            "at this meeting.")
    names, direction = parse_dissent(text)
    assert names == ["Beth M. Hammack", "Neel Kashkari", "Lorie K. Logan"]
    assert direction == "raise"

def test_parse_dissent_unrecognised_direction_is_unclear_not_dropped():
    text = "Voting against the monetary policy action were Jane Doe, who abstained."
    names, direction = parse_dissent(text)
    assert names == ["Jane Doe"]
    assert direction == "unclear"

@pytest.mark.parametrize("prev,cur,expected", [
    (3.75, 4.0, "hike"), (3.75, 3.5, "cut"), (3.75, 3.75, "hold"),
    (None, 3.75, "hold"),
])
def test_derive_decision(prev, cur, expected):
    assert derive_decision(prev, cur) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_meetings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.meetings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/meetings.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_meetings.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/meetings.py tests/test_meetings.py
git commit -m "feat: vote, target range, and dissent extraction"
```

---

### Task 5: The diff engine and its golden file

**Files:**
- Create: `src/fomc_diff/diffing.py`
- Test: `tests/test_diffing.py`

**Interfaces:**
- Consumes: `Paragraph` from Task 3
- Produces: `word_diff(a: str, b: str) -> str`, `DiffRow` dataclass with `role: str`, `change_type: str`, `words_added: int`, `words_removed: int`, `word_diff: str`, and `diff_statements(a: list[Paragraph], b: list[Paragraph]) -> list[DiffRow]`

`change_type` is one of `unchanged`, `changed`, `added`, `removed`.

This task carries the project's regression anchor: the June→July 2026 pair is the finding the whole repo is built on, so it is asserted exactly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diffing.py
from pathlib import Path
from fomc_diff.parse import parse_statement
from fomc_diff.diffing import diff_statements, word_diff

FIX = Path(__file__).parent / "fixtures"
def _paras(name):
    return parse_statement((FIX / name).read_text(encoding="utf-8"))

def test_word_diff_marks_replacement():
    out = word_diff("the Committee reaffirmed its policy",
                    "the Committee is continuing its policy")
    assert "[-reaffirmed-]" in out
    assert "[+is continuing+]" in out

def test_golden_june_to_july_2026():
    """The founding finding. If this breaks, the repo's premise broke."""
    rows = diff_statements(_paras("statement_20260617.html"),
                           _paras("statement_20260729.html"))
    by_role = {r.role: r for r in rows}

    assert by_role["policy"].change_type == "changed"
    assert "[-reaffirmed-]" in by_role["policy"].word_diff
    assert "[+is continuing+]" in by_role["policy"].word_diff

    assert by_role["economy"].change_type == "unchanged"
    assert by_role["inflation"].change_type == "unchanged"

    assert by_role["dissent"].change_type == "added"
    assert "Hammack" in by_role["dissent"].word_diff

def test_unchanged_rows_have_zero_word_counts():
    rows = diff_statements(_paras("statement_20260617.html"),
                           _paras("statement_20260729.html"))
    for r in rows:
        if r.change_type == "unchanged":
            assert (r.words_added, r.words_removed) == (0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_diffing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.diffing'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/diffing.py
"""Deterministic paragraph and word diffs between two statements."""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .parse import Paragraph


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_diffing.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/diffing.py tests/test_diffing.py
git commit -m "feat: role-aligned diff engine with June-July 2026 golden test"
```

---

### Task 6: Quantifier counting and the substring trap

**Files:**
- Create: `src/fomc_diff/quantifiers.py`
- Test: `tests/test_quantifiers.py`

**Interfaces:**
- Consumes: nothing
- Produces: `count_quantifiers(text: str) -> dict[tuple[str, str], int]`, keyed by `(population, quantifier)` where population is `participants` or `members`.

Quantifiers tracked, longest-first so alternation resolves correctly: `almost all`, `a number of`, `a couple of`, `a few`, `all`, `most`, `many`, `several`, `some`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quantifiers.py
from fomc_diff.quantifiers import count_quantifiers

def test_almost_all_does_not_also_count_as_all():
    """The substring trap. 'all participants' is inside 'almost all participants'."""
    c = count_quantifiers("Almost all participants agreed.")
    assert c.get(("participants", "almost all")) == 1
    assert c.get(("participants", "all,")) is None
    assert c.get(("participants", "all")) is None

def test_bare_all_still_counts():
    c = count_quantifiers("All participants agreed.")
    assert c.get(("participants", "all")) == 1
    assert c.get(("participants", "almost all")) is None

def test_members_and_participants_are_separate_populations():
    c = count_quantifiers("A few members dissented. A few participants agreed.")
    assert c.get(("members", "a few")) == 1
    assert c.get(("participants", "a few")) == 1

def test_case_insensitive_and_counted():
    c = count_quantifiers("Several participants noted. several participants added.")
    assert c.get(("participants", "several")) == 2

def test_unrelated_text_counts_nothing():
    assert count_quantifiers("The Committee met in Washington.") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quantifiers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.quantifiers'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/quantifiers.py
"""Graded hedge counts from FOMC minutes.

Order matters: the alternation is leftmost-first, so 'almost all' must precede
'all' or every 'almost all participants' silently also books an 'all'.
"""
from __future__ import annotations

import re
from collections import Counter

QUANTIFIERS = (
    "almost all",
    "a number of",
    "a couple of",
    "a few",
    "all",
    "most",
    "many",
    "several",
    "some",
)

_PATTERN = re.compile(
    r"\b(" + "|".join(q.replace(" ", r"\s+") for q in QUANTIFIERS) + r")\s+"
    r"(participants|members)\b",
    re.I,
)


def count_quantifiers(text: str) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    for m in _PATTERN.finditer(text):
        quant = re.sub(r"\s+", " ", m.group(1).lower())
        population = m.group(2).lower()
        counts[(population, quant)] += 1
    return dict(counts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_quantifiers.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/quantifiers.py tests/test_quantifiers.py
git commit -m "feat: quantifier counting with almost-all substring guard"
```

---

### Task 7: Phrase history index

**Files:**
- Create: `src/fomc_diff/phrases.py`
- Test: `tests/test_phrases.py`

**Interfaces:**
- Consumes: `Paragraph` from Task 3
- Produces: `PhraseRow` dataclass with `phrase: str`, `first_seen: str`, `last_seen: str`, `n_meetings: int`, and `phrase_index(by_date: dict[date, list[Paragraph]], phrases: list[str]) -> list[PhraseRow]`

This produces the "last time they used this word was March 2024" table. Phrases come from `config/phrases.yaml` at the CLI layer; this function takes them as a plain list so it stays testable without file IO.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phrases.py
from datetime import date
from fomc_diff.parse import Paragraph
from fomc_diff.phrases import phrase_index

def _p(text): return [Paragraph(0, "economy", text, "x")]

BY_DATE = {
    date(2026, 3, 18): _p("Economic activity is expanding at a moderate pace."),
    date(2026, 6, 17): _p("Economic activity is expanding at a solid pace."),
    date(2026, 7, 29): _p("Economic activity is expanding at a solid pace."),
}

def test_tracks_first_and_last_seen():
    rows = {r.phrase: r for r in phrase_index(BY_DATE, ["solid pace", "moderate pace"])}
    assert rows["solid pace"].first_seen == "2026-06-17"
    assert rows["solid pace"].last_seen == "2026-07-29"
    assert rows["solid pace"].n_meetings == 2
    assert rows["moderate pace"].first_seen == "2026-03-18"
    assert rows["moderate pace"].n_meetings == 1

def test_absent_phrase_is_omitted_not_zero_filled():
    rows = {r.phrase: r for r in phrase_index(BY_DATE, ["bowling night"])}
    assert rows == {}

def test_dates_are_sorted_regardless_of_dict_order():
    shuffled = {k: BY_DATE[k] for k in sorted(BY_DATE, reverse=True)}
    rows = {r.phrase: r for r in phrase_index(shuffled, ["solid pace"])}
    assert rows["solid pace"].first_seen == "2026-06-17"
    assert rows["solid pace"].last_seen == "2026-07-29"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_phrases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.phrases'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/phrases.py
"""First/last appearance of tracked phrases across the corpus."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .parse import Paragraph


@dataclass(frozen=True)
class PhraseRow:
    phrase: str
    first_seen: str
    last_seen: str
    n_meetings: int


def phrase_index(by_date: dict[date, list[Paragraph]],
                 phrases: list[str]) -> list[PhraseRow]:
    rows: list[PhraseRow] = []
    for phrase in phrases:
        needle = phrase.lower()
        hits = sorted(
            d for d, paras in by_date.items()
            if any(needle in p.text.lower() for p in paras)
        )
        if not hits:
            continue
        rows.append(PhraseRow(phrase, hits[0].isoformat(),
                              hits[-1].isoformat(), len(hits)))
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_phrases.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/fomc_diff/phrases.py tests/test_phrases.py
git commit -m "feat: phrase first/last-seen index"
```

---

### Task 8: CSV writers with the empty-table guard

**Files:**
- Create: `src/fomc_diff/tables.py`
- Test: `tests/test_tables.py`

**Interfaces:**
- Consumes: all dataclasses from Tasks 3–7
- Produces: `write_table(path: Path, fieldnames: list[str], rows: list[dict]) -> int`, raising `EmptyTableError` on zero rows.

Per the spec: a zero-row parse fails loudly and never commits an empty table. "Empty is not quiet" — a table that silently becomes empty is the failure mode most likely to go unnoticed for months.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tables.py
import csv
from pathlib import Path
import pytest
from fomc_diff.tables import write_table, EmptyTableError

def test_writes_rows_and_returns_count(tmp_path: Path):
    p = tmp_path / "t.csv"
    n = write_table(p, ["a", "b"], [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    assert n == 2
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert rows[0]["a"] == "1"

def test_zero_rows_raises_and_writes_nothing(tmp_path: Path):
    p = tmp_path / "t.csv"
    with pytest.raises(EmptyTableError):
        write_table(p, ["a"], [])
    assert not p.exists(), "an empty table must never reach disk"

def test_existing_file_untouched_when_new_data_is_empty(tmp_path: Path):
    p = tmp_path / "t.csv"
    write_table(p, ["a"], [{"a": 1}])
    before = p.read_text(encoding="utf-8")
    with pytest.raises(EmptyTableError):
        write_table(p, ["a"], [])
    assert p.read_text(encoding="utf-8") == before

def test_line_endings_are_lf_not_crlf(tmp_path: Path):
    p = tmp_path / "t.csv"
    write_table(p, ["a"], [{"a": 1}])
    assert b"\r\n" not in p.read_bytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tables.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fomc_diff.tables'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fomc_diff/tables.py
"""CSV writing. Empty is never quiet."""
from __future__ import annotations

import csv
from pathlib import Path


class EmptyTableError(RuntimeError):
    """Raised when a table would be written with zero rows."""


def write_table(path: Path, fieldnames: list[str], rows: list[dict]) -> int:
    if not rows:
        raise EmptyTableError(
            f"refusing to write {path.name} with 0 rows; "
            "an empty table is a parse failure, not a quiet result"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tables.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the whole suite and commit**

```bash
pytest -v
git add src/fomc_diff/tables.py tests/test_tables.py
git commit -m "feat: CSV writers that refuse to write empty tables"
```

---

## Self-Review

**Spec coverage.** Fetch/cache/manifest → Tasks 1–2. Committed text and SHA provenance → Task 2 (`FetchResult.sha256`), wired to `manifest.csv` in the follow-on plan. Role anchors and the unclassified assertion → Task 3. `decision` and `dissent_direction` derived fields → Task 4. Diff engine and golden file (test 1) → Task 5. Substring trap (test 4) → Task 6. Phrase table → Task 7. Empty-is-not-quiet → Task 8.

**Deferred to the follow-on plan, deliberately:** `macro.py`, `reaction.py`, `config/turn_rules.yaml` and the tautology guard (milestone 4); notebooks and charts (milestone 5); `annotate.py` export/verify and tests 5–7 (milestone 6). Task 8's `write_table` is the seam they all build on.

**Not yet covered by any task, and owed to the follow-on plan:** the backfill driver that walks 2008→present, the `refresh.yml` Action, the row-count-must-not-decrease CI guard, and the PDF fallback for minutes lacking an HTML version. These need the corpus to exist first.

**Type consistency.** `Paragraph` (Task 3) is consumed by Tasks 5 and 7 under that exact name. `DiffRow`, `PhraseRow`, `FetchResult` are each defined once. `parse_statement` returns `list[Paragraph]` everywhere it appears. `derive_decision` takes upper bounds only, matching its call site in the follow-on plan.

**One risk flagged for the executor:** Task 3's fixture assertions (`len(paras) == 4` / `== 3`) depend on the Fed's current HTML. If the fixtures are re-downloaded later and the markup has shifted, that test fails loudly — which is the intent, but the executor should fix the parser rather than relax the assertion.
