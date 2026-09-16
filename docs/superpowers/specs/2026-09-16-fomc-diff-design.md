# fomc-diff — design

**Date:** 2026-09-16
**Status:** approved design, not yet implemented
**Author:** Andre (design partner: Claude Opus 5)

## Purpose

A reproducible, open dataset of FOMC statements and minutes (2008→present), a
deterministic diff and phrase engine over that corpus, and a join to macro data
that measures how long the Committee's *language* lags the *data*.

The dataset is the product. The code exists to regenerate the dataset; the
analysis exists to show why the dataset is interesting.

Secondary goal: the build is documented publicly on X as it happens.

## Non-goals

- Not a trading signal. No backtest, no "edge", no predictive claim.
- Not a live event-day redline. A 2:00 ET redline is a possible later milestone
  and is explicitly out of scope here; it is a latency problem, not an analysis
  problem, and it would set the schedule rather than the analysis.
- Not an LLM tone-scorer. See "Why deterministic" below.

## Why deterministic

The founding probe diffed the June 17 and July 29, 2026 statements:

```
VOTE   12-0  ->  9-3
PARAS  3     ->  4

~ CHANGED   [-reaffirmed-] [+is continuing+]  its policy of maintaining ample reserves
  UNCHANGED Economic activity is expanding at a solid pace...   (verbatim)
  UNCHANGED Inflation remains elevated relative to the 2 percent goal...  (verbatim)
+ ADDED     Voting against were Beth M. Hammack, Neel Kashkari, and Lorie K. Logan,
            who preferred to RAISE the target range by 1/4 percentage point.
```

Two of the three body paragraphs are verbatim identical. A tone or hawkishness
scorer reading this pair would call the two documents nearly the same, because
on language they are. The entire signal lives in the vote count and an added
paragraph — **structural facts, not tone**. The deterministic pass caught what a
model pass would most likely have smoothed away.

Therefore: every number in this repo is computed in plain Python. A model writes
captions only, in a separate labeled column, and never sees source text.

## Architecture

Three stages. Each writes a file. Each is independently testable, and re-running
a later stage never touches the network.

```
fetch  ->  data/text/*.txt      (plain text, committed)
parse  ->  data/*.csv           (structured, committed)
derive ->  charts/, notebooks/  (analysis, committed)
```

```
fomc-diff/
  config/
    turn_rules.yaml      pre-registered data-turn definitions (see "Tautology guard")
    phrases.yaml         tracked phrases
  data/
    raw/                 gitignored HTML cache
    text/                statements/YYYYMMDD.txt, minutes/YYYYMMDD.txt   [committed]
    manifest.csv         url, fetched_at, sha256 of raw HTML             [committed]
    *.csv                the seven tables below                          [committed]
  src/fomc_diff/
    fetch.py             era-aware URL builder + on-disk cache
    parse.py             HTML -> role-tagged paragraphs
    diffing.py           paragraph + word diff, vote extraction
    quantifiers.py       graded-hedge counts from minutes
    macro.py             FRED via keyless fredgraph.csv
    reaction.py          2:00 ET -> close move
    annotate.py          captions; opt-in, never in CI
    cli.py
  tests/  notebooks/  charts/
  .github/workflows/refresh.yml
```

### Committed text, not committed HTML

Raw HTML is ~45 MB and unreadable in a browser. Extracted text is ~8 MB,
diffable, and renders on GitHub directly. Provenance is preserved by committing
a SHA-256 manifest of each raw page: if the Fed silently edits a published
document, the manifest mismatches and we find out.

This split is also why the whole dataset can be regenerated offline by anyone
who clones the repo.

## Corpus and sources

All URL patterns verified live on 2026-09-16 (HTTP 200 for both a 2015 and a
2026 document):

| Source | Pattern |
|---|---|
| Statements | `/newsevents/pressreleases/monetary{YYYYMMDD}a.htm` |
| Minutes (HTML) | `/monetarypolicy/fomcminutes{YYYYMMDD}.htm` |
| Minutes (PDF fallback) | `/monetarypolicy/files/fomcminutes{YYYYMMDD}.pdf` |
| Meeting dates, past | `/monetarypolicy/fomchistorical{YYYY}.htm` |
| Meeting dates, current | `/monetarypolicy/fomccalendars.htm` |

A single URL scheme covers the entire 2008→present span, which is why 2008 is
the floor. Backfill is ~290 documents fetched once at 1 req/sec and then cached;
CI thereafter fetches one document per meeting day, eight times a year.

**Licensing:** FOMC statements and minutes are US government works, public
domain under 17 USC §105. Redistributing the extracted text in this repo is
permitted. `federalreserve.gov/robots.txt` does not exist (404), so no crawl
restriction is declared.

### Paragraph roles

Roles are assigned by deterministic keyword anchors, never by position, because
position shifts between eras and the anchors do not:

- `policy` — contains "target range for the federal funds rate"
- `inflation` — begins "Inflation"
- `dissent` — begins "Voting against"
- `economy` — contains "Economic activity"

Any paragraph matching no anchor is tagged `unclassified` and asserted against
in the test suite, so Fed HTML drift surfaces as a red test rather than a
quietly missing row.

## Schema

Seven tables. `meeting_date` is the join key in every one.

| Table | Columns |
|---|---|
| `meetings.csv` *(spine)* | `meeting_date, statement_url, minutes_url, decision{hike\|hold\|cut}, target_lower, target_upper, vote_for, vote_against, dissenters, dissent_direction` |
| `statements.csv` | `meeting_date, para_index, para_role, text, sha256` |
| `diffs.csv` | `from_date, to_date, para_role, change_type{unchanged\|changed\|added\|removed}, words_added, words_removed, word_diff` |
| `phrases.csv` | `phrase, first_seen, last_seen, n_meetings` |
| `quantifiers.csv` | `meeting_date, population{participants\|members}, quantifier, count` |
| `macro.csv` | `meeting_date, cpi_yoy, core_pce_yoy, unrate, payrolls_3mo, ffr_effective, fetched_at` |
| `reaction.csv` | `meeting_date, spy_pct, tlt_pct, dgs10_bp` |

### Derived fields

`decision` is not parsed from prose. It is computed by comparing
`target_lower`/`target_upper` against the previous meeting's row: higher is
`hike`, lower is `cut`, equal is `hold`. The target range itself is parsed from
the `policy` paragraph. This keeps the most important categorical column out of
the reach of wording changes.

`dissent_direction` is parsed from the `dissent` paragraph, which states the
preferred alternative explicitly ("preferred to raise", "preferred to lower").
A dissent paragraph that matches neither is recorded as `unclear` and asserted
against in the suite, never silently dropped.

### Counting trap

`"all participants"` is a substring of `"almost all participants"`, and the Fed
uses `members` and `participants` to mean deliberately different populations.
Counting therefore requires word-boundary regex with negative lookbehind, and
`members` and `participants` are separate rows via the `population` column.
Collapsing them is the single easiest way to publish a wrong number.

Extraction is confirmed viable: the July 29, 2026 minutes yielded 44 graded
hedges across six distinct quantifiers.

## Analysis

### Claim B — dissent as a leading indicator (headline)

Does a rise in `vote_against` precede a policy change within N meetings?
Fully deterministic across all ~145 meetings, with no rule-tuning, because
dissent counts are a fact the Fed prints. September 16, 2026 is a live
out-of-sample case: three dissenters demanded a hike in July.

### Claim A — the language lag (depth)

For each tracked phrase:

```
lag_months = (meeting where the language turned) - (month the data turned)
```

A *language event* comes from `phrases.csv` (first or last appearance). A *data
turn* comes from a rule over a FRED series, e.g. "first month of >=3 consecutive
declines in core PCE YoY".

### Tautology guard

If the turn rule is tuned until the lag looks impressive, the metric is circular
— it measures our rule, not the Fed. Three structural guards, all mandatory:

1. Turn rules are pre-registered in `config/turn_rules.yaml`, written before
   results are examined. The file's git history is the proof.
2. The lag is published for **every** tracked phrase, not a flattering subset.
3. The README states plainly that n is roughly 145 meetings and far fewer
   language events. This is descriptive, not predictive.

The `reaction.csv` columns are labeled in the README as confounded by the 2:30
press conference and by unrelated same-day tape. They are color, not evidence.

## Annotation layer

`annotate.py` is opt-in via `--annotate`, never runs in CI, and writes only to
`annotations.csv` (`meeting_date, caption, model, generated_at, prompt_sha`).

**Structural guarantee:** annotate.py is handed only the computed row, never the
source text. It cannot invent a figure because it never sees one that is not
already in a deterministic table. Captions are labeled commentary in the README
and appear on no chart axis.

This is the last milestone and blocks nothing; the dataset ships complete
without it.

## Testing

| # | Test | Disable-proofs |
|---|---|---|
| 1 | Golden file: the Jun→Jul 2026 pair must reproduce exactly `12-0 → 9-3`, `reaffirmed → is continuing`, `+dissent para` | the diff engine's core behavior |
| 2 | Zero `unclassified` paragraphs across all committed documents | Fed HTML drift becomes a red test, not a missing row |
| 3 | Manifest SHA re-check on a sample | the Fed silently editing a published document |
| 4 | `"almost all participants"` fixture yields `almost_all=1, all=0` | the substring trap |
| 5 | Mutating `turn_rules.yaml` must change the output | proves the config has a real reader; a config check that passes without one is vacuous |
| 6 | `--annotate` off leaves all other tables byte-identical | annotation cannot contaminate the deterministic spine |

## Failure modes

- **Empty is not quiet.** A zero-row parse fails the Action loudly and never
  commits an empty table. CI refuses to commit if any table's row count
  decreases — the guard against silent data loss.
- Minutes occasionally lack an HTML version; the PDF fallback is used and
  flagged in `manifest.csv` so the source is never ambiguous.
- FRED revisions rewrite history. `macro.csv` records `fetched_at` per pull and
  the README states the columns are as-of, not vintage-pinned, so anyone
  recomputing later expects small differences rather than discovering them.

## Security

- No secrets belong in this repo. FRED is keyless; `annotate.py` reads any key
  from env only.
- `.gitignore` was committed before any other file.
- A leaked key is a rotation, never a history rewrite: force-pushing does not
  remove data from GitHub.

## Milestones

1. fetch + parse + `manifest.csv` + committed text for 2008→now
2. `diffing.py`, `meetings.csv`, `statements.csv`, `diffs.csv`, `phrases.csv` — Claim B computable
3. `quantifiers.py` + `quantifiers.csv`
4. `macro.py` + `reaction.py`, `config/turn_rules.yaml` — Claim A computable
5. notebooks + charts + README
6. `annotate.py` (blocked on Anthropic API credits; optional)

## Open questions

- Chart style and whether `charts/` renders in CI or by hand.
- Whether to publish to PyPI at all, or leave it a dataset repo. `fomc-diff` is
  free on PyPI as of 2026-09-16 but claiming it is not required for milestone 1.
