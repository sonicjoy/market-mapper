"""England Community Shield wiring - registry and exchanges.

Single-match annual season-opener: Premier League champion vs FA Cup
winner.
"""

from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league
from mappers.vocab.soccer_markets import SOCCER_OPTIC_CUP_TABLE_TYPES


def test_england_community_shield_registered():
    assert "england_community_shield" in LEAGUES
    assert LEAGUES["england_community_shield"] is LEAGUES['england_community_shield']
    assert sport_for_league("england_community_shield") == Sport.SOCCER


def test_england_community_shield_exchange_ids():
    assert LEAGUES['england_community_shield'].OPTIC.league_id == "england_-_community_shield"
    assert LEAGUES['england_community_shield'].PX is None
    assert LEAGUES['england_community_shield'].CRYPTO is None
    assert LEAGUES['england_community_shield'].POLYMARKET is None


def test_england_community_shield_uses_the_cup_taxonomy():
    assert LEAGUES['england_community_shield'].OPTIC.table_types == dict(SOCCER_OPTIC_CUP_TABLE_TYPES)
    assert MarketType.TO_ADVANCE in LEAGUES['england_community_shield'].OUTPUT_ORDER
    assert MarketType.MONEYLINE_3WAY in LEAGUES['england_community_shield'].OUTPUT_ORDER
