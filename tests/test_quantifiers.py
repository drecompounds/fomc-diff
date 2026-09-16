import re
from fomc_diff.quantifiers import count_quantifiers, _build_pattern, QUANTIFIERS

def test_almost_all_does_not_also_count_as_all():
    """Word boundaries prevent the spurious bare 'all' match."""
    c = count_quantifiers("Almost all participants agreed.")
    assert c.get(("participants", "almost all")) == 1
    assert c.get(("participants", "all")) is None

def test_removing_almost_all_creates_spurious_match():
    """Disable-proof: the 'almost all' entry must exist or 'all' silently matches."""
    stripped = tuple(q for q in QUANTIFIERS if q != "almost all")
    pattern = _build_pattern(stripped)
    text = "Almost all participants agreed."
    matches = []
    for m in pattern.finditer(text):
        quant = re.sub(r"\s+", " ", m.group(1).lower())
        population = m.group(2).lower()
        matches.append((population, quant))
    # Without "almost all" in the tuple, the pattern matches bare "all" at offset 7
    assert ("participants", "all") in matches, (
        "Removing 'almost all' from QUANTIFIERS allows bare 'all' to match spuriously"
    )
    # But the real count_quantifiers must not produce this with the full tuple
    c = count_quantifiers("Almost all participants agreed.")
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
