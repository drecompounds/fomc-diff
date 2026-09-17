"""Fetch FOMC documents. The only module permitted to touch the network."""
from __future__ import annotations

import hashlib
import json
import os
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


class CacheCorruptionError(RuntimeError):
    """Raised when a cached file's bytes on disk don't match the sha256
    recorded in its sidecar.

    This is the check that would have caught an interrupted/torn write
    before a re-run's manifest rebuild certified the corrupted bytes as
    ground truth. Delete the named file (and its .meta.json sidecar) and
    re-fetch; do not attempt to patch the bytes in place.
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


def _read_sidecar(meta_path: Path, url: str) -> dict | None:
    """Read a cache entry's sidecar, or return None if it doesn't exist.

    Enforces that the sidecar's stored URL matches the URL being requested;
    see CacheCollisionError. This check applies whether or not the sidecar
    has a recorded hash, so a stale/mismatched sidecar is still loud even
    for a pre-verification cache entry.
    """
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cached_url = meta.get("url")
    if cached_url is not None and cached_url != url:
        raise CacheCollisionError(
            f"cache collision on {meta_path.name}: requested {url!r} but "
            f"the cached sidecar was written for {cached_url!r}"
        )
    return meta


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a temp sibling, then atomically replace path with it.

    os.replace() is atomic on both Windows and POSIX, so a crash mid-write
    leaves either the old file or the new one at `path`, never a torn mix of
    both -- that torn-write scenario is exactly what corrupted a cached
    document and let the manifest certify it as ground truth.
    """
    tmp_path = path.with_name(path.name + ".part")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    except BaseException:
        # A failure anywhere in this sequence (disk full, a mocked/injected
        # crash in tests, etc.) must not leave a stray .part file behind --
        # a later run globbing the cache dir must never find it.
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    tmp_path = path.with_name(path.name + ".part")
    try:
        tmp_path.write_text(text, encoding=encoding)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def fetch(url: str, cache_dir: Path, *, session=None, sleep=time.sleep) -> FetchResult:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / _cache_name(url)
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if path.exists():
        # Collision-check even a pre-verification sidecar (see _read_sidecar).
        meta = _read_sidecar(meta_path, url)
        expected_sha = meta.get("sha256") if meta else None

        if expected_sha:
            # Hash the BYTES on disk, never the decoded string: read_text
            # applies universal-newline translation, so a CRLF document
            # hashes differently every time and the manifest can never
            # match. Confirmed 2026-09-16.
            raw = path.read_bytes()
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                raise CacheCorruptionError(
                    f"cached file {path} failed hash verification: "
                    f"expected sha256 {expected_sha}, got {actual_sha}. "
                    "This file is corrupt on disk (e.g. an interrupted "
                    "write). Delete it and its .meta.json sidecar and "
                    "re-fetch; do not trust or re-hash it in place."
                )
            return FetchResult(url, path, actual_sha, meta["fetched_at"], True)

        # No sidecar, or a sidecar with no recorded hash: this entry predates
        # hash verification and cannot be trusted. Re-fetch it rather than
        # silently serving unverifiable bytes -- fall through to the normal
        # fetch path below, which will overwrite the file and write a fresh,
        # verifiable sidecar (self-healing).

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
    digest = hashlib.sha256(raw).hexdigest()

    # Write BYTES verbatim, and atomically: a bare write_bytes() (or the
    # write_text() this replaced, which also translates LF to CRLF on
    # Windows) can leave a torn file on disk if the process dies mid-write.
    # Writing to a temp sibling and os.replace()-ing it into place means a
    # crash leaves either the old file or the new one, never a mix of both.
    _atomic_write_bytes(path, raw)

    # Write the sidecar AFTER the body is in place, and atomically too, so a
    # sidecar never points at a body that isn't fully written. Recording the
    # hash here is what lets every future cache hit verify itself instead of
    # trusting whatever bytes happen to be on disk.
    meta = {
        "url": url,
        "fetched_at": now,
        "sha256": digest,
        "content_length": len(raw),
    }
    _atomic_write_text(meta_path, json.dumps(meta), encoding="utf-8")

    return FetchResult(url, path, digest, now, False)
