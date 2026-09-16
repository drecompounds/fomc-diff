from datetime import date
from pathlib import Path

import pytest

from fomc_diff.discover import DiscoveryError, statement_links, build_corpus, listing_urls

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


# Task 1 tests

def test_january_2016_resolves_to_the_statement_not_the_longer_run_goals():
    """monetary20160127b.htm is the Statement on Longer-Run Goals, published the
    same day. Choosing by URL suffix would be a coin flip; choosing by label is
    not. This is the wrong-document guard."""
    links = statement_links(_html("listing_fomchistorical2016.html"))
    url = links[date(2016, 1, 27)]
    assert url.endswith("monetary20160127a.htm")
    assert "20160127b" not in url


def test_historical_page_yields_eight_statements_for_2016():
    links = statement_links(_html("listing_fomchistorical2016.html"))
    assert len([d for d in links if d.year == 2016]) == 8


def test_current_calendar_uses_the_html_label():
    """The historical pages label statement links 'Statement'; the current
    calendar labels the same thing 'HTML'. Accepting only one silently empties
    half the corpus."""
    links = statement_links(_html("listing_fomccalendars.html"))
    assert date(2026, 9, 16) in links
    assert links[date(2026, 9, 16)].endswith("monetary20260916a.htm")


def test_unknown_label_raises_rather_than_guessing():
    """A ninth Fed document type must be a red test, not a silent inclusion or
    a silent omission."""
    html = ('<a href="/newsevents/pressreleases/monetary20260101a.htm">'
            'Some New Document Type</a>')
    with pytest.raises(DiscoveryError, match="unrecognised label"):
        statement_links(html)


def test_known_non_statement_labels_are_dropped_silently():
    html = ('<a href="/newsevents/pressreleases/monetary20260101b.htm">'
            'Statement on Longer-Run Goals and Monetary Policy Strategy</a>')
    assert statement_links(html) == {}


def test_urls_are_absolute():
    links = statement_links(_html("listing_fomchistorical2016.html"))
    assert all(u.startswith("https://www.federalreserve.gov/") for u in links.values())


# Task 2 tests

def test_build_corpus_merges_both_page_shapes():
    pages = {
        "hist2016": _html("listing_fomchistorical2016.html"),
        "calendars": _html("listing_fomccalendars.html"),
    }
    corpus = build_corpus(pages, current_year=2026)
    assert len([d for d in corpus if d.year == 2016]) == 8
    assert len([d for d in corpus if d.year == 2026]) == 6


def test_a_complete_year_short_of_eight_statements_raises():
    """Eight scheduled meetings a year is a fact about the FOMC. A listing-page
    layout change that silently halved the corpus would otherwise be invisible
    until someone noticed the dataset was thin."""
    pages = {"only_one": '<a href="/newsevents/pressreleases/monetary20200101a.htm">Statement</a>'}
    with pytest.raises(DiscoveryError, match="2020"):
        build_corpus(pages, current_year=2026)


def test_the_in_progress_year_is_exempt_from_the_count_guard():
    """2026 has six statements so far and must not raise for it."""
    pages = {"only_one": '<a href="/newsevents/pressreleases/monetary20260101a.htm">Statement</a>'}
    assert len(build_corpus(pages, current_year=2026)) == 1


def test_listing_urls_covers_the_whole_span():
    urls = listing_urls(through_year=2026)
    assert any("fomchistorical2016.htm" in u for u in urls)
    assert any("fomchistorical2020.htm" in u for u in urls)
    assert any("fomccalendars.htm" in u for u in urls)
    assert not any("fomchistorical2021.htm" in u for u in urls)
