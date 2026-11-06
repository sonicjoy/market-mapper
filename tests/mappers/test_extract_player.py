"""Tests for PX player-name extraction — px.extract_player().

extract_player is a trivial suffix-strip; its real contract is that
classify_market picked the suffix for the same name.  Tests here
exercise that pairing end-to-end plus a couple of isolation-level
cases.
"""

import pytest

from mappers.exchanges.px import classify_market, extract_player
from mappers.vocab.basketball_markets import NBA_PX as _NBA_PX

# === classify→extract pairing ===
#
# The regression this guards: " Points" and " Total Points" both
# endswith-match "Paolo Banchero Total Points".  classify_market must
# pick the longer one so extract_player strips to "Paolo Banchero"
# (not "Paolo Banchero Total").  Covers single-suffix types, combos,
# and multi-suffix types (PLAYER_THREES has both " Made Threes" and
# " Total Three Pointers Made" — PX flip-flopped in April 2026).
# Primary stat lines (Points / Assists / Rebounds) got the same
# treatment when PX moved NBA to the NCAAB-style "Total {Stat}" form.

@pytest.mark.parametrize("name, expected", [
    # Single-suffix types
    ("James Harden Assists",                    "James Harden"),
    ("James Harden Rebounds",                   "James Harden"),
    ("James Harden Points",                     "James Harden"),
    ("James Harden Total Blocks",               "James Harden"),
    ("James Harden Total Points & Assists",     "James Harden"),
    # Threes: both historical namings
    ("James Harden Made Threes",                "James Harden"),
    ("Tobias Harris Total Three Pointers Made", "Tobias Harris"),
    # Primary stat lines: both historical namings
    ("Paolo Banchero Points",                   "Paolo Banchero"),
    ("Paolo Banchero Total Points",             "Paolo Banchero"),
    ("Paolo Banchero Assists",                  "Paolo Banchero"),
    ("Paolo Banchero Total Assists",            "Paolo Banchero"),
    ("Paolo Banchero Rebounds",                 "Paolo Banchero"),
    ("Paolo Banchero Total Rebounds",           "Paolo Banchero"),
])
def test_classify_then_extract_yields_player(name, expected):
    match = classify_market(name, "total", _NBA_PX)
    assert match.suffix is not None
    assert extract_player(name, match.suffix) == expected


# === extract_player in isolation ===
#
# Strip whatever suffix is handed in; no cfg consultation.

def test_extract_player_strips_given_suffix():
    assert extract_player("James Harden Total Blocks", " Total Blocks") == "James Harden"


# Defensive assertion for a programming error: caller paired the
# wrong suffix with the wrong name.  Should never fire in production.

def test_extract_player_asserts_suffix_matches_name():
    with pytest.raises(AssertionError, match="doesn't end with matched suffix"):
        extract_player("James Harden Points", " Assists")
