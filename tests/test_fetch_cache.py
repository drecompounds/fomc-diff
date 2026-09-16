import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from fomc_diff.fetch import fetch, NonTextContentError, CacheCollisionError
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

def test_cache_hit_with_deleted_sidecar_uses_mtime(tmp_path: Path):
    """With no sidecar, fetched_at must be derived from the cached file's
    mtime, not datetime.now(). Proven by setting the file's mtime to a
    fixed, clearly-old timestamp and asserting the returned value equals
    that exact mtime-derived ISO string."""
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    # Delete the sidecar to force the mtime fallback path.
    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    meta_path.unlink()

    fixed_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    fixed_epoch = fixed_dt.timestamp()
    os.utime(r1.path, (fixed_epoch, fixed_epoch))

    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is True
    expected = fixed_dt.isoformat(timespec="seconds")
    assert r2.fetched_at == expected, (
        "mtime-fallback path must derive fetched_at from the file's mtime, "
        "not datetime.now()"
    )

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
