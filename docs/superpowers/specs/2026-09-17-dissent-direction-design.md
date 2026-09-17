# Dissent direction and the dissent-lead analysis — design

**Date:** 2026-09-17
**Status:** approved design, not yet implemented
**Author:** Andre (design partner: Claude Opus 5)
**Builds on:** `2026-09-16-corpus-backfill-2016-2026-design.md`

## Purpose

Record *which way* each dissenter wanted to go, and then describe what the
Committee did next. Two deliverables:

1. `dissents.csv` — one row per dissenting official per meeting.
2. A pre-registered descriptive table of what followed a dissent.

## Why a count is not enough

`meetings.csv` records `vote_against` — how many dissented — and nothing about
direction. A hawkish dissent and a dovish dissent are opposite signals carried
by the same number, which makes the count close to uninterpretable on its own.

**Dissents within a single meeting can point in opposite directions.** This is
not an edge case:

> 2019-09-18: "Voting against the action were James Bullard, who preferred at
> this meeting to **lower** the target range...; and Esther L. George and Eric
> S. Rosengren, who preferred to **maintain** the target range..."

Three dissenters, two directions, against a cut. 2026-04-29 is the same shape:
Miran preferred to lower, while Hammack, Kashkari and Logan supported
maintaining but objected to an easing bias.

A single `dissent_direction` column per meeting would force a choice and
silently discard half the record. Hence one row per dissenter.

## Defect: `parse_dissent` is broken on most of the corpus

Measured across the 27 dissent meetings: **17 raise, and of the 10 that
succeed, 2 return the wrong number of names and 3 return `unclear`.**

`_DISSENT = re.compile(r"were (.+?), who (.+)$", re.S)` requires the literal
"were ... , who ...". It fails on:

- the singular "Voting against this action **was** Stephen I. Miran"
- "Voting against the action **were:**" (2016's colon)
- "..., **each of whom** preferred" (2016-09-21, 2016-11-02)
- multi-group clauses split by ";", where it captures only the first group

`_count_dissenters` in `meetings.py` already solves group splitting correctly —
it splits on ";", strips a leading "and", and cuts at the relative clause. The
direction parser must reuse that logic rather than carry a second, weaker copy.
This is the drift pattern that `UNIQUE_ROLES` and the shared dash class were
both centralised to prevent.

## Schema

`dissents.csv`, one row per dissenter per meeting:

| Column | Meaning |
|---|---|
| `meeting_date` | join key to `meetings.csv` |
| `name` | the official, as printed |
| `direction` | `lower` \| `raise` \| `maintain` \| `unclear` |

`unclear` is a real value, not a failure. 2026-04-29's second group objected to
an easing bias while supporting the rate itself; forcing that into `raise` or
`maintain` would be a fabricated number. It is recorded as `unclear` and
reported as such.

**Invariant:** the number of `dissents.csv` rows for a meeting must equal that
meeting's `vote_against`. A mismatch raises. This is what makes the two tables
mutually checking rather than independently wrong.

## The analysis

**Pre-registration is the point.** The rule is written to
`config/dissent_lead.yaml` and committed *before* any result is computed. The
file's git history is the proof, and the commit that adds it must land before
the commit that adds the output.

Rule, fixed in advance:

- For each meeting with at least one dissent, look ahead `N` meetings for
  `N` in **1, 2, 3, 4** — **all four reported, no subset**.
- "A move in the dissent's direction" means: a dissenter preferring `lower`
  is followed by a `cut`; preferring `raise` by a `hike`. `maintain` and
  `unclear` dissents are reported separately and are not scored.
- Compare against the unconditional base rate of a cut/hike in the same
  horizon, computed over all decision meetings.

### What this can and cannot show

Stated in the output itself, not only here:

- 87 decision meetings, 31 rate changes, 27 meetings with a dissent.
- **The longest run of identical decisions is 15 meetings**, and there are only
  **29 regime switches** in eleven years. Meetings are not independent
  observations; the effective sample is nearer 29 than 87.
- Dissents cluster by person and era — five of 2016's are largely one official.
- Therefore this is **descriptive**, not a test. No p-values, no significance
  claims, no "signal". A null result is the expected outcome and will be
  published as readily as any other.

The README must carry that framing wherever the table appears. The project
already states it makes no forecast and carries no backtest; this analysis does
not change that and must not be presented as if it did.

## Testing

| # | Test | Detects |
|---|---|---|
| 1 | 2019-09-18 yields 3 rows: Bullard `lower`, George `maintain`, Rosengren `maintain` | the multi-direction case that motivates the whole schema |
| 2 | 2025-09-17 ("was Stephen I. Miran") yields 1 row, `lower` | the singular clause |
| 3 | 2016-09-21 ("each of whom") yields 3 rows, all same direction | the clause form that already caused a wrong vote count |
| 4 | Row count per meeting equals `vote_against`, across the whole corpus | the two tables silently disagreeing |
| 5 | A dissent clause matching no known direction yields `unclear`, never a guess | a fabricated direction |
| 6 | The analysis reports all four horizons | horizon-shopping |
| 7 | Mutating `config/dissent_lead.yaml` changes the output | that the config has a real reader; a config test that passes without one is vacuous |

## Milestones

1. Rewrite `parse_dissent` on the shared group-splitting logic; `dissents.csv`
2. Pre-register `config/dissent_lead.yaml` and commit it, before any output
3. Compute and publish the descriptive table, all horizons, with the caveats
