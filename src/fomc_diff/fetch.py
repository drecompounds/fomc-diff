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
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

UA = "fomc-diff/0.1 (open data project; contact via GitHub issues)"


class NonTextContentError(RuntimeError):
    """Raised when fetch encounters non-text content that is not yet supported."""
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    from_cache: bool


def _cache_name(url: str) -> str:
    return Path(urlparse(url).path).name


def _get_fetched_at_from_cache(path: Path) -> str:
    """Get fetched_at from sidecar .meta.json, or fall back to file mtime."""
    meta_path = path.with_suffix(path.suffix + ".meta.json")

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta["fetched_at"]

    # Fall back to file mtime converted to UTC ISO
    mtime = path.stat().st_mtime
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def fetch(url: str, cache_dir: Path, *, session=None, sleep=time.sleep) -> FetchResult:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / _cache_name(url)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if path.exists():
        body = path.read_text(encoding="utf-8")
        fetched_at = _get_fetched_at_from_cache(path)
        return FetchResult(url, path,
                           hashlib.sha256(body.encode("utf-8")).hexdigest(),
                           fetched_at, True)

    if session is None:
        import requests
        session = requests.Session()

    sleep(1.0)  # 1 req/sec, applied before every real request
    resp = session.get(url, timeout=30, headers={"User-Agent": UA})
    resp.raise_for_status()

    # Check Content-Type header for binary content
    content_type = resp.headers.get("Content-Type", "")
    if content_type and not (content_type.startswith("text/") or "html" in content_type or "xml" in content_type):
        raise NonTextContentError(
            f"Binary fetching not supported yet; URL: {url}, Content-Type: {content_type}"
        )

    body = resp.text
    path.write_text(body, encoding="utf-8")

    # Write sidecar metadata with fetched_at timestamp
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    meta = {"url": url, "fetched_at": now}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    return FetchResult(url, path,
                       hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       now, False)
