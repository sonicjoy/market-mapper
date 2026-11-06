"""Cricket ODI league config.

Optic splits international ODIs and the English domestic one-day cup
into two league_ids, folded via extra_league_ids (same mechanism
wnba.py's all-star game uses).
"""

from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league


def test_cricket_odi_registered():
    assert "cricket_odi" in LEAGUES
    assert sport_for_league("cricket_odi") == Sport.CRICKET


def test_optic_folds_international_and_county_leagues():
    assert LEAGUES['cricket_odi'].OPTIC.league_id == "international_-_odi_matches"
    assert LEAGUES['cricket_odi'].OPTIC.extra_league_ids == ("england_-_one_day_cup",)
    assert LEAGUES['cricket_odi'].OPTIC.table_types == {"moneyline": MarketType.MONEYLINE}


def test_no_px_crypto_for_v1():
    assert LEAGUES["cricket_odi"].PX is None
    assert LEAGUES["cricket_odi"].CRYPTO is None
    assert LEAGUES["cricket_odi"].POLYMARKET is not None
    assert LEAGUES["cricket_odi"].POLYMARKET.slug_prefix == "crint"
