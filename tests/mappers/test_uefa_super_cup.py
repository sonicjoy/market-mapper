"""UEFA Super Cup wiring — registry and exchanges.

Single-match annual final: Champions League winner vs Europa League winner.
"""

from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league
from mappers.vocab.soccer_markets import SOCCER_OPTIC_CUP_TABLE_TYPES


def test_uefa_super_cup_registered():
    assert "uefa_super_cup" in LEAGUES
    assert LEAGUES["uefa_super_cup"] is LEAGUES['uefa_super_cup']
    assert sport_for_league("uefa_super_cup") == Sport.SOCCER


def test_uefa_super_cup_exchange_ids():
    assert LEAGUES['uefa_super_cup'].OPTIC.league_id == "uefa_-_super_cup"
    assert LEAGUES['uefa_super_cup'].PX is None
    assert LEAGUES['uefa_super_cup'].CRYPTO is None


def test_uefa_super_cup_polymarket_wired():
    # Was POLYMARKET=None for one day (wired 2026-08-10, poly added 2026-08-11
    # once a live bridge sample confirmed the "usc-" slug prefix). This was the
    # largest unmapped competition among leagues we already fetch Optic
    # fixtures for -- 13.7k dropped legs in a 3h window.
    poly = LEAGUES['uefa_super_cup'].POLYMARKET
    assert poly is not None
    assert poly.slug_prefix == "usc"
    assert poly.optic_league_id == LEAGUES['uefa_super_cup'].OPTIC.league_id
    # PSG/Aston Villa both resolve by containment against Optic's
    # "... FC"-suffixed names, so no alias overlay is needed.
    assert poly.team_name_aliases == {}


def test_uefa_super_cup_uses_the_cup_taxonomy():
    assert LEAGUES['uefa_super_cup'].OPTIC.table_types == dict(SOCCER_OPTIC_CUP_TABLE_TYPES)
    assert MarketType.TO_ADVANCE in LEAGUES['uefa_super_cup'].OUTPUT_ORDER
    assert MarketType.MONEYLINE_3WAY in LEAGUES['uefa_super_cup'].OUTPUT_ORDER
