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

    assert by_role["dissent"].change_type == "added"
    assert "Hammack" in by_role["dissent"].word_diff

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
