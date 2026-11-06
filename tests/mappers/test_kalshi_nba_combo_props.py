"""Kalshi NBA combined-stat player props map like the single-stat ones.

Real shape (2026-10-20 BOS @ DET): KXNBAPRA events carry scope
"Pts + Reb + Ast" and KXNBASTOCK events "Steals + Blocks", with the same
typed strike fields as KXNBAREB.  Tickers are opaque ids.
"""

from __future__ import annotations

import pytest

from mappers.exchanges.kalshi import KalshiConfig, Market, OverUnderMarket, build_rows, parse_typed_market
from mappers.market_types import MarketType
from mappers.profiles._builders import OpticStandardProfile
from mappers.profiles.basketball import BASKETBALL_PROFILES
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import market_type_for_scope

BASKETBALL = KalshiConfig(sport=Sport.BASKETBALL)
OPTIC_TYPES = next(p.table_types for p in BASKETBALL_PROFILES if isinstance(p, OpticStandardProfile))

# (Kalshi scope, canonical type, Optic market_id, title, floor_strike, entity)
_PROPS = [
    ("Pts + Reb + Ast", MarketType.PLAYER_PTS_REB_AST, "player_points_+_rebounds_+_assists",
     "Jayson Tatum: 40+ points, rebounds, and assists", 39.5, "jayson_tatum"),
    ("Steals + Blocks", MarketType.PLAYER_STEALS_BLOCKS, "player_steals_+_blocks",
     "Ausar Thompson: 4+ steals and blocks", 3.5, "ausar_thompson"),
]


def _prop(scope: str, title: str, floor: float) -> Market:
    return Market(
        event_ticker="E", ticker="T-1", title=title,
        strike_type="greater", floor_strike=floor,
        custom_strike={"basketball_player": "p-id", "basketball_team": "t-id"},
        competition_scope=scope, series_scope=scope,
    )


@pytest.mark.parametrize("scope,mt,optic_market,title,floor,entity", _PROPS)
def test_kalshi_scope_and_optic_market_share_one_type(scope, mt, optic_market, title, floor, entity):
    assert market_type_for_scope(Sport.BASKETBALL, scope) == mt
    assert OPTIC_TYPES[optic_market] == mt


@pytest.mark.parametrize("scope,mt,optic_market,title,floor,entity", _PROPS)
def test_yes_is_over_and_no_is_under_at_the_strike(scope, mt, optic_market, title, floor, entity):
    m = _prop(scope, title, floor)
    p = parse_typed_market(m, BASKETBALL)
    assert isinstance(p, OverUnderMarket)
    assert (p.market_type, p.line) == (mt, floor)

    rows = build_rows("2026-10-20", "DET", "BOS", [m], BASKETBALL, league="nba")
    assert sorted((r.market_type, r.entity, r.line, r.side, r.kalshi_side) for r in rows) == [
        (mt.value, entity, floor, "over", "yes"),
        (mt.value, entity, floor, "under", "no"),
    ]
