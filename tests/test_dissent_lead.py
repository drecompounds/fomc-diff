"""The analysis must report what the pre-registered rule says, not a subset."""
from pathlib import Path

import pytest

from fomc_diff.dissent_lead import analyse, load_rule

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "dissent_lead.yaml"
MEETINGS = ROOT / "data" / "meetings.csv"
DISSENTS = ROOT / "data" / "dissents.csv"


def test_all_pre_registered_horizons_are_reported():
    """Horizon-shopping is the failure this analysis is built to prevent:
    try 1/2/3/4, report whichever looks best. The config names four and all
    four must appear in the output, whatever they show."""
    rule = load_rule(CONFIG)
    assert rule["horizons"] == [1, 2, 3, 4]
    res = analyse(MEETINGS, DISSENTS, rule)
    assert sorted(res["horizons"]) == [1, 2, 3, 4]


def test_mutating_the_config_changes_the_output():
    """A config check that passes without a real reader is vacuous -- the rule
    file would be decoration. Changing the horizons must change the result."""
    rule = load_rule(CONFIG)
    baseline = analyse(MEETINGS, DISSENTS, rule)
    mutated = dict(rule, horizons=[7])
    other = analyse(MEETINGS, DISSENTS, mutated)
    assert sorted(other["horizons"]) == [7]
    assert sorted(other["horizons"]) != sorted(baseline["horizons"])


def test_only_directional_dissents_are_scored():
    """A dissenter who wanted no change has no directional prediction to check.
    Scoring `maintain` or `unclear` would invent a prediction they never made,
    and they are 42 percent of the sample -- too large to absorb silently."""
    rule = load_rule(CONFIG)
    assert set(rule["scoring"]) == {"lower", "raise"}
    res = analyse(MEETINGS, DISSENTS, rule)
    assert res["scored"] + res["unscored"] == res["n_dissents"]
    assert res["unscored"] > 0, "if nothing is unscored, the split is not real"


def test_every_row_carries_its_sample_size():
    """A rate without an n is unreadable, and n here is small enough that
    omitting it would be misleading rather than merely terse."""
    rule = load_rule(CONFIG)
    res = analyse(MEETINGS, DISSENTS, rule)
    for h in res["horizons"].values():
        for row in h["rows"]:
            assert "trials" in row and isinstance(row["trials"], int)


def test_the_baseline_is_unconditional_not_drawn_from_dissent_meetings():
    """Comparing dissent meetings against a baseline built from dissent
    meetings would be circular -- the comparison would measure nothing."""
    rule = load_rule(CONFIG)
    res = analyse(MEETINGS, DISSENTS, rule)
    for h, block in res["horizons"].items():
        # the baseline sample is every decision meeting with a full lookahead,
        # which must far exceed the count of dissent observations
        assert block["baseline_n"] > max(r["trials"] for r in block["rows"])


def test_a_rule_declaring_no_horizons_raises(tmp_path):
    """Empty is never quiet: a rule file that parses but declares nothing must
    fail loudly, not silently analyse zero horizons and report an empty table
    that looks like a finished result."""
    bad = tmp_path / "rule.yaml"
    bad.write_text("# a comment and nothing else\nunit: dissenter\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="horizons"):
        load_rule(bad)
