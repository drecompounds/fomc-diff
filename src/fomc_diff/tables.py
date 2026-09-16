"""CSV writing. Empty is never quiet."""
from __future__ import annotations

import csv
from pathlib import Path


class EmptyTableError(RuntimeError):
    """Raised when a table would be written with zero rows."""


def write_table(path: Path, fieldnames: list[str], rows: list[dict]) -> int:
    if not rows:
        raise EmptyTableError(
            f"refusing to write {path.name} with 0 rows; "
            "an empty table is a parse failure, not a quiet result"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
