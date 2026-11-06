"""Optic soccer (1st half) double_chance → rows keyed by covered outcomes."""

import pytest

from mappers.exchanges import optic
from mappers.exchanges.optic import OpticConfig
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE, double_chance_side
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES

_HOME, _AWAY = "ENG", "ESP"
_START = "2026-09-26T18:45:00Z"
_TEAM_MAP = {"T_ENG": _HOME, "T_ESP": _AWAY}
_CFG = OpticConfig(
    league_id="uefa_-_nations_league", table_types=dict(SOCCER_OPTIC_TABLE_TYPES))


def _odd(market_id: str, selection: str, *, team_id=None) -> optic.Odd:
    return optic.Odd(
        id=f"FIX1:{market_id}:{selection}",
        market_id=market_id,
        market=market_id,
        selection=selection,
        team_id=team_id,
        grouping_key="default",
    )


def _rows(*odds: optic.Odd, home_name="England", away_name="Spain"):
    fixture = optic.Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-09-26T14:45:00", start_date=_START,
        home=_HOME, away=_AWAY, home_name=home_name, away_name=away_name,
        team_map=_TEAM_MAP, odds=list(odds), is_live=False,
    )
    rows, odd_lookup, _ = optic.build_rows(
        _START, _HOME, _AWAY, fixture, _CFG, league="uefa_nations_league")
    return [r for r in rows if r.market_type.endswith("double_chance")], odd_lookup


def test_double_chance_is_a_soccer_optic_table_type():
    assert SOCCER_OPTIC_TABLE_TYPES["double_chance"] is MarketType.DOUBLE_CHANCE
    assert SOCCER_OPTIC_TABLE_TYPES["1st_half_double_chance"] is (
        MarketType.FIRST_HALF_DOUBLE_CHANCE)


def test_first_half_double_chance_keys_like_full_game():
    rows, _ = _rows(
        _odd("1st_half_double_chance", "England Or Draw"),
        _odd("double_chance", "England Or Draw"),
    )
    assert {(r.market_type, r.side) for r in rows} == {
        ("1h_double_chance", "ENG/_TIE"),
        ("double_chance", "ENG/_TIE"),
    }


def test_three_double_chance_odds_key_by_covered_outcomes():
    rows, odd_lookup = _rows(
        _odd("double_chance", "England Or Draw"),
        _odd("double_chance", "Spain Or Draw"),
        _odd("double_chance", "England Or Spain"),
    )
    selections = {}
    for r in rows:
        assert r.optic_id is not None
        selections[r.side] = odd_lookup[r.optic_id].selection
    assert selections == {
        "ENG/_TIE": "England Or Draw",
        "ESP/_TIE": "Spain Or Draw",
        "ENG/ESP": "England Or Spain",
    }
    assert all(r.entity is None and r.line is None for r in rows)


def test_outcome_order_and_case_do_not_matter():
    rows, _ = _rows(
        _odd("double_chance", "draw or england"),
        _odd("double_chance", "Spain or England"),
    )
    assert {r.side for r in rows} == {"ENG/_TIE", "ENG/ESP"}


def test_team_name_containing_or_still_parses():
    rows, _ = _rows(
        _odd("double_chance", "Win Or Bust FC Or Draw"),
        home_name="Win Or Bust FC",
    )
    assert [r.side for r in rows] == ["ENG/_TIE"]


def test_moneyline_selection_spelling_resolves_a_display_name_mismatch():
    rows, _ = _rows(
        _odd("moneyline", "Czechia", team_id="T_ENG"),
        _odd("double_chance", "Czechia Or Draw"),
        home_name="Czech Republic",
    )
    assert [r.side for r in rows] == ["ENG/_TIE"]


@pytest.mark.parametrize(
    "selection", ["Portugal Or Draw", "England Or England", "England", "Draw Or Tie"])
def test_unresolvable_double_chance_is_skipped(selection):
    rows, _ = _rows(_odd("double_chance", selection))
    assert rows == []


def test_double_chance_side_orders_home_away_tie():
    assert double_chance_side({TIE_SIDE, "LIV"}, "LIV", "CHE") == "LIV/_TIE"
    assert double_chance_side({"CHE", "LIV"}, "LIV", "CHE") == "LIV/CHE"
    with pytest.raises(ValueError):
        double_chance_side({"LIV"}, "LIV", "CHE")
    with pytest.raises(ValueError):
        double_chance_side({"LIV", "ARS"}, "LIV", "CHE")
