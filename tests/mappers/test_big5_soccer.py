"""Big-5 soccer wiring — Italy Serie A / France Ligue 1 / Germany Bundesliga."""

from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league


def test_italy_serie_a_registered():
    cfg = LEAGUES["italy_serie_a"]
    assert sport_for_league("italy_serie_a") == Sport.SOCCER
    assert cfg.OPTIC.league_id == "italy_-_serie_a"
    assert cfg.KALSHI is not None
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "sea"
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.league == "ITSA"
    assert cfg.PX is None


def test_france_ligue_1_registered():
    cfg = LEAGUES["france_ligue_1"]
    assert sport_for_league("france_ligue_1") == Sport.SOCCER
    assert cfg.OPTIC.league_id == "france_-_ligue_1"
    assert cfg.KALSHI is not None
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "fl1"
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.league == "FRL1"


def test_germany_bundesliga_registered():
    cfg = LEAGUES["germany_bundesliga"]
    assert sport_for_league("germany_bundesliga") == Sport.SOCCER
    assert cfg.OPTIC.league_id == "germany_-_bundesliga"
    assert cfg.KALSHI is not None
    assert cfg.POLYMARKET is not None
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.league == "DEB"
