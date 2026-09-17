from pathlib import Path
import pytest
from fomc_diff.parse import Paragraph, parse_statement
from fomc_diff.diffing import diff_statements, word_diff, DuplicateRoleError

FIX = Path(__file__).parent / "fixtures"
def _paras(name):
    return parse_statement((FIX / name).read_text(encoding="utf-8"))

def _para(index, role, text):
    return Paragraph(index, role, text, "deadbeef")

def test_word_diff_marks_replacement():
    out = word_diff("the Committee reaffirmed its policy",
                    "the Committee is continuing its policy")
    assert "[-reaffirmed-]" in out
    assert "[+is continuing+]" in out

def test_golden_june_to_july_2026():
    """The founding finding. If this breaks, the repo's premise broke."""
    rows = diff_statements(_paras("statement_20260617.html"),
                           _paras("statement_20260729.html"))
    by_role = {r.role: r for r in rows}

    assert by_role["policy"].change_type == "changed"
    assert "[-reaffirmed-]" in by_role["policy"].word_diff
    assert "[+is continuing+]" in by_role["policy"].word_diff

    assert by_role["economy"].change_type == "unchanged"
    assert by_role["inflation"].change_type == "unchanged"

    assert by_role["vote_against"].change_type == "added"
    assert "Hammack" in by_role["vote_against"].word_diff

def test_unchanged_rows_have_zero_word_counts():
    rows = diff_statements(_paras("statement_20260617.html"),
                           _paras("statement_20260729.html"))
    assert any(r.change_type == "unchanged" for r in rows), (
        "fixture pair must actually contain an unchanged row, or this "
        "assertion loop passes vacuously"
    )
    for r in rows:
        if r.change_type == "unchanged":
            assert (r.words_added, r.words_removed) == (0, 0)

def test_duplicate_role_in_old_statement_raises():
    old = [
        _para(0, "policy", "first policy paragraph"),
        _para(1, "policy", "second policy paragraph, same role"),
    ]
    new = [_para(0, "policy", "a single policy paragraph")]
    with pytest.raises(DuplicateRoleError) as exc_info:
        diff_statements(old, new)
    assert "policy" in str(exc_info.value)
    assert "old" in str(exc_info.value)

def test_duplicate_role_in_new_statement_raises():
    old = [_para(0, "policy", "a single policy paragraph")]
    new = [
        _para(0, "policy", "first policy paragraph"),
        _para(1, "policy", "second policy paragraph, same role"),
    ]
    with pytest.raises(DuplicateRoleError) as exc_info:
        diff_statements(old, new)
    assert "policy" in str(exc_info.value)
    assert "new" in str(exc_info.value)


def test_repeated_roles_align_by_occurrence_rather_than_collapsing():
    """unclassified/guidance/balance_sheet legitimately repeat -- COVID, Ukraine
    and the 2023 banking-stress paragraphs all land in one statement. Keying by
    bare role dropped every occurrence but the last, and the guard against that
    blocked the entire 89-statement backfill on correct input."""
    old = [
        _para(0, "unclassified", "first unclassified paragraph"),
        _para(1, "unclassified", "second unclassified paragraph"),
    ]
    new = [
        _para(0, "unclassified", "first unclassified paragraph"),
        _para(1, "unclassified", "second unclassified paragraph, revised"),
    ]
    rows = diff_statements(old, new)
    by_role = {r.role: r for r in rows}
    assert set(by_role) == {"unclassified", "unclassified#1"}
    assert by_role["unclassified"].change_type == "unchanged"
    assert by_role["unclassified#1"].change_type == "changed"


def test_a_role_appearing_once_then_twice_still_aligns_the_first():
    """A statement gaining a second guidance paragraph must not cause the
    original one to read as removed-and-re-added."""
    old = [_para(0, "guidance", "the committee will monitor incoming data")]
    new = [
        _para(0, "guidance", "the committee will monitor incoming data"),
        _para(1, "guidance", "a brand new second guidance paragraph appears"),
    ]
    rows = diff_statements(old, new)
    by_role = {r.role: r for r in rows}
    assert set(by_role) == {"guidance", "guidance#1"}
    assert by_role["guidance"].change_type == "unchanged"
    assert by_role["guidance#1"].change_type == "added"


def test_duplicate_unique_role_still_raises():
    """Two 'policy' paragraphs remain an error: they would collapse into one
    entry and lose a paragraph with no warning."""
    old = [
        _para(0, "policy", "first policy paragraph"),
        _para(1, "policy", "second policy paragraph, same role"),
    ]
    new = [_para(0, "policy", "a single policy paragraph")]
    with pytest.raises(DuplicateRoleError):
        diff_statements(old, new)
