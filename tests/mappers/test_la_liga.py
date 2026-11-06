"""Spain La Liga wiring — registry and exchanges."""

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league


def test_la_liga_registered():
    assert "la_liga" in LEAGUES
    assert LEAGUES["la_liga"] is LEAGUES['la_liga']
    assert sport_for_league("la_liga") == Sport.SOCCER


def test_la_liga_exchange_ids():
    assert LEAGUES['la_liga'].OPTIC.league_id == "spain_-_la_liga"
    assert LEAGUES['la_liga'].PX is not None
    assert LEAGUES['la_liga'].PX.tournament_id == 8
    assert LEAGUES['la_liga'].CRYPTO is not None
    assert LEAGUES['la_liga'].CRYPTO.league == "ESP"
    cfg = LEAGUES['la_liga'].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "lal"
    assert cfg.optic_league_id == "spain_-_la_liga"


def test_la_liga_poly_celta_alias():
    cfg = LEAGUES['la_liga'].POLYMARKET
    assert cfg is not None
    poly = pm._norm_name("RC Celta de Vigo", "mlb_suffix")
    optic = pm._norm_name("Real Club Celta de Vigo", "mlb_suffix")
    assert cfg.team_name_aliases[poly] == optic


def test_la_liga_poly_moneyline_rule():
    cfg = LEAGUES['la_liga'].POLYMARKET
    assert cfg is not None
    out = pm.soccer_ml_team_win_rule(
        "Will Club Atlético de Madrid win on 2026-08-19?", cfg,
    )
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE_3WAY
