# Corpus backfill, 2016-2026 — design

**Date:** 2026-09-16
**Status:** approved design, not yet implemented
**Author:** Andre (design partner: Claude Opus 5)
**Amends:** `2026-09-16-fomc-diff-design.md` — see "Corrections to the original spec"

## Purpose

Turn the working diff engine into the dataset the original spec called the
product: every FOMC policy statement from 2016-01-27 through 2026-09-16,
fetched, parsed, diffed, and committed as CSV.

The engine passes 79 tests and works on the three most recent statements. This
design is about the other eighty-six, where it does not.

## Why this is its own spec

"Pre-2016 statement format" sat on the README as a bounded regex fix. Probing
the real corpus refuted that. Measured against all 89 discovered statements,
the current engine fails as follows:

| Check | Fails | Rate |
|---|---|---|
| **Lead paragraph silently deleted** | **86 / 89** | **97%** |
| `parse_vote` | 86 / 89 | 96% |
| Paragraphs left `unclassified` | 84 / 89 | 94% |
| Duplicate `policy` roles | 45 / 89 | 50% |
| `parse_target_range` | 15 / 89 | 16% |
| Dissent paragraph found | 2 / 89 | 2% |
| **Clean on every check** | **2 / 89** | **2%** |

Two documents out of eighty-nine survive intact. That is a subsystem, not a
patch.

## Scope

**In:** 2016-01-27 through 2026-09-16 — 89 statements, verified discoverable
and HTTP 200 on 2026-09-16.

**Out:** 2008-2015. The original spec's floor was 2008; this design stops at
2016 to halve the fixture burden and avoid the unverified pre-2008 URL space.
Extending the floor is a later, separate decision. Consequence, stated plainly:
Claim B (dissent as a leading indicator) is computed over 89 meetings, not the
~145 the original spec assumed.

**Also out:** minutes, SEP backfill, FRED join, charts, annotation.

---

## Defect 1 — the boilerplate filter deletes real content

This is the most serious defect in the codebase and the root cause of most of
the table above.

`parse.py` drops a paragraph whole when it starts with a known boilerplate
prefix. On 86 of 89 documents the Fed's markup glues the release line, the
"Share" widget, and **the entire opening economic-assessment paragraph** into a
single `<p>`:

> "For release at 2:00 p.m. EST Share Recent indicators suggest that economic
> activity has continued to expand at a solid pace..."

`startswith("For release at")` matches, and the lead paragraph of nearly every
statement in the corpus is discarded. The worst case is 2020-03-03, the
emergency 50 basis point cut, where the decision itself is inside that
paragraph:

> "For release at 10:00 a.m. EST Share The fundamentals of the U.S. economy
> remain strong. ... the Federal Open Market Committee **decided today to lower
> the target range for the federal funds rate by 1/2 percentage point, to 1 to
> 1-1/4 percent.**"

That statement parses "successfully" to a single paragraph — the voting list —
with the rate decision silently deleted. Nothing raises.

**Why it went unnoticed:** the three most recent 2026 statements do not have
the glue, which is why the engine appeared to work and why the founding
June-to-July probe was correct.

**Fix.** Boilerplate removal becomes surgical: strip the known prefix (a
release line matches `^For release at [\d:]+ [ap]\.m\. E[SD]T\s*(Share\s*)?`)
and keep the remainder. A paragraph is dropped only when nothing substantive
survives the strip.

**Guard.** A statement parsing to fewer than 3 paragraphs raises, except where
a fixture records a known-short emergency statement. Repaired, 2020-03-03
yields 2 paragraphs — decision and vote — which is genuinely all it contains.

This defect also qualifies a claim the README makes, and the correction belongs
in the README: "empty is never quiet" held for the parse failures that raised,
but this path was neither empty nor quiet — it was **confidently short**. The
new guard is what makes the claim true.

## Defect 2 — `a.htm` is not an identity

`statement_url(date)` builds `monetary{YYYYMMDD}a.htm`. The `a` suffix means
"first press release that day," not "the policy statement."

| URL | What it actually is |
|---|---|
| `monetary20081216a.htm` | Term Auction Facility auction results (the statement is at `b.htm`) |
| `monetary20160127b.htm` | Statement on Longer-Run Goals — same day as the January statement |
| `monetary20250822a.htm` | 2025 framework revision, at the `a` suffix, not a meeting statement |
| `monetary20190130c.htm` | Statement Regarding Balance Sheet Normalization |

None raise. `monetary20081216a.htm` returns two `unclassified` paragraphs and
would be filed as a meeting.

**Fix — `discover.py`.** Read the Fed's own listings and keep only what they
label as a statement. Never construct a statement URL from a date again.

- Sources: `/monetarypolicy/fomchistorical{YYYY}.htm` for 2016-2020,
  `/monetarypolicy/fomccalendars.htm` for 2021-present.
- Keep an anchor only if its text is exactly `Statement` (historical pages) or
  `HTML` (current calendar). Both verified against the live pages.
- Yields `{meeting_date: url}`.

**Guard — the label vocabulary is closed.** The two accepted labels sit
alongside eight other observed labels. An anchor adjacent to a `monetary*.htm`
link whose label is in neither the accept set nor the known reject set
**raises**. A ninth Fed document type must be a red test, not a silent
inclusion or omission.

**Guard — count.** Any complete calendar year yielding fewer than 8 statements
raises; the in-progress year is exempt. Verified counts: 8 for 2016-2018, 9 for
2019 (one unscheduled action), 10 for 2020 (two emergency cuts), 8 for
2021-2025, 6 for 2026 to date. Total 89.

## Defect 3 — "Voting for" and "Voting against" share a paragraph

In 2016-2025 they are one paragraph:

> "Voting for the monetary policy action were Jerome H. Powell, Chair, ...
> Voting against the action were James Bullard, who preferred at this meeting to
> lower **the target range for the federal funds rate** to 1-1/2 to 1-3/4
> percent; and Esther L. George and Eric S. Rosengren, who preferred ..."
> — 2019-09-18

It contains the `policy` anchor phrase, because the dissenter's preferred
alternative names the target range. So `role_for` tags it `policy`, colliding
with the real policy paragraph; the `dissent` anchor
(`startswith("Voting against")`) never fires; and when nobody dissents the
paragraph matches nothing and falls to `unclassified`.

The codebase already met this trap — `role_for` carries a comment that
`dissent` MUST precede `policy` for exactly this reason. The rule was right and
its scope was too narrow.

**Fix.** Two roles, `vote_for` and `vote_against`, both checked before
`policy`. This handles all three observed shapes with no special-casing:

| Shape | Documents | Result |
|---|---|---|
| Combined paragraph | 2016-2025 | one `vote_for`; against-clause extracted within it |
| Split paragraphs | 2020-09-16 | one `vote_for`, one `vote_against` |
| Separate dissent, counted vote | 2026 | `vote_against` only |

## Defect 4 — the vote count is not printed before 2026

`by a N-M vote` is absent from every statement 2016 through 2025, and present
in only 3 of the 6 2026 statements. **The counted format is the 2026 novelty,
not a 2016 boundary.**

**Fix.** `parse_vote` branches: use the printed count when present, else count
names in the `vote_for` paragraph, splitting at "Voting against".

Named-list details, all observed:

- the against-clause is singular or plural — "Voting against this action
  **was** Stephen I. Miran" (2025-09-17); "Voting against the action **were**
  James Bullard ... and Esther L. George and Eric S. Rosengren" (2019-09-18)
- an absent against-clause means zero dissents: a fact, not a failure
- names are separated by semicolons or commas, with a trailing "and"
- titles ("Chair", "Vice Chair", "Vice Chairman") are appositives on a name,
  not separate voters, and must not be counted

**Validation is by hand-verified fixtures, not cross-checking.** An earlier
draft of this spec proposed asserting that documents carrying both formats
agree. Measured: **zero documents carry both.** The eras are disjoint and that
test could never fail. Instead, five documents spanning the vote shapes have
their counts verified by hand and recorded as fixtures, including 2019-09-18
(7-3, three dissenters), 2025-09-17 (11-1, singular "was"), 2021-12-15
(unanimous, no against-clause), and 2020-09-16 (split paragraphs).

## Defect 5 — two paragraphs share the `policy` anchor

Separate from the vote collision, 34 documents carry two paragraphs containing
"target range for the federal funds rate":

- decision: "the Committee decided to maintain **the target range for the
  federal funds rate** at 1/4 to 1/2 percent"
- reaction function: "In determining the timing and size of future adjustments
  to **the target range for the federal funds rate**, the Committee will
  assess..."

**Fix.** `policy` requires a decision verb as well as the phrase, as a regex —
`Committee decided (today )?to` — because the literal substring "Committee
decided to" misses 2020-03-03's "decided **today** to lower". The
reaction-function paragraph takes the `guidance` role.

Because `policy` becomes strictly narrower, an era phrasing the decision
differently produces zero `policy` paragraphs rather than a wrong one, and that
raises.

## Role taxonomy

Ordered; first match wins.

| Role | Anchor |
|---|---|
| `vote_for` | begins "Voting for" |
| `vote_against` | begins "Voting against" |
| `policy` | matches `Committee decided (today )?to` and contains "target range for the federal funds rate" |
| `directive` | contains "directs the Desk" |
| `guidance` | contains "In determining the timing and size of future adjustments" or "In assessing the appropriate stance of monetary policy" |
| `outlook_risk` | contains "path of the economy" |
| `commitment` | contains "committed to using its full range of tools" |
| `mandate` | contains "seeks to achieve maximum employment" or "Consistent with its statutory mandate" |
| `balance_sheet` | contains "reinvest" or "holdings of Treasury securities" |
| `economy` | lead economic-assessment paragraph |
| `inflation` | begins "Inflation" |
| `unclassified` | everything else |

Roles are drawn from measured frequency across the repaired corpus, not
invented: "In assessing the appropriate stance of monetary policy" appears in
46 documents, "committed to using its full range of tools" in 14, "Consistent
with its statutory mandate" in 19, the reinvestment paragraph in 12.

**The `economy` anchor requires calibration against fixtures.** Its wording
varies across the corpus ("Information received since the Federal Open Market
Committee met in...", "Recent indicators suggest that...", "Indicators of
economic activity and employment...", "Available indicators suggest..."). A
loose anchor collides with other paragraphs; a tight one misses eras. Tests 9
and 10 below are the gate, and settling this anchor is the substance of the
parse milestone rather than a detail of it.

**`statement_type`.** Two documents — 2019-10-11 (reserve management) and
2020-03-23 (unlimited purchases) — are Desk directives with no rate decision.
`meetings.csv` gains `statement_type` (`decision` | `operational`). Only
`decision` rows require a `policy` paragraph and a vote. This keeps the
no-policy-raises rule intact without forcing a false decision row.

## `backfill.py`

Discover, fetch (cached, 1 req/sec), parse, diff consecutive pairs, write
`meetings.csv`, `statements.csv`, `diffs.csv`, `manifest.csv`.

Re-running against a warm cache is a no-op and must produce byte-identical
CSVs. Row counts must not decrease relative to the committed tables.

## Corrections to the original spec

**Test #2, "zero `unclassified` paragraphs across all committed documents", can
never pass.** Statements carry genuine one-off content: the 2023 banking stress
("The U.S. banking system is sound and resilient", 6 documents), Ukraine
("Russia's war against Ukraine", 5), COVID variants. Forbidding `unclassified`
forces junk roles onto real content.

Replacement: **any paragraph opening recurring in 8 or more documents must
carry a role.** Verified achievable — against the repaired corpus and the
taxonomy above, the most frequent remaining `unclassified` opening appears in
5 documents, leaving margin. This catches anchor rot and Fed HTML drift, which
is what the test was for, without forbidding episodic content.

**The README's "pre-2016 statement format" entry is wrong** and is rewritten.
The named-list vote format runs 2016-2025; there is no 2016 boundary.

**The README's "empty is never quiet" claim is qualified** per Defect 1.

## Testing

Each test names a specific failure and is disable-proofed by breaking the code
it names.

| # | Test | Detects |
|---|---|---|
| 1 | 2020-03-03 parses to 2 paragraphs and yields the 1 to 1-1/4 percent decision | Defect 1 — the boilerplate filter eating the rate decision |
| 2 | Every document in the corpus yields a non-empty lead economic paragraph | Defect 1 at corpus scale (86 documents) |
| 3 | A statement parsing to fewer than 3 paragraphs raises, unless fixture-exempt | confidently-short output, the failure mode "empty is never quiet" missed |
| 4 | `discover` resolves 2016-01-27 to `...a.htm` and never `...b.htm` | Defect 2 — the same-day Longer-Run Goals document |
| 5 | An anchor with an unknown label adjacent to a `monetary*.htm` link raises | a ninth Fed document type entering or bypassing the corpus |
| 6 | A complete year yielding fewer than 8 statements raises | a listing-page change silently truncating the corpus |
| 7 | 2019-09-18 parses as `vote_for`, not `policy`, and yields 7-3 | Defect 3; ordering regression between vote roles and `policy` |
| 8 | 2025-09-17 ("was Stephen I. Miran") yields 11-1; 2021-12-15 yields 0 against and does not raise | Defect 4 — singular clause, and unanimity read as failure |
| 9 | No document yields two paragraphs of the same role among `policy`, `economy`, `inflation`, `vote_for`, `vote_against` | Defect 5 and `economy` anchor over-broadening |
| 10 | No paragraph opening recurring in >=8 documents is `unclassified` | anchor rot and Fed HTML drift (replaces original Test #2) |
| 11 | A `decision` row with no `policy` paragraph raises; an `operational` row does not | the narrowed `policy` anchor matching nothing in a new era |
| 12 | Backfill re-run against a warm cache is byte-identical | nondeterminism entering the committed dataset |

## Failure modes

- **Discovery returning nothing** must raise, not write an empty corpus. The
  listing pages are the single point of failure for the whole backfill.
- **A date appearing in the listings twice** resolves to the first occurrence
  and is logged; never silently resolved by dict-overwrite.
- **Fed edits a published statement.** The manifest SHA mismatches on refetch
  and the run fails. This is the manifest's only job.
- **Cache poisoning from the old builder.** `data/raw/` may already hold
  documents fetched by `statement_url()`, including wrong ones. The backfill
  verifies each cache entry's `.meta.json` URL against the discovered URL;
  `CacheCollisionError` already covers this.

## What this does not fix

- `dissent_direction` is parsed from within the `vote_for` paragraph rather
  than getting its own role.
- Individual dissenter names are captured, but a participant-level panel is not
  built here.
- 2008-2015 remains out of the corpus.

## Milestones

1. `parse.py` boilerplate repair and the minimum-paragraph guard (Defect 1)
2. `discover.py` with its guards, fixtures for both listing-page shapes (Defect 2)
3. `parse.py` role taxonomy, vote roles, `economy` anchor calibration (Defects 3, 5)
4. `meetings.py` named-list branch and hand-verified fixtures (Defect 4)
5. `backfill.py`, `statement_type`, and the committed CSVs
6. README rewrite: corpus coverage, the corrected era claim, the qualified
   "empty is never quiet" claim, the new roles
