"""Kalshi NFL "Winning Margin" (KXNFLWINMARGIN): one YES_NO per bucket.

Real shape (2026-10-15 SEA v DEN): event scope "Winning Margin", a team
leg per bucket ("1 to 6", "7 to 14", "15 or more") with the team's id in
custom_strike["football_team"], and a "tie" leg that names a third id.
"""

from __future__ import annotations

import pytest

from mappers.exchanges.kalshi import (
    GameYesNoMarket,
    KalshiConfig,
    Market,
    TeamYesNoMarket,
    build_rows,
    parse_typed_market,
)
from mappers.sport import Sport

FOOTBALL = KalshiConfig(sport=Sport.FOOTBALL)
MS = {"id": "ms", "home_id": "den-id", "away_id": "sea-id", "tie_id": None}


def _leg(bucket: str, team_id: str) -> Market:
    return Market(
        event_ticker="E", ticker=f"T-{bucket}", title="Winning Margin", yes_sub_title=bucket,
        strike_type="custom", custom_strike={"Winning Margin": bucket, "football_team": team_id},
        competition_scope="Winning Margin", series_scope="Winning Margin", milestone=MS,
    )


@pytest.mark.parametrize("bucket,key", [("1 to 6", "1_to_6"), ("7 to 14", "7_to_14"), ("15 or more", "15_or_more")])
def test_team_bucket_is_a_team_yes_no(bucket, key):
    parsed = parse_typed_market(_leg(bucket, "sea-id"), FOOTBALL)
    assert isinstance(parsed, TeamYesNoMarket)
    assert parsed.market_type.value == "winning_margin_5-way"
    assert (parsed.side, parsed.grouping_key) == ("away", key)


def test_tie_is_a_game_yes_no_whatever_id_it_names():
    parsed = parse_typed_market(_leg("tie", "third-id"), FOOTBALL)
    assert isinstance(parsed, GameYesNoMarket) and parsed.grouping_key == "tie"


def test_only_the_yes_leg_maps():
    legs = [_leg("7 to 14", "den-id"), _leg("7 to 14", "sea-id"), _leg("tie", "third-id")]
    rows = build_rows("2026-10-15", "DEN", "SEA", legs, FOOTBALL, league="nfl")
    got = sorted(((r.entity, r.grouping_key, r.side) for r in rows), key=str)
    assert {r.market_type for r in rows} == {"winning_margin_5-way"}
    assert [g[2] for g in got if g[1] == "tie"] == ["yes"]
    assert {g[0] for g in got if g[1] == "tie"} == {None}
    assert [g[2] for g in got if g[1] == "7_to_14"] == ["yes", "yes"]
    assert {r.kalshi_side for r in rows} == {"yes"}
    assert len({g[0] for g in got if g[1] == "7_to_14"}) == 2


def test_team_bucket_without_a_team_id_is_refused():
    with pytest.raises(ValueError):
        parse_typed_market(_leg("1 to 6", "third-id"), FOOTBALL)
