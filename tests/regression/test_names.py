"""Independent name matcher: the verdict that fails a gate is 'swapped'."""

from regression.names import fits, side_verdict, tokens


def test_tokens_fold_accents_and_drop_venue_noise():
    assert tokens("Enzo Fernández to win") == ["enzo", "fernandez"]
    assert tokens("Yes - Court McGee") == ["court", "mcgee"]
    assert tokens(None) == []


def test_fits_subset_and_surname():
    assert fits("Court McGee to win", "Court McGee")
    assert fits("McGee", "Court McGee")
    assert fits("C. McGee", "Court McGee")  # shared surname
    assert not fits("Eric Nolan", "Court McGee")
    assert not fits("", "Court McGee")


def test_short_last_token_is_not_a_surname_match():
    # "Jr" / an initial must not tie two different people together
    assert not fits("Ab Cd", "Xy Cd")


def test_side_verdicts():
    assert side_verdict("Court McGee to win", "Court McGee", "Eric Nolan") == "agrees"
    # the 2026-09-29 incident: McGee's contract mapped onto Nolan
    assert side_verdict("Court McGee to win", "Eric Nolan", "Court McGee") == "swapped"
    assert side_verdict("Home", "Court McGee", "Eric Nolan") == "unclear"
    # same surname on both sides (siblings) is no evidence either way
    assert side_verdict("Silva", "Natalia Silva", "Bruna Silva") == "unclear"
