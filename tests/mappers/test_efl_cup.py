"""EFL Cup (English League Cup) wiring — registry and exchanges."""

from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league
from mappers.vocab.soccer_markets import SOCCER_OPTIC_CUP_TABLE_TYPES


def test_efl_cup_registered():
    assert "efl_cup" in LEAGUES
    assert LEAGUES["efl_cup"] is LEAGUES['efl_cup']
    assert sport_for_league("efl_cup") == Sport.SOCCER


def test_efl_cup_exchange_ids():
    assert LEAGUES['efl_cup'].OPTIC.league_id == "england_-_efl_cup"
    assert LEAGUES['efl_cup'].PX is None
    assert LEAGUES['efl_cup'].CRYPTO is not None
    assert LEAGUES['efl_cup'].CRYPTO.league == "EFLC"
    assert LEAGUES['efl_cup'].POLYMARKET is None


def test_efl_cup_uses_the_cup_taxonomy():
    assert LEAGUES['efl_cup'].OPTIC.table_types == dict(SOCCER_OPTIC_CUP_TABLE_TYPES)
    assert MarketType.MONEYLINE_3WAY in LEAGUES['efl_cup'].OUTPUT_ORDER
