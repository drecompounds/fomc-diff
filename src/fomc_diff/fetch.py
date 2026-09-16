"""Fetch FOMC documents. The only module permitted to touch the network."""
from __future__ import annotations

from datetime import date

BASE = "https://www.federalreserve.gov"


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d")


def statement_url(d: date) -> str:
    return f"{BASE}/newsevents/pressreleases/monetary{_stamp(d)}a.htm"


def minutes_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/fomcminutes{_stamp(d)}.htm"


def minutes_pdf_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/files/fomcminutes{_stamp(d)}.pdf"
