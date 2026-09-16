from datetime import date
from fomc_diff.parse import Paragraph
from fomc_diff.phrases import phrase_index

def _p(text): return [Paragraph(0, "economy", text, "x")]

BY_DATE = {
    date(2026, 3, 18): _p("Economic activity is expanding at a moderate pace."),
    date(2026, 6, 17): _p("Economic activity is expanding at a solid pace."),
    date(2026, 7, 29): _p("Economic activity is expanding at a solid pace."),
}

def test_tracks_first_and_last_seen():
    rows = {r.phrase: r for r in phrase_index(BY_DATE, ["solid pace", "moderate pace"])}
    assert rows["solid pace"].first_seen == "2026-06-17"
    assert rows["solid pace"].last_seen == "2026-07-29"
    assert rows["solid pace"].n_meetings == 2
    assert rows["moderate pace"].first_seen == "2026-03-18"
    assert rows["moderate pace"].n_meetings == 1

def test_absent_phrase_is_omitted_not_zero_filled():
    rows = {r.phrase: r for r in phrase_index(BY_DATE, ["bowling night"])}
    assert rows == {}

def test_dates_are_sorted_regardless_of_dict_order():
    shuffled = {k: BY_DATE[k] for k in sorted(BY_DATE, reverse=True)}
    rows = {r.phrase: r for r in phrase_index(shuffled, ["solid pace"])}
    assert rows["solid pace"].first_seen == "2026-06-17"
    assert rows["solid pace"].last_seen == "2026-07-29"
