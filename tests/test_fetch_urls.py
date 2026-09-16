from datetime import date
from fomc_diff.fetch import statement_url, minutes_url, minutes_pdf_url

BASE = "https://www.federalreserve.gov"

def test_statement_url():
    assert statement_url(date(2026, 7, 29)) == (
        f"{BASE}/newsevents/pressreleases/monetary20260729a.htm")

def test_minutes_url():
    assert minutes_url(date(2026, 7, 29)) == (
        f"{BASE}/monetarypolicy/fomcminutes20260729.htm")

def test_minutes_pdf_url():
    assert minutes_pdf_url(date(2015, 9, 17)) == (
        f"{BASE}/monetarypolicy/files/fomcminutes20150917.pdf")
