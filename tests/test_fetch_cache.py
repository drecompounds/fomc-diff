import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from fomc_diff.fetch import (
    fetch,
    NonTextContentError,
    CacheCollisionError,
    CacheCorruptionError,
)
import pytest

HTML = "<html><body><p>hello</p></body></html>"

class FakeResponse:
    status_code = 200
    text = HTML
    content = HTML.encode("utf-8")
    headers = {"Content-Type": "text/html; charset=utf-8"}
    def raise_for_status(self): pass

class FakeSession:
    def __init__(self, response=None):
        self.calls = 0
        self.response = response or FakeResponse()
    def get(self, url, timeout=30, headers=None):
        self.calls += 1
        return self.response

def test_fetch_writes_file_and_sha(tmp_path: Path):
    s = FakeSession()
    r = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r.from_cache is False
    assert r.path.exists()
    assert r.sha256 == hashlib.sha256(HTML.encode("utf-8")).hexdigest()
    assert s.calls == 1

def test_second_fetch_uses_cache_and_makes_no_request(tmp_path: Path):
    s = FakeSession()
    fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is True
    assert s.calls == 1, "cache hit must not issue a second request"

def test_fetching_twice_returns_same_fetched_at(tmp_path: Path):
    """A cache hit must read fetched_at from the sidecar, not call
    datetime.now(). Proven by forcing the sidecar to a fixed, clearly-old
    timestamp that datetime.now() could never coincidentally produce, then
    asserting the returned value matches it exactly."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    fixed = "2020-01-01T00:00:00+00:00"
    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fetched_at"] = fixed
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.fetched_at == fixed, (
        "cache hit must return the sidecar's fetched_at verbatim, not datetime.now()"
    )

def test_cache_hit_with_deleted_sidecar_is_refetched_not_trusted(tmp_path: Path):
    """Formerly: with no sidecar, fetched_at fell back to the cached file's
    mtime and the (unverifiable) cached bytes were served as-is. That mtime
    fallback is exactly what let a torn write get served silently -- there
    was no sidecar hash to catch it.

    New contract (see CacheCorruptionError and rule 4 in the fix): a cache
    entry with no sidecar cannot be verified, so it is no longer trusted.
    fetch() re-fetches it instead, still never recomputing fetched_at for an
    actually-verified hit (see test_fetched_at_still_comes_from_the_sidecar_
    on_a_verified_hit) -- but this is not a verified hit, it's a fresh fetch,
    so from_cache is False and fetched_at legitimately comes from now()."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    # Delete the sidecar: this entry predates hash recording and can no
    # longer be verified.
    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta_path.unlink()

    fixed_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    fixed_epoch = fixed_dt.timestamp()
    os.utime(r1.path, (fixed_epoch, fixed_epoch))

    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is False, (
        "a sidecar-less cache entry must be re-fetched, not silently served"
    )
    assert s.calls == 2, "the missing sidecar must trigger a real re-fetch"
    assert r2.fetched_at != fixed_dt.isoformat(timespec="seconds"), (
        "fetched_at must not come from the old file's mtime any more"
    )
    # And the re-fetch must have healed the cache: a sidecar with a sha256
    # now exists, so the next hit is a verified one.
    new_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert new_meta.get("sha256"), "re-fetch must write a sidecar with a recorded hash"

def test_cache_collision_raises_on_url_mismatch(tmp_path: Path):
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["url"] = "https://other.gov/a.htm"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(CacheCollisionError) as exc_info:
        fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert "https://example.gov/a.htm" in str(exc_info.value)
    assert "https://other.gov/a.htm" in str(exc_info.value)

def test_pdf_content_type_raises_error(tmp_path: Path):
    class PdfResponse:
        status_code = 200
        text = ""
        content = b""
        headers = {"Content-Type": "application/pdf"}
        def raise_for_status(self): pass

    s = FakeSession(response=PdfResponse())
    with pytest.raises(NonTextContentError) as exc_info:
        fetch("https://example.gov/doc.pdf", tmp_path, session=s, sleep=lambda _: None)

    assert "Binary fetching not supported yet" in str(exc_info.value)
    assert "application/pdf" in str(exc_info.value)
    # Verify no file was written
    cache_file = tmp_path / "doc.pdf"
    assert not cache_file.exists()

def test_missing_content_type_raises_error(tmp_path: Path):
    """An absent Content-Type header must be treated as unknown (rejected),
    not trusted as text."""
    class NoContentTypeResponse:
        status_code = 200
        text = HTML
        content = HTML.encode("utf-8")
        headers = {}
        def raise_for_status(self): pass

    s = FakeSession(response=NoContentTypeResponse())
    with pytest.raises(NonTextContentError):
        fetch("https://example.gov/b.htm", tmp_path, session=s, sleep=lambda _: None)
    assert not (tmp_path / "b.htm").exists()


# --- provenance regression found on the live 2026-09-16 fetch ---------------

def test_sha_is_stable_across_fetch_and_cache_reread(tmp_path):
    """A fresh fetch and a cache hit must report the SAME sha for one document.

    write_text() on Windows translates LF to CRLF, so a body served with CRLF
    came back as CR CR LF on disk and the decoded re-read hashed differently
    from the fetch. The manifest then mismatches on every document forever,
    which destroys its only job: detecting a silently edited Fed page.
    """
    crlf = "<html>\r\n<body>\r\n<p>hi</p>\r\n</body>\r\n</html>"

    class R:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        text = crlf
        content = crlf.encode("utf-8")
        def raise_for_status(self): pass

    class S:
        def get(self, url, timeout=30, headers=None): return R()

    first = fetch("https://example.gov/x.htm", tmp_path, session=S(), sleep=lambda _: None)
    second = fetch("https://example.gov/x.htm", tmp_path, session=S(), sleep=lambda _: None)
    assert second.from_cache is True
    assert first.sha256 == second.sha256, "sha must not change between fetch and cache re-read"


def test_cached_bytes_are_byte_identical_to_what_was_served(tmp_path):
    crlf = "<html>\r\n<p>hi</p>\r\n</html>"

    class R:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        text = crlf
        content = crlf.encode("utf-8")
        def raise_for_status(self): pass

    class S:
        def get(self, url, timeout=30, headers=None): return R()

    r = fetch("https://example.gov/y.htm", tmp_path, session=S(), sleep=lambda _: None)
    assert r.path.read_bytes() == crlf.encode("utf-8"), "cached file must be byte-faithful to the server body"


# --- cache integrity: atomic writes + hash verification on every hit -------

def test_a_corrupted_cache_entry_is_detected_rather_than_served(tmp_path):
    """A torn write corrupted one cached document and manifest.csv recorded the
    damaged bytes as ground truth, because a re-run rebuilds the manifest from
    whatever is on disk. Serving an unverified cache entry is how a silent
    wrong answer reached the published dataset."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    # Simulate a torn write: corrupt the bytes on disk after the sidecar
    # (with its correct sha256) has already been written.
    r1.path.write_bytes(b"<html><body><p>MOJIBAKE</p></body></html>")

    with pytest.raises(CacheCorruptionError) as exc_info:
        fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    msg = str(exc_info.value)
    assert str(r1.path) in msg or r1.path.name in msg
    assert r1.sha256 in msg, "expected hash must be named"
    corrupted_hash = hashlib.sha256(r1.path.read_bytes()).hexdigest()
    assert corrupted_hash in msg, "actual (corrupted) hash must be named"


def test_a_cache_entry_without_a_recorded_hash_is_refetched_not_trusted(tmp_path):
    """Entries written before hashes were recorded cannot be verified."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta_path.unlink()

    new_html = "<html><body><p>DIFFERENT</p></body></html>"

    class NewResponse:
        status_code = 200
        text = new_html
        content = new_html.encode("utf-8")
        headers = {"Content-Type": "text/html; charset=utf-8"}
        def raise_for_status(self): pass

    s2 = FakeSession(response=NewResponse())
    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s2, sleep=lambda _: None)

    assert r2.from_cache is False
    assert r2.sha256 == hashlib.sha256(new_html.encode("utf-8")).hexdigest(), (
        "the new bytes must win over the untrusted, unverifiable old cache entry"
    )
    assert r1.path.read_bytes() == new_html.encode("utf-8")


def test_fetched_at_still_comes_from_the_sidecar_on_a_verified_hit(tmp_path):
    """Provenance must not be recomputed as now() on a cache hit -- the
    original reason the sidecar exists."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    fixed = "2020-01-01T00:00:00+00:00"
    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fetched_at"] = fixed
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is True
    assert r2.fetched_at == fixed, (
        "a verified cache hit must return the sidecar's fetched_at verbatim"
    )


def test_an_interrupted_write_leaves_no_partial_file_in_the_cache(tmp_path):
    """Make the session raise midway / simulate failure after the body write
    begins, and assert no .part file and no half-written cache entry remains
    that a later run would serve."""
    from fomc_diff import fetch as fetch_mod

    real_replace = os.replace
    call_count = {"n": 0}

    def flaky_replace(src, dst):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulate a crash between the temp write and the atomic
            # replace of the body file -- the .part file must be left
            # behind, never the real cache path.
            raise OSError("simulated crash during atomic replace")
        return real_replace(src, dst)

    s = FakeSession()
    import unittest.mock as mock
    with mock.patch.object(fetch_mod.os, "replace", side_effect=flaky_replace):
        with pytest.raises(OSError):
            fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    cache_path = tmp_path / "a.htm"
    assert not cache_path.exists(), "a failed replace must not leave a half-written cache entry"
    leftover_parts = list(tmp_path.glob("*.part"))
    assert leftover_parts == [], f"a .part file was left behind: {leftover_parts}"
