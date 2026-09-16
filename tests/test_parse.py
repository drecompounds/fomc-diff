import collections
from pathlib import Path
import pytest
from fomc_diff.parse import (
    extract_paragraphs, role_for, parse_statement, ArticleContainerError,
    _opens_with_economic_assessment)

FIX = Path(__file__).parent / "fixtures"
UNIQUE_ROLES = ("policy", "economy", "inflation", "vote_for", "vote_against")

def _html(name): return (FIX / name).read_text(encoding="utf-8")

def test_july_has_five_body_paragraphs():
    """Five, not four: the vote-announcement line was being deleted by the
    release-line boilerplate filter until that defect was fixed."""
    paras = parse_statement(_html("statement_20260729.html"))
    assert len(paras) == 5

def test_june_has_four_body_paragraphs():
    paras = parse_statement(_html("statement_20260617.html"))
    assert len(paras) == 4

def test_roles_assigned_by_anchor_not_position():
    paras = parse_statement(_html("statement_20260729.html"))
    assert [p.role for p in paras] == [
        "vote", "policy", "economy", "inflation", "vote_against"]

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
     "vote_against"),
    ("The Committee went bowling.", "unclassified"),
])
def test_role_for(text, expected):
    assert role_for(text) == expected

def test_missing_article_container_raises_error():
    html_without_article = "<html><body><p>Some text</p></body></html>"
    with pytest.raises(ArticleContainerError) as exc_info:
        extract_paragraphs(html_without_article)
    assert "Article container not found" in str(exc_info.value)
    assert "unrecognised" in str(exc_info.value)

def test_unterminated_article_container_raises_error():
    html_unterminated = '<div id="article"><p>Some text</p>'
    with pytest.raises(ArticleContainerError) as exc_info:
        extract_paragraphs(html_unterminated)
    assert "Article container unterminated" in str(exc_info.value)
    assert "no matching closing tag" in str(exc_info.value)

def test_error_messages_are_different():
    html_missing = "<html><body><p>Some text</p></body></html>"
    html_unterminated = '<div id="article"><p>Some text</p>'

    try:
        extract_paragraphs(html_missing)
    except ArticleContainerError as e:
        missing_msg = str(e)

    try:
        extract_paragraphs(html_unterminated)
    except ArticleContainerError as e:
        unterminated_msg = str(e)

    assert missing_msg != unterminated_msg
    assert "not found" in missing_msg
    assert "unterminated" in unterminated_msg


# --- Defect 1: the boilerplate filter deleted real content -------------------
# The Fed glues the release line and the "Share" widget onto the first body
# paragraph in 86 of the 89 statements from 2016-2026. Dropping a paragraph
# whole because it STARTS with boilerplate therefore deleted the lead economic
# paragraph corpus-wide -- and on 2020-03-03 it deleted the rate decision.

def test_release_line_does_not_swallow_the_rate_decision():
    """2020-03-03, the emergency 50bp cut, carried its decision in the same
    <p> as 'For release at 10:00 a.m. EST Share'. The old filter matched the
    prefix and discarded the paragraph, so the statement parsed to exactly one
    paragraph -- the voting list -- with the decision silently gone."""
    paras = parse_statement(_html("statement_20200303.html"))
    joined = " ".join(p.text for p in paras)
    assert "decided today to lower the target range" in joined
    assert "1 to 1‑1/4 percent" in joined or "1 to 1-1/4 percent" in joined


def test_release_line_itself_is_still_stripped():
    """Fixing the swallow must not re-admit the boilerplate it was written to
    remove. The prefix goes; the sentence after it stays."""
    paras = parse_statement(_html("statement_20200303.html"))
    joined = " ".join(p.text for p in paras)
    assert "For release at" not in joined
    assert "EST Share" not in joined


def test_lead_economic_paragraph_survives_in_a_normal_statement():
    """The same glue sits on every ordinary statement, where it was eating the
    opening economic assessment rather than the decision."""
    paras = parse_statement(_html("statement_20250917.html"))
    joined = " ".join(p.text for p in paras)
    assert "growth of economic activity moderated" in joined
    assert "For release at" not in joined


def test_a_statement_never_parses_to_fewer_than_two_paragraphs():
    """Confidently-short output is the failure mode that hid this defect: the
    parse did not raise and did not return empty, it returned one plausible
    paragraph. Every real statement has at least a decision and a vote."""
    for name in ("statement_20200303.html", "statement_20250917.html",
                 "statement_20260916.html"):
        assert len(parse_statement(_html(name))) >= 2, name


def test_html_comments_do_not_leak_into_paragraph_text():
    """The 2026-09-16 statement wraps its vote line in HTML comments. Tag
    stripping alone cannot remove them -- <[^>]+> stops at the first '>' inside
    '<!-- ... -->' -- so '-->' fragments survived into the text, and therefore
    into its sha256, which is the provenance key."""
    for name in ("statement_20260916.html", "statement_20260729.html"):
        for p in parse_statement(_html(name)):
            assert "-->" not in p.text, f"{name}: comment residue in {p.text[:60]!r}"
            assert "<!--" not in p.text


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


# --- Task 4: narrow `policy`, widen the taxonomy -----------------------------

def test_reaction_function_is_guidance_not_a_second_policy_paragraph():
    """2016-03-16 has both 'the Committee decided to maintain the target
    range...' and 'In determining the timing and size of future adjustments to
    the target range...'. Both match the bare anchor phrase."""
    paras = parse_statement(_html("statement_20160316.html"))
    assert len([p for p in paras if p.role == "policy"]) == 1
    assert any(p.role == "guidance" for p in paras)


def test_emergency_cut_yields_exactly_one_policy_paragraph():
    """2020-03-03, the emergency 50bp cut, must produce one policy paragraph
    carrying the decision.

    This test does NOT discriminate the _DECIDED regex from a literal
    "Committee decided to" substring, and an earlier docstring wrongly claimed
    it did: "to" is a prefix of "today", so the literal matches
    "decided today to lower" by coincidence. What this guards is that the
    decision paragraph EXISTS and is tagged policy -- it goes red if the
    boilerplate filter starts eating it again (the original Defect 1) or if the
    policy anchor stops matching altogether.

    The regex is kept for whitespace robustness ("decided
 to"), not because
    the literal fails on this fixture.
    """
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


def test_every_statement_with_a_decision_has_an_economy_paragraph():
    """The prior gates checked that roles never duplicate and that recurring
    paragraphs are classified. Neither asserts the economy role EXISTS, so an
    anchor matching nothing satisfied both -- on 22 of the 89 real statements.

    Two documented exemptions, both by condition rather than by filename:
      - Desk directives carry no economic assessment at all.
      - A statement that FUSES its assessment and its decision into one
        paragraph (2020-03-03) can only express one role for it, and `policy`
        wins because the decision is the more load-bearing fact.
    """
    for f in sorted(FIX.glob("statement_*.html")):
        paras = parse_statement(f.read_text(encoding="utf-8"))
        roles = [p.role for p in paras]
        if "directive" in roles:
            continue
        policy = next((p for p in paras if p.role == "policy"), None)
        if policy is not None and _opens_with_economic_assessment(policy.text):
            continue          # fused paragraph; see docstring
        assert roles.count("economy") == 1, f"{f.name}: {roles}"


def test_the_fused_paragraph_exemption_is_narrow():
    """The exemption must require BOTH conditions. A statement whose policy
    paragraph does not open with an assessment gets no free pass."""
    paras = parse_statement(_html("statement_20250917.html"))
    policy = next(p for p in paras if p.role == "policy")
    assert not _opens_with_economic_assessment(policy.text)
