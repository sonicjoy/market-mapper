"""Kalshi NFL first touchdown scorer (KXNFLFIRSTTD): one Yes per player, the No leg never maps.

Real shape (2026-10-15): event scope "First TD", title "<Player>: 1st Touchdown",
custom_strike carries football_player / football_team ids.
"""

from __future__ import annotations

from mappers.exchanges.kalshi import KalshiConfig, Market, YesNoMarket, build_rows, parse_typed_market
from mappers.sport import Sport

FOOTBALL = KalshiConfig(sport=Sport.FOOTBALL)


def _leg(player: str) -> Market:
    return Market(
        event_ticker="E", ticker=f"T-{player}", title=f"{player}: 1st Touchdown", yes_sub_title=player,
        strike_type="structured", custom_strike={"football_player": "p-id", "football_team": "t-id"},
        competition_scope="First TD", series_scope="First TD",
    )


def test_first_td_is_a_player_yes_no_of_the_first_touchdown_type():
    parsed = parse_typed_market(_leg("Jaxon Smith-Njigba"), FOOTBALL)
    assert isinstance(parsed, YesNoMarket)
    assert parsed.market_type.value == "first_touchdown_scorer"
    assert (parsed.player_name, parsed.yes_only) == ("Jaxon Smith-Njigba", True)


def test_only_the_yes_leg_maps():
    rows = build_rows("2026-10-15", "DEN", "SEA", [_leg("Jaxon Smith-Njigba"), _leg("Sam Darnold")], FOOTBALL, league="nfl")
    assert {r.market_type for r in rows} == {"first_touchdown_scorer"}
    assert [(r.side, r.kalshi_side) for r in rows] == [("yes", "yes")] * 2


def test_other_player_yes_no_still_maps_both_legs():
    leg = _leg("Cale Makar").model_copy(update={"competition_scope": "1st Goalscorer", "series_scope": "1st Goalscorer"})
    rows = build_rows("2026-10-15", "COL", "VGK", [leg], KalshiConfig(sport=Sport.HOCKEY), league="nhl")
    assert sorted(r.side for r in rows) == ["no", "yes"]
