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


import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

UA = "fomc-diff/0.1 (open data project; contact via GitHub issues)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    from_cache: bool


def _cache_name(url: str) -> str:
    return Path(urlparse(url).path).name


def fetch(url: str, cache_dir: Path, *, session=None, sleep=time.sleep) -> FetchResult:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / _cache_name(url)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if path.exists():
        body = path.read_text(encoding="utf-8")
        return FetchResult(url, path,
                           hashlib.sha256(body.encode("utf-8")).hexdigest(),
                           now, True)

    if session is None:
        import requests
        session = requests.Session()

    sleep(1.0)  # 1 req/sec, applied before every real request
    resp = session.get(url, timeout=30, headers={"User-Agent": UA})
    resp.raise_for_status()
    body = resp.text
    path.write_text(body, encoding="utf-8")
    return FetchResult(url, path,
                       hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       now, False)
