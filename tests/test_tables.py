import csv
from pathlib import Path
import pytest
from fomc_diff.tables import write_table, EmptyTableError

def test_writes_rows_and_returns_count(tmp_path: Path):
    p = tmp_path / "t.csv"
    n = write_table(p, ["a", "b"], [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    assert n == 2
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert rows[0]["a"] == "1"

def test_zero_rows_raises_and_writes_nothing(tmp_path: Path):
    p = tmp_path / "t.csv"
    with pytest.raises(EmptyTableError):
        write_table(p, ["a"], [])
    assert not p.exists(), "an empty table must never reach disk"

def test_existing_file_untouched_when_new_data_is_empty(tmp_path: Path):
    p = tmp_path / "t.csv"
    write_table(p, ["a"], [{"a": 1}])
    before = p.read_text(encoding="utf-8")
    with pytest.raises(EmptyTableError):
        write_table(p, ["a"], [])
    assert p.read_text(encoding="utf-8") == before

def test_line_endings_are_lf_not_crlf(tmp_path: Path):
    p = tmp_path / "t.csv"
    write_table(p, ["a"], [{"a": 1}])
    assert b"\r\n" not in p.read_bytes()
