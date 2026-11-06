"""Kalshi NFL "(Protected)" player props: the base prop's mapping, typed `_insurance`.

Real shape (2026-10-15 SEA v DEN): KXNFLPASSYDSPROT et al. carry event scope
"Passing Yards (Protected)" under the shared series scope "Protected Props",
with the same typed strike fields as KXNFLPASSYDS.  Tickers are opaque ids.
"""

from __future__ import annotations

import pytest

from mappers.exchanges.kalshi import KalshiConfig, Market, OverUnderMarket, build_rows, parse_typed_market
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import market_type_for_scope

FOOTBALL = KalshiConfig(sport=Sport.FOOTBALL)

# (Kalshi scope, base canonical type, stat word in the title)
_PROPS = [
    ("Anytime Touchdowns", "player_touchdowns", "touchdowns"),
    ("Passing Yards", "player_passing_yards", "passing yards"),
    ("Passing Touchdowns", "player_passing_touchdowns", "passing touchdowns"),
    ("Receiving Yards", "player_receiving_yards", "receiving yards"),
    ("Receptions", "player_receptions", "receptions"),
    ("Rushing Yards", "player_rushing_yards", "rushing yards"),
]


def _prop(scope: str, stat: str, *, protected: bool, floor: float = 149.5) -> Market:
    suffix = " (Protected)" if protected else ""
    return Market(
        event_ticker="E", ticker="T-1", title=f"Bo Nix: {int(floor + 0.5)}+ {stat}{suffix}",
        strike_type="greater", floor_strike=floor,
        custom_strike={"football_player": "p-id", "football_team": "t-id"},
        competition_scope=f"{scope}{suffix}",
        series_scope="Protected Props" if protected else scope,
    )


@pytest.mark.parametrize("scope,base,stat", _PROPS)
def test_protected_prop_is_the_base_type_with_insurance(scope, base, stat):
    std = parse_typed_market(_prop(scope, stat, protected=False), FOOTBALL)
    prot = parse_typed_market(_prop(scope, stat, protected=True), FOOTBALL)
    assert isinstance(std, OverUnderMarket) and isinstance(prot, OverUnderMarket)
    assert std.market_type.value == base
    assert prot.market_type.value == f"{base}_insurance"
    assert (prot.market_type.scope, prot.market_type.shape) == (std.market_type.scope, std.market_type.shape)
    assert (prot.line, prot.player_name) == (std.line, std.player_name) == (149.5, "Bo Nix")


@pytest.mark.parametrize("scope,base,stat", _PROPS)
def test_protected_rows_equal_the_standard_rows_but_for_the_type(scope, base, stat):
    def rows(protected: bool):
        m = _prop(scope, stat, protected=protected, floor=1.5)
        return build_rows("2026-10-15", "SEA", "DEN", [m], FOOTBALL, league="nfl")

    std, prot = rows(False), rows(True)
    assert {r.market_type for r in std} == {base}
    assert {r.market_type for r in prot} == {f"{base}_insurance"}
    shape = lambda rs: sorted((r.line, r.side, r.entity) for r in rs)  # noqa: E731
    assert shape(prot) == shape(std) == [(1.5, "over", "bo_nix"), (1.5, "under", "bo_nix")]


def test_the_shared_series_scope_alone_maps_nothing():
    assert market_type_for_scope(Sport.FOOTBALL, "Protected Props") is None


BASKETBALL = KalshiConfig(sport=Sport.BASKETBALL)

# KXNBAPTSPROT / REBPROT / ASTPROT / 3PTPROT; scope assumed "<base scope> (Protected)" as NFL.
_NBA_PROPS = [
    ("Player Points", "player_points"),
    ("Player Rebounds", "player_rebounds"),
    ("Player Assists", "player_assists"),
    ("Player Threes", "player_threes"),
]


@pytest.mark.parametrize("scope,base", _NBA_PROPS)
def test_nba_protected_prop_is_the_base_type_with_insurance(scope, base):
    def parse(protected: bool):
        suffix = " (Protected)" if protected else ""
        return parse_typed_market(Market(
            event_ticker="E", ticker="T-1", title=f"Jalen Brunson: 25+ x{suffix}",
            strike_type="greater", floor_strike=24.5,
            custom_strike={"basketball_player": "p-id"},
            competition_scope=f"{scope}{suffix}",
            series_scope="Protected Props" if protected else scope,
        ), BASKETBALL)

    std, prot = parse(False), parse(True)
    assert isinstance(std, OverUnderMarket) and isinstance(prot, OverUnderMarket)
    assert prot.market_type.value == f"{base}_insurance"
    assert (prot.market_type.scope, prot.market_type.shape) == (std.market_type.scope, std.market_type.shape)
    assert (prot.line, prot.player_name) == (std.line, std.player_name)
