from pathlib import Path
import pytest
from fomc_diff.parse import extract_paragraphs, role_for, parse_statement, ArticleContainerError

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
