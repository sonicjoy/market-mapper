"""Tests for PX market classification — px.classify_market()."""

import pytest

from mappers.exchanges.px import classify_market
from mappers.market_types import MarketType
from mappers.vocab.basketball_markets import NBA_PX as _NBA_PX
from mappers.vocab.basketball_markets import NCAAB_PX as _NCAAB_PX
from mappers.vocab.basketball_markets import WNBA_PX as _WNBA_PX

# === Exact matches (game-level, fixed names) ===

@pytest.mark.parametrize("name, px_type, expected", [
    ("Moneyline",               "moneyline", MarketType.MONEYLINE),
    ("Spread",                  "spread",    MarketType.POINT_SPREAD),
    ("Total Points",            "total",     MarketType.GAME_TOTAL),
    ("First Half Moneyline",    "moneyline", MarketType.FIRST_HALF_MONEYLINE),
    ("First Half Spread",       "spread",    MarketType.FIRST_HALF_POINT_SPREAD),
    ("First Half Total Points", "total",     MarketType.FIRST_HALF_TOTAL),
])
def test_exact_matches(name, px_type, expected):
    assert classify_market(name, px_type, _NBA_PX).market_type == expected


# === Suffix matches (parameterized by team or player) ===

@pytest.mark.parametrize("name, px_type, expected", [
    # Team total
    ("CLE: Team Total Points",                  "total", MarketType.TEAM_TOTAL),
    ("GSW: Team Total Points",                  "total", MarketType.TEAM_TOTAL),
    # Player stat lines
    ("James Harden Points",                     "total", MarketType.PLAYER_POINTS),
    ("James Harden Assists",                    "total", MarketType.PLAYER_ASSISTS),
    ("James Harden Rebounds",                   "total", MarketType.PLAYER_REBOUNDS),
    ("James Harden Made Threes",                "total", MarketType.PLAYER_THREES),
    ("Tobias Harris Total Three Pointers Made", "total", MarketType.PLAYER_THREES),
    ("James Harden Total Blocks",               "total", MarketType.PLAYER_BLOCKS),
    ("James Harden Total Steals",               "total", MarketType.PLAYER_STEALS),
    # Legacy and new naming for the primary stat lines: PX flipped
    # NBA from "{Player} {Stat}" to "{Player} Total {Stat}" in
    # April 2026 (NCAAB had used the latter form for a long time).
    ("Paolo Banchero Points",                   "total", MarketType.PLAYER_POINTS),
    ("Paolo Banchero Total Points",             "total", MarketType.PLAYER_POINTS),
    ("Paolo Banchero Assists",                  "total", MarketType.PLAYER_ASSISTS),
    ("Paolo Banchero Total Assists",            "total", MarketType.PLAYER_ASSISTS),
    ("Paolo Banchero Rebounds",                 "total", MarketType.PLAYER_REBOUNDS),
    ("Paolo Banchero Total Rebounds",           "total", MarketType.PLAYER_REBOUNDS),
    # DD/TD (moneyline wire type — binary yes/no)
    ("James Harden To Record a Double Double",  "moneyline", MarketType.PLAYER_DOUBLE_DOUBLE),
    ("James Harden To Record a Triple Double",  "moneyline", MarketType.PLAYER_TRIPLE_DOUBLE),
    # DD/TD may also arrive as sup_moneyline (PX relabel; still YES_NO)
    ("James Harden To Record a Double Double",  "sup_moneyline", MarketType.PLAYER_DOUBLE_DOUBLE),
    ("James Harden To Record a Triple Double",  "sup_moneyline", MarketType.PLAYER_TRIPLE_DOUBLE),
    # Combos
    ("James Harden Total Points & Assists",              "total", MarketType.PLAYER_PTS_AST),
    ("James Harden Total Points & Rebounds",             "total", MarketType.PLAYER_PTS_REB),
    ("James Harden Total Points, Rebounds & Assists",    "total", MarketType.PLAYER_PTS_REB_AST),
    ("James Harden Total Rebounds & Assists",            "total", MarketType.PLAYER_REB_AST),
    # Steals+blocks and turnovers (currently ignored but classifiable)
    ("James Harden Total Steals & Blocks",               "total", MarketType.PLAYER_STEALS_BLOCKS),
    ("James Harden Total Turnovers",                     "total", MarketType.PLAYER_TURNOVERS),
])
def test_suffix_matches(name, px_type, expected):
    assert classify_market(name, px_type, _NBA_PX).market_type == expected


# === Longest-first ordering ===
#
# "Total Points & Assists" must match the combo suffix, not greedily
# match " Points" (which is a substring).

def test_longest_first_ordering():
    mt = classify_market("LeBron James Total Points & Assists", "total", _NBA_PX).market_type
    assert mt == MarketType.PLAYER_PTS_AST
    assert mt != MarketType.PLAYER_POINTS


# Combo suffixes containing "Total {Stat}" must win over the bare
# "Total {Stat}" single-stat suffixes added when PX flipped naming.
@pytest.mark.parametrize("name, expected", [
    ("LeBron James Total Points, Rebounds & Assists", MarketType.PLAYER_PTS_REB_AST),
    ("LeBron James Total Points & Rebounds",          MarketType.PLAYER_PTS_REB),
    ("LeBron James Total Rebounds & Assists",         MarketType.PLAYER_REB_AST),
])
def test_combo_suffixes_beat_total_singles(name, expected):
    assert classify_market(name, "total", _NBA_PX).market_type == expected


# ": Team Total Points" must win over " Total Points".
def test_team_total_beats_total_points():
    mt = classify_market("CLE: Team Total Points", "total", _NBA_PX).market_type
    assert mt == MarketType.TEAM_TOTAL
    assert mt != MarketType.PLAYER_POINTS


# === Error cases ===

def test_unrecognized_name_raises():
    with pytest.raises(ValueError, match="Unrecognized"):
        classify_market("Free Throws Made", "total", _NBA_PX)


def test_type_mismatch_raises():
    with pytest.raises(ValueError, match="expected"):
        classify_market("Moneyline", "spread", _NBA_PX)


# === NCAAB classification ===
#
# NCAAB uses the same "Total {Stat}" suffix family as NBA but with a
# different tournament_id (648).  Game-level exacts match NBA.  The
# combo, DD/TD, and defensive-stat suffixes must classify correctly
# without colliding with the single-stat suffixes that contain them
# (" Total Points" within " Total Points, Rebounds & Assists").

@pytest.mark.parametrize("name, px_type, expected", [
    # Single-stat lines
    ("Cooper Flagg Total Points",             "total", MarketType.PLAYER_POINTS),
    ("Cooper Flagg Total Rebounds",           "total", MarketType.PLAYER_REBOUNDS),
    ("Cooper Flagg Total Assists",            "total", MarketType.PLAYER_ASSISTS),
    ("Cooper Flagg Total Three Pointers Made", "total", MarketType.PLAYER_THREES),
    ("Cooper Flagg Total Blocks",             "total", MarketType.PLAYER_BLOCKS),
    ("Cooper Flagg Total Steals",             "total", MarketType.PLAYER_STEALS),
    ("Cooper Flagg Total Turnovers",          "total", MarketType.PLAYER_TURNOVERS),
    # Combos
    ("Cooper Flagg Total Points & Rebounds",  "total", MarketType.PLAYER_PTS_REB),
    ("Cooper Flagg Total Points & Assists",   "total", MarketType.PLAYER_PTS_AST),
    ("Cooper Flagg Total Rebounds & Assists", "total", MarketType.PLAYER_REB_AST),
    ("Cooper Flagg Total Points, Rebounds & Assists", "total", MarketType.PLAYER_PTS_REB_AST),
    ("Cooper Flagg Total Steals & Blocks",    "total", MarketType.PLAYER_STEALS_BLOCKS),
    # DD/TD (wire type is moneyline — binary yes/no)
    ("Cooper Flagg To Record a Double Double", "moneyline", MarketType.PLAYER_DOUBLE_DOUBLE),
    ("Cooper Flagg To Record a Triple Double", "moneyline", MarketType.PLAYER_TRIPLE_DOUBLE),
    # DD/TD may also arrive as sup_moneyline (PX relabel; still YES_NO)
    ("Cooper Flagg To Record a Double Double", "sup_moneyline", MarketType.PLAYER_DOUBLE_DOUBLE),
    ("Cooper Flagg To Record a Triple Double", "sup_moneyline", MarketType.PLAYER_TRIPLE_DOUBLE),
    # Team total (colon prefix)
    ("DUKE: Team Total Points",               "total", MarketType.TEAM_TOTAL),
])
def test_ncaab_suffix_matches(name, px_type, expected):
    assert classify_market(name, px_type, _NCAAB_PX).market_type == expected


# Longest-first ordering matters: the combo " Total Points, Rebounds &
# Assists" must win over " Total Points" (which is a substring of it).
@pytest.mark.parametrize("name, expected", [
    ("Cooper Flagg Total Points, Rebounds & Assists", MarketType.PLAYER_PTS_REB_AST),
    ("Cooper Flagg Total Points & Rebounds",          MarketType.PLAYER_PTS_REB),
    ("Cooper Flagg Total Rebounds & Assists",         MarketType.PLAYER_REB_AST),
    ("Cooper Flagg Total Points & Assists",           MarketType.PLAYER_PTS_AST),
])
def test_ncaab_combo_suffixes_beat_singles(name, expected):
    assert classify_market(name, "total", _NCAAB_PX).market_type == expected


# === WNBA: DD as sup_moneyline (pipeline failure 2026-07-28) ===

def test_wnba_double_double_sup_moneyline():
    mt = classify_market(
        "Napheesa Collier To Record a Double Double",
        "sup_moneyline",
        _WNBA_PX,
    ).market_type
    assert mt == MarketType.PLAYER_DOUBLE_DOUBLE
