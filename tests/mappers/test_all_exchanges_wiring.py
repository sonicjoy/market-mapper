"""Exchange coverage for UEFA/Brazil/Sudamericana/esports all-exchanges pass."""

from mappers.exchanges.kalshi import KalshiConfig
from mappers.run import LEAGUES
from mappers.seed.tip_factories import sport_of


def test_europa_league_crypto_wired():
    cfg = LEAGUES["europa_league"]
    assert cfg.CRYPTO is not None and cfg.CRYPTO.league == "UEL"


def test_europa_conference_crypto_wired():
    cfg = LEAGUES["europa_conference_league"]
    assert cfg.CRYPTO is not None and cfg.CRYPTO.league == "UCOL"


def test_sudamericana_polymarket_wired():
    cfg = LEAGUES["conmebol_sudamericana"]
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "sud"
    assert cfg.POLYMARKET.optic_league_id == cfg.OPTIC.league_id


def test_every_league_gets_sport_scoped_kalshi_config():
    for slug in ("europa_league", "brazil_serie_a", "korea_k2", "cs2"):
        cfg = LEAGUES[slug]
        assert KalshiConfig(sport=sport_of(cfg)) == cfg.KALSHI


def test_canada_premier_polymarket_wired():
    cfg = LEAGUES["canada_premier_league"]
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "canpl"


def test_cs2_crypto_wired():
    assert LEAGUES['cs2'].CRYPTO is not None
    assert LEAGUES['cs2'].CRYPTO.league == "CS2"
