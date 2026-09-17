"""Descriptive: what did the Committee do after a dissent?

The rule this implements is pre-registered in `config/dissent_lead.yaml` and was
committed before any result existed. Every horizon listed there is reported,
whatever it shows. This module computes; it does not select.

This is NOT a test of a hypothesis. See the caveats printed with the output.
"""
from __future__ import annotations

import collections
import csv
from pathlib import Path

# Minimal YAML reader for the flat subset used by dissent_lead.yaml. The
# project is stdlib-only by constraint, and pulling in PyYAML for one flat
# mapping would be a dependency with no other reader.
def load_rule(path: Path) -> dict:
    horizons: list[int] = []
    scoring: dict[str, str] = {}
    caveats: list[str] = []
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("horizons:"):
            body = stripped.split(":", 1)[1].split("#")[0].strip().strip("[]")
            horizons = [int(x) for x in body.split(",") if x.strip()]
            section = None
        elif stripped.startswith("scoring:"):
            section = "scoring"
        elif stripped.startswith("caveats:"):
            section = "caveats"
        elif stripped.startswith(("unit:", "baseline:")):
            section = None
        elif section == "scoring" and ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            scoring[k.strip()] = v.split("#")[0].strip()
        elif section == "caveats" and stripped.startswith("- "):
            caveats.append(stripped[2:].strip().strip('"'))
        elif section == "caveats" and caveats:
            caveats[-1] += " " + stripped.strip('"')
    if not horizons or not scoring:
        raise ValueError(f"{path} declares no horizons or no scoring rule")
    return {"horizons": horizons, "scoring": scoring, "caveats": caveats}


def analyse(meetings_csv: Path, dissents_csv: Path, rule: dict) -> dict:
    meetings = [r for r in csv.DictReader(meetings_csv.open(encoding="utf-8"))
                if r["statement_type"] == "decision"]
    meetings.sort(key=lambda r: r["meeting_date"])
    idx = {r["meeting_date"]: i for i, r in enumerate(meetings)}
    decisions = [r["decision"] for r in meetings]
    n = len(meetings)

    dissents = list(csv.DictReader(dissents_csv.open(encoding="utf-8")))
    scoring = rule["scoring"]

    out: dict = {"n_meetings": n, "n_dissents": len(dissents), "horizons": {}}
    out["scored"] = sum(1 for d in dissents if d["direction"] in scoring)
    out["unscored"] = len(dissents) - out["scored"]

    # How much of each direction is one person, or one era? Printed with the
    # result because a rate computed over 13 votes, 6 of them from the same
    # official, is not 13 observations and must not be read as 13.
    scored_rows = [d for d in dissents if d["direction"] in scoring]
    out["scored_meetings"] = len({d["meeting_date"] for d in scored_rows})
    out["concentration"] = {}
    for direction in scoring:
        rows = [d for d in scored_rows if d["direction"] == direction]
        if not rows:
            continue
        people = collections.Counter(d["name"] for d in rows)
        top_name, top_n = people.most_common(1)[0]
        out["concentration"][direction] = {
            "n": len(rows),
            "people": len(people),
            "years": len({d["meeting_date"][:4] for d in rows}),
            "top_name": top_name,
            "top_n": top_n,
        }

    for h in rule["horizons"]:
        # Unconditional baseline: over all decision meetings that HAVE an
        # h-meeting lookahead, how often does a cut (or hike) occur within it?
        base: dict[str, int] = {}
        base_n = 0
        for i in range(n):
            if i + h >= n:
                continue
            base_n += 1
            window = decisions[i + 1:i + 1 + h]
            for move in set(scoring.values()):
                if move in window:
                    base[move] = base.get(move, 0) + 1

        rows = []
        for direction, move in scoring.items():
            hits = trials = 0
            for d in dissents:
                if d["direction"] != direction:
                    continue
                i = idx.get(d["meeting_date"])
                if i is None or i + h >= n:
                    continue
                trials += 1
                if move in decisions[i + 1:i + 1 + h]:
                    hits += 1
            rows.append({
                "direction": direction,
                "move": move,
                "trials": trials,
                "hits": hits,
                "rate": hits / trials if trials else None,
                "base_rate": base.get(move, 0) / base_n if base_n else None,
            })
        out["horizons"][h] = {"baseline_n": base_n, "rows": rows}
    return out


def format_report(res: dict, rule: dict) -> str:
    L = []
    L.append("What followed a dissent, 2016-2026")
    L.append("=" * 62)
    L.append("")
    L.append(f"{res['n_meetings']} decision meetings, {res['n_dissents']} dissenting votes.")
    L.append(f"{res['scored']} carry a directional preference and are scored; "
             f"{res['unscored']} do not "
             f"({100 * res['unscored'] // res['n_dissents']}% of the sample).")
    L.append("")
    L.append(f"{'horizon':>7} {'dissent':>8} {'->':^3} {'move':>4} "
             f"{'n':>3} {'hits':>5} {'rate':>6} {'base':>6} {'lift':>6}")
    L.append("-" * 62)
    for h in sorted(res["horizons"]):
        for r in res["horizons"][h]["rows"]:
            if r["rate"] is None:
                L.append(f"{h:>7} {r['direction']:>8} {'->':^3} {r['move']:>4} "
                         f"{0:>3}   (no observations)")
                continue
            lift = r["rate"] - r["base_rate"]
            L.append(f"{h:>7} {r['direction']:>8} {'->':^3} {r['move']:>4} "
                     f"{r['trials']:>3} {r['hits']:>5} {r['rate']:>5.0%} "
                     f"{r['base_rate']:>5.0%} {lift:>+5.0%}")
        L.append("")
    L.append("n is the number of DISSENTING OFFICIALS with a full lookahead --")
    L.append("not independent meetings, and not independent people.")
    L.append("")
    L.append("How concentrated the sample is:")
    for direction, c in sorted(res["concentration"].items()):
        L.append(f"  {direction:>6}: {c['n']} votes from {c['people']} officials "
                 f"across {c['years']} years; {c['top_name']} is "
                 f"{c['top_n']} of {c['n']} ({100 * c['top_n'] // c['n']}%)")
    L.append(f"  the whole scored sample comes from {res['scored_meetings']} "
             "distinct meetings")
    L.append("")
    L.append("Read this as description, not evidence:")
    for c in rule["caveats"]:
        L.append(f"  - {c}")
    return "\n".join(L)


def main(argv=None) -> None:
    root = Path(__file__).resolve().parents[2]
    rule = load_rule(root / "config" / "dissent_lead.yaml")
    res = analyse(root / "data" / "meetings.csv",
                  root / "data" / "dissents.csv", rule)
    print(format_report(res, rule))


if __name__ == "__main__":
    main()
