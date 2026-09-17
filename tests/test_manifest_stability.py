"""The manifest's hash must survive a refetch, or it cannot do its only job."""
from pathlib import Path

from fomc_diff.backfill import _content_hash

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_content_hash_ignores_the_noise_the_fed_changes_every_response():
    """federalreserve.gov is NOT byte-stable. Cloudflare injects a randomised
    email-protection token and a per-response script, so two fetches a second
    apart produce different bytes and a different raw sha256 -- verified live
    against both a 2016 and a 2026 statement.

    A manifest keyed on raw bytes therefore mismatches on every refetch and
    can never distinguish a real edit from that noise, which is the only
    thing it exists to detect. This test injects exactly that noise and
    requires the recorded hash to be unmoved.
    """
    html = _html("statement_20260916.html")
    noisy = html.replace(
        "</body>",
        '<script>var t="cf-token-9f2b41e0";</script>'
        '<a href="/cdn-cgi/l/email-protection#1c237e737865">x</a></body>',
    )
    assert noisy != html, "the noise was not injected; this test would be vacuous"
    assert _content_hash(noisy) == _content_hash(html)


def test_content_hash_changes_when_the_statement_actually_changes():
    """The other half: a hash that never changes detects nothing. One word of
    the policy paragraph must move it."""
    html = _html("statement_20260916.html")
    edited = html.replace("decided to raise", "decided to lower")
    assert edited != html, "the edit was not applied; this test would be vacuous"
    assert _content_hash(edited) != _content_hash(html)


def test_content_hash_covers_the_role_not_only_the_text():
    """A paragraph keeping its wording but changing role is a real change in
    the dataset, so it must move the hash."""
    a = _content_hash(_html("statement_20260729.html"))
    b = _content_hash(_html("statement_20260617.html"))
    assert a != b
