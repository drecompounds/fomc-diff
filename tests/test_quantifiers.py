from fomc_diff.quantifiers import count_quantifiers

def test_almost_all_does_not_also_count_as_all():
    """The substring trap. 'all participants' is inside 'almost all participants'."""
    c = count_quantifiers("Almost all participants agreed.")
    assert c.get(("participants", "almost all")) == 1
    assert c.get(("participants", "all,")) is None
    assert c.get(("participants", "all")) is None

def test_bare_all_still_counts():
    c = count_quantifiers("All participants agreed.")
    assert c.get(("participants", "all")) == 1
    assert c.get(("participants", "almost all")) is None

def test_members_and_participants_are_separate_populations():
    c = count_quantifiers("A few members dissented. A few participants agreed.")
    assert c.get(("members", "a few")) == 1
    assert c.get(("participants", "a few")) == 1

def test_case_insensitive_and_counted():
    c = count_quantifiers("Several participants noted. several participants added.")
    assert c.get(("participants", "several")) == 2

def test_unrelated_text_counts_nothing():
    assert count_quantifiers("The Committee met in Washington.") == {}
