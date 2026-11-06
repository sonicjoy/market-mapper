"""Tennis games handicap + per-player games won, both sides of the merge.

Optic prices two tennis contracts that the tennis Optic crosswalk did not
list, so no canonical row for either ever existed:

  * ``game_spread`` -- the GAMES handicap, i.e. tennis's POINT_SPREAD, the
    same contract Kalshi posts as GSPREAD and Novig as SPREAD.  Without an
    Optic row the Kalshi/Novig rows stood alone with ``optic_odds: null``
    and ``BigQuery/load_mappings.py`` dropped them (it skips any record with
    no Optic block), so 198 stamped Novig game-handicap outcomes went
    nowhere on 2026-08-26.
  * ``player_games_won`` -- games won by ONE named player.  Optic ships
    ``player_id`` on it and Novig ships ``PLAYER_GAMES_WON`` with
    ``player.opticOddsId``, so the entity is the usual id join.

The tests that matter are the merge-key ones: a Novig row and its Optic
twin must produce the SAME ``row_key``, because that identity is the only
thing standing between ``attach_novig_row`` stamping and dropping.
"""

import json

from mappers.exchanges.novig import build_rows as novig_build_rows
from mappers.exchanges.novig import parse_market
from mappers.exchanges.optic import Fixture, Odd, OpticConfig
from mappers.exchanges.optic import build_rows as optic_build_rows
from mappers.market_types import MarketType, Scope, Shape
from mappers.pipeline import row_key
from mappers.vocab import novig_markets
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES

START = "2026-08-26T15:00:00Z"
HOME, AWAY = "OLI", "BAR"
HOME_OPTIC, AWAY_OPTIC = "528FD6FB9154", "5921FFD9E921"
TEAM_MAP = {HOME_OPTIC: HOME, AWAY_OPTIC: AWAY}
# In tennis the competitor IS the player, so Optic's team_id and player_id
# are the same id on a player prop (verified on fixture 24382-97053,
# 2026-08-26).
PLAYER_NAMES = {HOME_OPTIC: "genaro_alberto_olivieri"}

TENNIS_OPTIC = OpticConfig(league_id="atp",
                           table_types=dict(TENNIS_OPTIC_TABLE_TYPES))


def _fixture(odds: list[Odd]) -> Fixture:
    return Fixture(
        fixture_id="20260826D5EF4342", game_id="24382-97053-2026-34",
        sportradar_id=None, start_et="2026-08-26T11:00:00", start_date=START,
        home=HOME, away=AWAY, home_name="Olivieri", away_name="Barrios Vera",
        team_map=dict(TEAM_MAP), odds=odds, is_live=False,
    )


def _optic_rows(odds: list[Odd]):
    rows, _, _ = optic_build_rows(
        START, HOME, AWAY, _fixture(odds), TENNIS_OPTIC, league="atp")
    return rows


def _novig_market(mtype, *, strike, outcomes, player=None, competitor=None):
    return parse_market(json.dumps({
        "id": "m1", "type": mtype, "description": f"{mtype} desc",
        "status": "OPEN", "strike": strike, "league": "ATP",
        "eventId": "e1", "playerId": (player or {}).get("id"),
        "player": player, "competitor": competitor,
        "outcomeIds": [o["id"] for o in outcomes], "outcomes": outcomes,
    }))


def _novig_rows(market, mt):
    return novig_build_rows(
        market, mt, home=HOME, away=AWAY, start_date=START, league="atp",
        team_map=dict(TEAM_MAP), player_names=dict(PLAYER_NAMES))


# === crosswalk registration ===

def test_optic_crosswalk_lists_both_tennis_contracts():
    assert TENNIS_OPTIC_TABLE_TYPES["game_spread"] == MarketType.POINT_SPREAD
    assert (TENNIS_OPTIC_TABLE_TYPES["player_games_won"]
            == MarketType.PLAYER_GAMES_WON)
    # The set-scoped siblings settle differently and stay unmapped.
    assert "1st_set_game_spread" not in TENNIS_OPTIC_TABLE_TYPES
    assert "1st_set_player_games_won" not in TENNIS_OPTIC_TABLE_TYPES


def test_novig_crosswalk_maps_player_games_won_and_ignores_nothing():
    assert (novig_markets.TENNIS["PLAYER_GAMES_WON"]
            == MarketType.PLAYER_GAMES_WON)
    assert "PLAYER_GAMES_WON" not in novig_markets.TENNIS_IGNORED


def test_player_games_won_is_a_player_over_under():
    mt = MarketType.PLAYER_GAMES_WON
    assert mt.scope == Scope.PLAYER
    assert mt.shape == Shape.OVER_UNDER


# === optic side ===

def test_optic_game_spread_is_a_signed_team_spread():
    """selection_line is null and points carries the sign, exactly like
    set_handicap -- side comes from team_id, never the selection string."""
    odds = [
        Odd(id="o1", market_id="game_spread", selection="Tomas Barrios Vera",
            selection_line=None, points=-4.5, team_id=AWAY_OPTIC,
            player_id=None, grouping_key="default:4.5"),
        Odd(id="o2", market_id="game_spread",
            selection="Genaro Alberto Olivieri", selection_line=None,
            points=4.5, team_id=HOME_OPTIC, player_id=None,
            grouping_key="default:4.5"),
    ]
    rows = _optic_rows(odds)
    assert {r.market_type for r in rows} == {"point_spread"}
    assert {(r.side, r.line) for r in rows} == {(AWAY, -4.5), (HOME, 4.5)}
    assert {r.entity for r in rows} == {None}


def test_optic_player_games_won_keys_off_the_player_name():
    odds = [
        Odd(id="o1", market_id="player_games_won",
            selection="Genaro Alberto Olivieri", selection_line="under",
            points=9.5, team_id=HOME_OPTIC, player_id=HOME_OPTIC,
            grouping_key="genaro_alberto_olivieri:9.5"),
        Odd(id="o2", market_id="player_games_won",
            selection="Genaro Alberto Olivieri", selection_line="over",
            points=9.5, team_id=HOME_OPTIC, player_id=HOME_OPTIC,
            grouping_key="genaro_alberto_olivieri:9.5"),
    ]
    rows = _optic_rows(odds)
    assert {r.market_type for r in rows} == {"player_games_won"}
    assert {r.entity for r in rows} == {"genaro_alberto_olivieri"}
    assert {(r.side, r.line) for r in rows} == {("over", 9.5), ("under", 9.5)}


# === novig side ===

def test_novig_player_games_won_entity_comes_from_the_optic_player_id():
    market = _novig_market(
        "PLAYER_GAMES_WON", strike=9.5,
        player={"id": "p1", "name": "Genaro Alberto Olivieri",
                "fullName": "Genaro Alberto Olivieri",
                "opticOddsId": HOME_OPTIC},
        outcomes=[
            {"id": "o-under", "description": "Under 9.5", "type": "Under",
             "index": 1},
            {"id": "o-over", "description": "Over 9.5", "type": "Over",
             "index": 0},
        ])
    rows = _novig_rows(market, MarketType.PLAYER_GAMES_WON)
    assert {r.entity for r in rows} == {"genaro_alberto_olivieri"}
    assert {(r.side, r.line) for r in rows} == {("over", 9.5), ("under", 9.5)}


def test_novig_player_games_won_dropped_when_optic_never_priced_the_player():
    market = _novig_market(
        "PLAYER_GAMES_WON", strike=9.5,
        player={"id": "p9", "name": "Nobody", "fullName": "Nobody",
                "opticOddsId": "UNKNOWN-PLAYER"},
        outcomes=[
            {"id": "a", "description": "Over 9.5", "type": "Over", "index": 0},
            {"id": "b", "description": "Under 9.5", "type": "Under",
             "index": 1},
        ])
    assert _novig_rows(market, MarketType.PLAYER_GAMES_WON) == []


# === the merge keys attach_novig_row needs ===

def test_novig_games_handicap_lands_on_the_optic_game_spread_key():
    """Novig SPREAD (strike = the HOME line) vs Optic game_spread.

    Before game_spread was registered there was no Optic row to land on,
    so every one of these was a load-time drop.
    """
    optic = _optic_rows([
        Odd(id="o1", market_id="game_spread",
            selection="Genaro Alberto Olivieri", selection_line=None,
            points=-1.5, team_id=HOME_OPTIC, player_id=None,
            grouping_key="default:1.5"),
        Odd(id="o2", market_id="game_spread", selection="Tomas Barrios Vera",
            selection_line=None, points=1.5, team_id=AWAY_OPTIC,
            player_id=None, grouping_key="default:1.5"),
    ])
    novig = _novig_rows(
        _novig_market("SPREAD", strike=-1.5, outcomes=[
            {"id": "n-home", "description": "G. Olivieri -1.5",
             "type": "Home", "index": 0},
            {"id": "n-away", "description": "T. Barrios Vera +1.5",
             "type": "Away", "index": 1},
        ]),
        novig_markets.TENNIS["SPREAD"])

    assert {row_key(r) for r in novig} == {row_key(r) for r in optic}


def test_novig_player_games_won_lands_on_the_optic_key():
    optic = _optic_rows([
        Odd(id="o1", market_id="player_games_won",
            selection="Genaro Alberto Olivieri", selection_line="over",
            points=9.5, team_id=HOME_OPTIC, player_id=HOME_OPTIC,
            grouping_key="genaro_alberto_olivieri:9.5"),
        Odd(id="o2", market_id="player_games_won",
            selection="Genaro Alberto Olivieri", selection_line="under",
            points=9.5, team_id=HOME_OPTIC, player_id=HOME_OPTIC,
            grouping_key="genaro_alberto_olivieri:9.5"),
    ])
    novig = _novig_rows(
        _novig_market(
            "PLAYER_GAMES_WON", strike=9.5,
            player={"id": "p1", "name": "Genaro Alberto Olivieri",
                    "fullName": "Genaro Alberto Olivieri",
                    "opticOddsId": HOME_OPTIC},
            outcomes=[
                {"id": "n-over", "description": "Over 9.5", "type": "Over",
                 "index": 0},
                {"id": "n-under", "description": "Under 9.5",
                 "type": "Under", "index": 1},
            ]),
        MarketType.PLAYER_GAMES_WON)

    assert {row_key(r) for r in novig} == {row_key(r) for r in optic}
