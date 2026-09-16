"""Fetch FOMC documents. The only module permitted to touch the network."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE = "https://www.federalreserve.gov"
UA = "fomc-diff/0.1 (open data project; contact via GitHub issues)"


class NonTextContentError(RuntimeError):
    """Raised when fetch encounters non-text content that is not yet supported."""
    pass


class CacheCollisionError(RuntimeError):
    """Raised when a cached sidecar's stored URL doesn't match the URL
    being requested.

    The cache key (see _cache_name) is derived from the URL basename only,
    discarding host and path, so two different URLs that share a basename
    would otherwise silently serve the wrong cached document. This turns
    that failure mode loud.
    """
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    from_cache: bool


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d")


def statement_url(d: date) -> str:
    return f"{BASE}/newsevents/pressreleases/monetary{_stamp(d)}a.htm"


def minutes_url(d: date) -> str:
    return f"{BASE}/monetarypolicy/fomcminutes{_stamp(d)}.htm"


def minutes_pdf_url(d: date) -> str:
    """Build the PDF-fallback minutes URL.

    Note: PDF fetching is not yet supported by fetch() — a response whose
    Content-Type is not text/html/xml (as a PDF's is not) is rejected with
    NonTextContentError. This builds the URL only; do not assume fetch()
    can retrieve it yet.
    """
    return f"{BASE}/monetarypolicy/files/fomcminutes{_stamp(d)}.pdf"


def _cache_name(url: str) -> str:
    return Path(urlparse(url).path).name


def _get_fetched_at_from_cache(path: Path, url: str) -> str:
    """Get fetched_at from sidecar .meta.json, or fall back to file mtime.

    Also enforces that the sidecar's stored URL matches the URL being
    requested; see CacheCollisionError.
    """
    meta_path = path.with_suffix(path.suffix + ".meta.json")

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cached_url = meta.get("url")
        if cached_url is not None and cached_url != url:
            raise CacheCollisionError(
                f"cache collision on {path.name}: requested {url!r} but "
                f"the cached sidecar was written for {cached_url!r}"
            )
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
        # Hash the BYTES on disk, never the decoded string: read_text applies
        # universal-newline translation, so a CRLF document hashes differently
        # every time and the manifest can never match. Confirmed 2026-09-16.
        raw = path.read_bytes()
        fetched_at = _get_fetched_at_from_cache(path, url)
        return FetchResult(url, path,
                           hashlib.sha256(raw).hexdigest(),
                           fetched_at, True)

    if session is None:
        import requests
        session = requests.Session()

    sleep(1.0)  # 1 req/sec, applied before every real request
    resp = session.get(url, timeout=30, headers={"User-Agent": UA})
    resp.raise_for_status()

    # Check Content-Type header for binary content. An absent or empty
    # Content-Type is UNKNOWN, not text — it must be rejected too, or
    # binary content with no header flows through resp.text and lands in
    # the cache as mojibake.
    content_type = resp.headers.get("Content-Type", "")
    if not content_type or not (
        content_type.startswith("text/") or "html" in content_type or "xml" in content_type
    ):
        raise NonTextContentError(
            f"Binary fetching not supported yet; URL: {url}, Content-Type: {content_type!r}"
        )

    raw = resp.content
    # Write BYTES verbatim. write_text() translates LF to CRLF on Windows,
    # which turned a CRLF body into CR CR LF and corrupted the cached copy
    # relative to what the Fed actually served.
    path.write_bytes(raw)

    # Write sidecar metadata with fetched_at timestamp
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    meta = {"url": url, "fetched_at": now}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    return FetchResult(url, path,
                       hashlib.sha256(raw).hexdigest(),
                       now, False)
