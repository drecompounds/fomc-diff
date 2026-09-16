# fomc-diff

A deterministic diff engine for Federal Reserve FOMC statements.

It reads the Fed's published statements, diffs each one against the previous
meeting, and reports what actually changed: the vote, the target range, the
dissents, and the language — paragraph by paragraph, word by word.

**Every number it produces is computed in plain Python.** No model scores
anything. Clone the repo and you get byte-identical results.

## Why this exists

The June 17 and July 29, 2026 statements are 98.45% identical as text. The
economy and inflation paragraphs are *byte-for-byte* the same — zero words
changed. A tone model reading that pair would reasonably call it "no change."

Here is what actually changed:

```
VOTE   12-0  ->  9-3
PARAS  3     ->  4

~ CHANGED   [-reaffirmed-] [+is continuing+]  its policy of maintaining ample reserves
  UNCHANGED Economic activity is expanding at a solid pace...   (verbatim)
  UNCHANGED Inflation remains elevated relative to the 2 percent goal...  (verbatim)
+ ADDED     Voting against were Beth M. Hammack, Neel Kashkari, and Lorie K. Logan,
            who preferred to RAISE the target range by 1/4 percentage point.
```

Three officials broke ranks to demand a hike. Seven weeks later, on
September 16, 2026, the Fed hiked a quarter point to 3-3/4 to 4 percent — and
the vote was 12-0, with the dissent paragraph removed entirely.

The signal was a number, not a tone. That is the whole design thesis: the
structure of a statement (vote counts, added and removed paragraphs) carries
information its prose does not, and structure is exactly what deterministic
code reads better than a model does.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/<you>/fomc-diff
cd fomc-diff
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows
# .venv/bin/pip install -e ".[dev]"     # macOS / Linux
pytest -q
```

## Usage

```python
from datetime import date
from pathlib import Path

from fomc_diff.fetch import fetch, statement_url
from fomc_diff.parse import parse_statement
from fomc_diff.diffing import diff_statements
from fomc_diff.meetings import parse_vote, parse_target_range, derive_decision

cache = Path("data/raw")
jul = fetch(statement_url(date(2026, 7, 29)), cache)
sep = fetch(statement_url(date(2026, 9, 16)), cache)

jul_html = jul.path.read_text(encoding="utf-8")
sep_html = sep.path.read_text(encoding="utf-8")

print(parse_vote(jul_html))   # (9, 3)
print(parse_vote(sep_html))   # (12, 0)

for row in diff_statements(parse_statement(jul_html), parse_statement(sep_html)):
    print(row.change_type, row.role, row.word_diff[:80])
```

Fetching is cached and rate-limited to one request per second. A cached
document is never re-fetched, and the cache is byte-faithful to what the Fed
served.

## Design rules

These are load-bearing, not style preferences.

**Deterministic spine.** Every figure is computed. A model may write prose
captions, in a separate labelled column, and every number a caption cites is
checked against the computed row it came from — a caption citing a figure that
is not in the data fails the test suite.

**Empty is never quiet.** A parse that cannot find what it is looking for
raises. It never returns a plausible-looking wrong value, and it never writes
an empty table. On its first live document — the September 16, 2026 statement —
this engine failed in three places and not one of them returned a wrong number.

**Byte-faithful provenance.** Cached documents are stored and hashed as bytes.
An earlier version wrote them as text, which on Windows translated line endings
and produced three different SHAs for one document — making the manifest
useless for its only job, detecting a silently edited page.

**Structure over tone.** Vote counts, dissent names and directions, and added
or removed paragraphs are facts the Fed prints. They are read directly.

## What is here

| Module | Responsibility |
|---|---|
| `fetch.py` | Cached, rate-limited fetching with SHA provenance. The only module that touches the network. |
| `parse.py` | HTML to role-tagged paragraphs (`policy`, `economy`, `inflation`, `dissent`). |
| `meetings.py` | Vote, target range, dissent names and direction, derived decision. |
| `diffing.py` | Role-aligned paragraph and word diffs. |
| `quantifiers.py` | Graded hedge counts from minutes ("a few" / "several" / "most" participants). |
| `phrases.py` | First and last appearance of tracked phrases across the corpus. |
| `tables.py` | CSV writers that refuse to write an empty table. |

Design and implementation notes live in `docs/superpowers/`.

## Status

Working: the corpus engine above, 65 tests, three real statements as fixtures.

Not built yet:

- Backfill driver for the full 2008-present corpus
- Pre-2016 statement format — older statements have no `by a N-M vote` line, and
  single-dissenter statements read "Voting against ... **was** X", which the
  current regex does not match
- Duplicate-role alignment — ZIRP-era statements reference the target range in
  several paragraphs, which currently raises `DuplicateRoleError` by design
- FRED macro join, to measure how long the Committee's language lags the data
- Charts and the annotation layer

## Data and licensing

FOMC statements and minutes are US government works and are in the public
domain under 17 U.S.C. § 105. This project's own code is MIT licensed — see
`LICENSE`.

Fetching is polite by construction: one request per second, cached, and in
normal operation one new document per meeting, eight times a year.

## Not investment advice

This is a text-analysis tool. It makes no forecast and carries no backtest.
Nothing here is a trading signal.
