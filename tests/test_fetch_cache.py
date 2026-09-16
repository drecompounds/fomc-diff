import hashlib
from pathlib import Path
from fomc_diff.fetch import fetch

HTML = "<html><body><p>hello</p></body></html>"

class FakeResponse:
    status_code = 200
    text = HTML
    content = HTML.encode("utf-8")
    def raise_for_status(self): pass

class FakeSession:
    def __init__(self): self.calls = 0
    def get(self, url, timeout=30, headers=None):
        self.calls += 1
        return FakeResponse()

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
