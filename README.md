# fomc-diff

A deterministic diff engine and open dataset for Federal Reserve FOMC
statements, covering every meeting from January 2016 to September 2026.

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
git clone https://github.com/drecompounds/fomc-diff
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
an empty table.

That claim was overstated, and the corpus proved it. The boilerplate filter
dropped any paragraph beginning with a known prefix — and the Fed glues its
release line onto the front of the first body paragraph, so the opening
economic assessment was deleted in 86 of 89 statements. On March 3, 2020 the
emergency 50 basis point cut was inside that paragraph, so the rate decision
itself was discarded. Nothing raised. The output was not empty and not loud:
it was *confidently short*.

The rule now has a guard behind it. A statement parsing to fewer than two
paragraphs raises, every recurring paragraph must carry a role, and both are
checked against the whole corpus rather than a handful of fixtures.

**Provenance hashes what is stable.** `manifest.csv` records a hash of each
statement's *extracted text*, not of its raw bytes.

federalreserve.gov is not byte-stable. Cloudflare injects a randomised
email-protection token and a per-response script, so two fetches a second apart
return different bytes and a different raw SHA — verified live against both a
2016 and a 2026 statement. A manifest keyed on raw bytes mismatches on every
refetch and so can never distinguish a real edit from that noise, which is the
only thing it exists to detect. The extracted text is stable across refetches,
and the manifest is byte-identical run to run.

Raw bytes are still hashed where that is the right check: each cached file's
sidecar records the SHA of the bytes on disk, and a cache hit re-verifies it.
A torn write once corrupted a cached document, the next run served it and
recorded the damaged hash as ground truth, and a corrupted row reached this
dataset. Cached bodies are written to a temporary file and moved into place
atomically, and an entry whose hash cannot be verified is refetched rather
than trusted.

**Structure over tone.** Vote counts, dissent names and directions, and added
or removed paragraphs are facts the Fed prints. They are read directly.

## What is here

| Module | Responsibility |
|---|---|
| `discover.py` | Resolves statement URLs from the Fed's own listing pages, by label. The only module that decides what counts as a statement. |
| `fetch.py` | Cached, rate-limited fetching with SHA provenance. The only module that touches the network. |
| `parse.py` | HTML to role-tagged paragraphs (`policy`, `economy`, `inflation`, `vote_for`, `vote_against`, `guidance`, `directive` and others). |
| `meetings.py` | Vote, target range, dissent names and direction, derived decision. |
| `diffing.py` | Role-aligned paragraph and word diffs. |
| `quantifiers.py` | Graded hedge counts from minutes ("a few" / "several" / "most" participants). |
| `phrases.py` | First and last appearance of tracked phrases across the corpus. |
| `sep.py` | Summary of Economic Projections (the dot-plot tables): medians, central tendency and range per variable per horizon, plus release-to-release deltas. |
| `backfill.py` | Drives the whole corpus into the four committed CSVs. |
| `tables.py` | CSV writers that refuse to write an empty table. |

Design and implementation notes live in `docs/superpowers/`.

## The dataset

`data/` holds the corpus, regenerable from scratch with
`python -m fomc_diff.backfill`. Re-running against a warm cache produces
byte-identical files.

| File | Rows | What it is |
|---|---|---|
| `meetings.csv` | 89 | The spine: `meeting_date, statement_type, vote_for, vote_against, target_lower, target_upper, decision` |
| `statements.csv` | 479 | One row per role-tagged paragraph |
| `diffs.csv` | 520 | Role-aligned paragraph and word diffs between consecutive meetings |
| `manifest.csv` | 89 | `url, fetched_at, content_sha256` — a hash of each statement's extracted text, stable across refetches |

89 statements, 2016-01-27 to 2026-09-16: 87 rate decisions (56 holds, 20 hikes,
11 cuts) and 2 operational Desk directives that carry no rate decision and no
vote. 45 dissenting votes across 27 meetings.

`decision` is never read from prose. It is computed by comparing each meeting's
target range against the previous one, which keeps the most important
categorical column out of reach of wording changes.

Statement URLs are resolved from the Fed's own listing pages by anchor label,
never built from a date. The suffix is not an identity: `monetary20160127b.htm`
is the Statement on Longer-Run Goals, published the same day as the January
policy statement, and December 2008's statement is at `b.htm` while `a.htm` is
a Term Auction Facility result.

### What validates it

The numbers are checked against facts the parser never sees:

- `vote_for + vote_against` equals the seated committee size throughout, and
  tracks real Board composition — 10 during the 2016-17 governor vacancies,
  9 in early 2022, 12 once Jefferson, Cook and Barr were seated.
- The 2022 hiking cycle reproduces step for step: 25, 50, 75, 75, 75, 75, 50
  basis points to 4.25-4.5%.
- The founding finding holds at corpus scale: 2026-06-17 12-0 hold,
  2026-07-29 **9-3** hold, 2026-09-16 12-0 **hike**.

## Status

Working: the corpus engine and the committed dataset above, 136 tests.

Not built yet:

- Minutes are fetched but not yet parsed into the corpus
- SEP backfill — `sep.py` reads a projections table, but only 2026 is committed
- FRED macro join, to measure how long the Committee's language lags the data
- Charts and the annotation layer
- Individual participant dots (`sep.py` reads the summary table, not the chart)
- 2008-2015. The engine stops at 2016; extending it is a separate decision,
  and the pre-2016 listing pages have not been verified.

### Known limitations

- **Roles are single-valued.** Where the Fed fuses two purposes into one
  paragraph, the more load-bearing role wins and the other is unrepresentable.
  March 3, 2020 carries its economic assessment and its rate decision in one
  paragraph; it is tagged `policy`.
- **Role anchors are calibrated to observed wording.** They are matched against
  all 89 statements, but a genuinely new phrasing will fall to `unclassified`
  rather than being silently misfiled. The corpus-level tests are what catch
  that, not the unit tests.

## Data and licensing

FOMC statements and minutes are US government works and are in the public
domain under 17 U.S.C. § 105. This project's own code is MIT licensed — see
`LICENSE`.

Fetching is polite by construction: one request per second, cached, and in
normal operation one new document per meeting, eight times a year.

## Not investment advice

This is a text-analysis tool. It makes no forecast and carries no backtest.
Nothing here is a trading signal.
