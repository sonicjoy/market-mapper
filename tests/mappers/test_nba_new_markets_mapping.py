"""New NBA markets: PolyUS PRA + race to N, crypto.com PRA / steals / blocks / double double.

Shapes copied from live payloads for BOS @ DET 2026-10-20 (gateway event
135241, crypto.com catalogue, Optic fixture 20261020D42F1161) on 2026-10-19.
Polymarket US lists no PRA yet; its shape is the venue's other basketball
player props (``N+`` Yes/No, ``metadata.playerName``).

Each venue test asserts the key its row is matched on equals the key
``optic.build_rows`` produces for the same Optic selection.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import mappers.pipeline  # noqa: F401 - settles the vocab/polymarket import cycle
from mappers.exchanges import optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.crypto_com import build_rows, parse_selection
from mappers.exchanges.polymarket_usa_sides import venue_side
from mappers.market_types import MarketType as M
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES, NBA_CRYPTO, WNBA_CRYPTO
from mappers.vocab.poly_usa_smt import smt_spec

NBA_OPTIC = optic.OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES))
_BIND = pus.EventBind(fixture=SimpleNamespace(home="DET", away="BOS", fixture_id="F"),
                      team_sides={"17": "BOS", "23": "DET"})


def _optic_keys(*odds: optic.Odd) -> set[tuple]:
    fx = optic.Fixture(
        fixture_id="F", game_id="G", sportradar_id=None, start_et="2026-10-20T15:00:00",
        start_date="2026-10-20T19:00:00Z", home="DET", away="BOS", home_name="Detroit Pistons",
        away_name="Boston Celtics", team_map={"OPT-DET": "DET", "OPT-BOS": "BOS"},
        odds=list(odds), is_live=False,
    )
    rows, _, _ = optic.build_rows("2026-10-20T19:00:00Z", "DET", "BOS", fx, NBA_OPTIC, league="nba")
    return {(r.market_type, r.entity, r.line, r.side) for r in rows}


def _odd(market_id: str, selection: str, selection_line: str | None, points: float | None,
         team_id: str | None = None, player_id: str | None = None) -> optic.Odd:
    return optic.Odd(id=f"F:b:{market_id}:{selection}:{points}", market_id=market_id, selection=selection,
                     selection_line=selection_line, points=points, team_id=team_id, player_id=player_id,
                     grouping_key="default")


# --- Polymarket US ---

@pytest.mark.parametrize("smt", [
    "basketball_player_points", "basketball_player_rebounds", "basketball_player_assists",
    "basketball_player_threes", "basketball_player_steals", "basketball_player_blocks",
    "basketball_player_points_rebounds_assists", "basketball_game_race_to_points",
])
def test_every_listed_basketball_type_has_an_optic_side(smt: str) -> None:
    """An enum the generic player_<stat> fallback cannot name is dropped silently."""
    spec = smt_spec(smt)
    assert spec is not None
    assert spec[0] in set(BASKETBALL_OPTIC_TABLE_TYPES.values())


def _us_market(smt: str, line: float, metadata: dict[str, Any], team_id: str) -> pus.UsMarket:
    obj = {
        "league_id": 2, "event_id": "135241", "event_ticker": "evt",
        "event_start": "2026-10-20T19:00:00Z", "sportradar_game_id": "",
        "teams": [{"id": "17", "abbreviation": "bos", "name": "Celtics"},
                  {"id": "23", "abbreviation": "det", "name": "Pistons"}],
        "market_id": "m1", "slug": "m1", "sports_market_type": smt, "line": line, "metadata": metadata,
        "sides": [{"id": "a", "long": True, "description": "Yes", "team_id": team_id},
                  {"id": "b", "long": False, "description": "No", "team_id": team_id}],
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def test_polyus_pra_n_plus_is_over_below_the_line() -> None:
    market = _us_market("basketball_player_points_rebounds_assists", 20,
                        {"lineLabel": "20+", "playerName": "John Collins", "teamId": 23}, "23")
    bets = pus.market_bets(market, _BIND)
    assert bets == [
        (M.PLAYER_PTS_REB_AST.value, "john_collins", 19.5, "over"),
        (M.PLAYER_PTS_REB_AST.value, "john_collins", 19.5, "under"),
    ]
    assert [venue_side(market, _BIND, b) for b in bets] == ["yes", "no"]
    assert set(bets) <= _optic_keys(
        _odd("player_points_+_rebounds_+_assists", "John Collins", "over", 19.5, player_id="P1"),
        _odd("player_points_+_rebounds_+_assists", "John Collins", "under", 19.5, player_id="P1"),
    )


def test_polyus_race_maps_the_named_team_yes_only() -> None:
    """``atc-…-race10-bos``: Yes = BOS first to 10; its No is not mapped."""
    market = _us_market("basketball_game_race_to_points", 10, {}, "17")
    (bet,) = pus.market_bets(market, _BIND)
    assert bet == (M.RACE_TO_POINTS.value, None, 10.0, "BOS")
    assert venue_side(market, _BIND, bet) == "yes"
    assert bet in _optic_keys(
        _odd("race_to_10_points", "Boston Celtics", None, None, team_id="OPT-BOS"),
        _odd("race_to_10_points", "Detroit Pistons", None, None, team_id="OPT-DET"),
    )


# --- crypto.com ---

def _crypto_prop(contract: str, participant: str, outcome: str, value: float | None, desc: str) -> str:
    return json.dumps({
        "SecurityID": f"S-{contract}", "Symbol": "NX.F.OPT.NBA-00001-261020-M.O.1.369.20270731",
        "eventMetaLEAGUE": "NBA", "eventMetaSPORTS_GROUPING": "Basketball",
        "eventMetaEVENT_DATE": "2026-10-20T19:00:00+00:00", "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
        "eventMetaPREDICT_CONTRACT_TYPE": contract, "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
        "eventMetaPREDICT_OUTCOME_TYPE": outcome, "eventMetaPREDICT_VALUE": value, "eventName": desc,
        "eventMetaPREDICT_MARKET_ID": "MKT", "eventMetaPREDICT_OUTCOME_ID": "OUT",
        "eventMetaPARTICIPANT": participant, "eventMetaPLAYER_ID": None,
        "eventMetaEXTERNAL_HOME_ID": "H", "eventMetaEXTERNAL_AWAY_ID": "A", "eventMetaEXTERNAL_GAME_ID": "G",
        "eventMetaHOME_PARTICIPANT": "Detroit Pistons", "eventMetaAWAY_PARTICIPANT": "Boston Celtics",
    })


def _crypto_rows(line: str) -> list:
    sel = parse_selection(line)
    assert sel is not None
    return build_rows("2026-10-20T19:00:00+00:00", "DET", "BOS", [sel], NBA_CRYPTO,
                      aliases={"H": "DET", "A": "BOS"}, league="nba")


@pytest.mark.parametrize("contract,player,value,optic_market,mt", [
    ("Total Points, Rebounds, & Assists", "Jayson Tatum", 24.5,
     "player_points_+_rebounds_+_assists", M.PLAYER_PTS_REB_AST),
    ("Total Steals", "Jayson Tatum", 0.5, "player_steals", M.PLAYER_STEALS),
    ("Total Blocks", "Derrick White", 0.5, "player_blocks", M.PLAYER_BLOCKS),
])
def test_crypto_over_ladder_props(contract, player, value, optic_market, mt) -> None:
    (row,) = _crypto_rows(_crypto_prop(contract, player, "Over", value, f"{player} Over {value} {contract}"))
    key = (row.market_type, row.entity, row.line, row.side)
    assert key == (mt.value, player.lower().replace(" ", "_"), value, "over")
    assert key in _optic_keys(_odd(optic_market, player, "over", value, player_id="P1"))


def test_crypto_double_double_yes_is_optic_over_half() -> None:
    (row,) = _crypto_rows(_crypto_prop("To Record a Double Double", "Cade Cunningham", "Yes", None,
                                       "Cade Cunningham To Record a Double Double"))
    key = (row.market_type, row.entity, row.line, row.side)
    assert key == (M.PLAYER_DOUBLE_DOUBLE.value, "cade_cunningham", None, "yes")
    assert key in _optic_keys(_odd("player_double_double", "Cade Cunningham", "over", 0.5, player_id="P1"))


def test_crypto_first_field_goal_scorer_stays_unmapped() -> None:
    """Optic's first basket counts free throws; the venue's does not."""
    assert _crypto_rows(_crypto_prop("First Field Goal Scorer", "John Collins", "Yes", None,
                                     "John Collins First Field Goal Scorer")) == []


def test_wnba_crypto_props_unchanged() -> None:
    for contract in ("Total Points, Rebounds, & Assists", "Total Steals", "Total Blocks",
                     "To Record a Double Double"):
        assert contract not in WNBA_CRYPTO.prop_contract_types
