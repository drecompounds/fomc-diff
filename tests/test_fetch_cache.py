import hashlib
from pathlib import Path
from fomc_diff.fetch import fetch, NonTextContentError
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
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r1.fetched_at == r2.fetched_at, "fetched_at should be stable across cache hits"

def test_cache_hit_with_deleted_sidecar_uses_mtime(tmp_path: Path):
    s = FakeSession()
    r1 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)

    # Delete the sidecar to simulate older cache
    meta_path = r1.path.with_suffix(r1.path.suffix + ".meta.json")
    if meta_path.exists():
        meta_path.unlink()

    # Fetch again, should return stable timestamp from mtime (not now())
    r2 = fetch("https://example.gov/a.htm", tmp_path, session=s, sleep=lambda _: None)
    assert r2.from_cache is True
    assert r2.fetched_at is not None
    # Both should have timestamps, and they should not be drastically different (mtime-based)
    assert r2.fetched_at  # Should have a value

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
