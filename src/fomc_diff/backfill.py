"""Drive discover + fetch + parse + meetings + diffing into the committed CSVs.

`build_rows` is offline: it takes an already-fetched `{date: html}` mapping
and returns the three tables derivable from that alone (meetings, statements,
diffs). It never touches the network or the filesystem, so it is exactly what
the test suite exercises.

`run()` is the only network- and filesystem-touching entry point. It resolves
the listing pages, fetches every statement (rate-limited, cached), builds the
three tables via `build_rows`, and additionally writes a manifest table
recording the provenance of every fetched document -- that is why
`data/raw/` itself is gitignored (see the repo's .gitignore):
reproducibility comes from the manifest, not from the cache.

The manifest records a hash of the EXTRACTED TEXT, not of the raw bytes.
The Fed's pages are not byte-stable: Cloudflare injects a randomised
email-protection token and a per-response script, so two fetches a second
apart produce different bytes and a different raw sha256. A raw hash
therefore mismatches on every refetch and can never distinguish a real
edit from that noise -- which is the manifest's only job. The extracted
text was verified stable across repeated fetches of both a 2016 and a
2026 statement.

The raw-bytes hash still lives in each cache entry's sidecar, where it is
the right check: it detects local corruption of a file at rest.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path

from . import discover
from .discover import DiscoveryError, build_corpus, listing_urls
from .errors import FomcParseError
from .fetch import fetch
from .parse import parse_statement
from .diffing import diff_statements
from .meetings import (
    parse_vote, parse_target_range, derive_decision, dissent_clause,
    parse_dissent,
)
from .tables import write_table

MEETINGS_FIELDS = [
    "meeting_date", "statement_type", "vote_for", "vote_against",
    "target_lower", "target_upper", "decision",
]
STATEMENTS_FIELDS = ["meeting_date", "para_index", "role", "text", "sha256"]
DIFFS_FIELDS = [
    "from_date", "to_date", "role", "change_type",
    "words_added", "words_removed", "word_diff",
]
DISSENTS_FIELDS = ["meeting_date", "name", "direction"]
MANIFEST_FIELDS = ["meeting_date", "url", "content_sha256", "fetched_at", "from_cache"]

# The FOMC raised to 0.25-0.50 percent on 2015-12-16, the meeting before this
# corpus begins. Seeding it makes the first row's decision a measurement
# rather than a default. Source: FOMC statement, December 16, 2015.
SEED_PRIOR_UPPER = 0.50


def build_rows(
    documents: dict[date, str],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Turn `{date: html}` into `(meetings, statements, diffs, dissents)` rows.

    A statement is `operational` when it has a `directive` paragraph and no
    `policy` paragraph (e.g. 2019-10-11, 2020-03-23); otherwise `decision`.
    Only `decision` rows require a vote and a target range -- and a
    `decision` row with no `policy` paragraph raises rather than writing a
    row with empty columns.

    `dissents` carries one row per dissenter, per decision meeting. Its row
    count for a meeting is enforced equal to that meeting's `vote_against` --
    a mismatch raises `FomcParseError` rather than shipping two tables that
    silently disagree.
    """
    dates = sorted(documents)
    meetings: list[dict] = []
    statements: list[dict] = []
    dissents: list[dict] = []
    paras_by_date: dict[date, list] = {}
    # Seeded, not None: derive_decision refuses to default "no prior meeting"
    # to "hold". 2016-01-27 (this corpus's first meeting) comes out "hold"
    # because 0.50 == 0.50, a measurement against the documented prior
    # decision, not a default.
    prev_decision_upper: float | None = SEED_PRIOR_UPPER

    for d in dates:
        html = documents[d]
        paras = parse_statement(html)
        paras_by_date[d] = paras
        roles = {p.role for p in paras}

        for p in paras:
            statements.append({
                "meeting_date": d,
                "para_index": p.index,
                "role": p.role,
                "text": p.text,
                "sha256": p.sha256,
            })

        is_operational = "directive" in roles and "policy" not in roles
        statement_type = "operational" if is_operational else "decision"

        if is_operational:
            meetings.append({
                "meeting_date": d,
                "statement_type": statement_type,
                "vote_for": None,
                "vote_against": None,
                "target_lower": None,
                "target_upper": None,
                "decision": None,
            })
            continue

        if "policy" not in roles:
            raise FomcParseError(
                f"{d}: statement classified as 'decision' has no 'policy' "
                "paragraph (and no 'directive' paragraph either, so it is "
                "not 'operational' either); refusing to write a decision "
                "row with an empty vote and target range"
            )

        vote_for, vote_against = parse_vote(html)
        target_lower, target_upper = parse_target_range(html)
        decision = derive_decision(prev_decision_upper, target_upper)
        prev_decision_upper = target_upper

        clause = dissent_clause(paras)
        dissent_rows = parse_dissent(clause) if clause is not None else []
        if len(dissent_rows) != vote_against:
            raise FomcParseError(
                f"{d}: dissents.csv would carry {len(dissent_rows)} row(s) "
                f"for this meeting but vote_against is {vote_against}; these "
                "two counts must match, or one of them is wrong"
            )
        for name, direction in dissent_rows:
            dissents.append({
                "meeting_date": d,
                "name": name,
                "direction": direction,
            })

        meetings.append({
            "meeting_date": d,
            "statement_type": statement_type,
            "vote_for": vote_for,
            "vote_against": vote_against,
            "target_lower": target_lower,
            "target_upper": target_upper,
            "decision": decision,
        })

    diffs: list[dict] = []
    for prev_d, cur_d in zip(dates, dates[1:]):
        for row in diff_statements(paras_by_date[prev_d], paras_by_date[cur_d]):
            diffs.append({
                "from_date": prev_d,
                "to_date": cur_d,
                "role": row.role,
                "change_type": row.change_type,
                "words_added": row.words_added,
                "words_removed": row.words_removed,
                "word_diff": row.word_diff,
            })

    return meetings, statements, diffs, dissents


def _content_hash(html: str) -> str:
    """Hash the extracted, role-tagged text of a statement.

    Stable across refetches, unlike a hash of the raw bytes, and therefore
    the only hash that can detect the Fed silently editing a published
    document. Includes the role so a paragraph changing role is a change.
    """
    paras = parse_statement(html)
    joined = "\n".join(f"{p.role}\t{p.text}" for p in paras)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def run(cache_dir: Path, out_dir: Path, *, current_year: int) -> None:
    """Discover, fetch, and write the four corpus CSVs.

    Pre-flight guard: `build_corpus`'s per-year minimum only inspects years
    that appear in the merged corpus. A year missing entirely -- a listing
    page that failed to fetch, or whose layout changed so no anchor matched
    -- produces no key, so that guard never sees it. This function is the
    only caller that knows the full intended page set (2016..current_year),
    so the contiguity check belongs here, not in `discover.build_corpus`.
    """
    cache_dir = Path(cache_dir)
    out_dir = Path(out_dir)

    pages: dict[str, str] = {}
    for url in listing_urls(current_year):
        res = fetch(url, cache_dir)
        pages[url] = res.path.read_bytes().decode("utf-8")

    corpus = build_corpus(pages, current_year=current_year)

    years = {d.year for d in corpus}
    expected = set(range(discover.FIRST_YEAR, current_year + 1))
    missing = expected - years
    if missing:
        raise DiscoveryError(
            f"no statements discovered for {sorted(missing)}; a listing page "
            "probably failed to parse. Refusing to write a corpus with a "
            "hole in it.")

    documents: dict[date, str] = {}
    manifest: list[dict] = []
    for d in sorted(corpus):
        url = corpus[d]
        res = fetch(url, cache_dir)
        documents[d] = res.path.read_bytes().decode("utf-8")
        manifest.append({
            "meeting_date": d,
            "url": res.url,
            "content_sha256": _content_hash(documents[d]),
            "fetched_at": res.fetched_at,
            "from_cache": res.from_cache,
        })

    meetings, statements, diffs, dissents = build_rows(documents)

    write_table(out_dir / "meetings.csv", MEETINGS_FIELDS, meetings)
    write_table(out_dir / "statements.csv", STATEMENTS_FIELDS, statements)
    write_table(out_dir / "diffs.csv", DIFFS_FIELDS, diffs)
    write_table(out_dir / "dissents.csv", DISSENTS_FIELDS, dissents)
    write_table(out_dir / "manifest.csv", MANIFEST_FIELDS, manifest)


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill the FOMC statement corpus into CSVs.")
    parser.add_argument("--cache-dir", default="data/raw", type=Path)
    parser.add_argument("--out", dest="out_dir", default="data", type=Path)
    parser.add_argument("--current-year", type=int, default=date.today().year)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    run(args.cache_dir, args.out_dir, current_year=args.current_year)


if __name__ == "__main__":
    main()
