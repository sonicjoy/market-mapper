"""Novig and Huddle vocab is code: tip rules never touch it (AGENTS.md)."""

from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.novig import NovigConfig
from mappers.market_types import MarketType
from mappers.seed.overlay_taxonomy import overlay_huddle, overlay_novig
from mappers.vocab import novig_markets
from mappers.vocab.football_huddle import GAME_TYPES
from tests.mappers.test_overlay_taxonomy import LEAGUES, _ignore_row, _map_row


def test_novig_ignores_tip_rules():
    """Tip 'MONEY_1H -> 1h_moneyline' left 15 NFL + 57 NCAAF markets unmapped."""
    rows = [
        _map_row(league="nfl", sportsbook="novig", key_type="market_type",
                 key="MONEY_1H", canonical=MarketType.FIRST_HALF_MONEYLINE.value),
        _map_row(league="nfl", sportsbook="novig", key_type="market_type",
                 key="TIP_ONLY", canonical=MarketType.MONEYLINE.value),
        _ignore_row(league="nfl", sportsbook="novig", key_type="market_type",
                    key="TOUCHDOWNS"),
    ]
    novig = NovigConfig(league="NFL", market_types=dict(novig_markets.FOOTBALL))
    out = overlay_novig(novig, rows, LEAGUES["nfl"])
    assert out is novig
    assert out.market_types["MONEY_1H"] == MarketType.FIRST_HALF_WINNER_3WAY
    assert "TIP_ONLY" not in out.market_types
    assert out.market_types["TOUCHDOWNS"] == MarketType.PLAYER_TOUCHDOWNS


def test_huddle_ignores_tip_rules():
    rows = [_map_row(league="nfl", sportsbook="huddle", key_type="market_code",
                     key="RESULT", canonical=MarketType.POINT_SPREAD.value)]
    huddle = HuddleConfig(competition_ids=("c",), table_types=dict(GAME_TYPES))
    assert overlay_huddle(huddle, rows, LEAGUES["nfl"]) is huddle
