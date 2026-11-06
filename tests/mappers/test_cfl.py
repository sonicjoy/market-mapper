"""CFL Polymarket / Kalshi / tip wiring — game-line MVP."""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from mappers.exchanges import polymarket as pm
from mappers.exchanges.kalshi import KalshiConfig
from mappers.market_types import MarketType, Scope
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.sport import Sport
from mappers.vocab.football_markets import CFL_PX, FOOTBALL_POLY_TEAM_NAME_ALIASES


def _tip_cfg():
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "cfl")
    return build_tip_league(row)


def test_cfl_tip_builds_football_config():
    cfg = _tip_cfg()
    assert cfg.league == "cfl"
    assert cfg.sport == Sport.FOOTBALL
    assert cfg.OPTIC.league_id == "cfl"
    assert KalshiConfig(sport=Sport.FOOTBALL) == cfg.KALSHI
    assert cfg.PX is not None
    assert cfg.PX.tournament_id == CFL_PX.tournament_id
    assert cfg.CRYPTO is None


def test_cfl_px_exact():
    assert CFL_PX.exact == {
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
    }


def test_cfl_polymarket_wired():
    cfg = _tip_cfg()
    poly = cfg.POLYMARKET
    assert poly is not None
    assert poly.slug_prefix == "cfl"
    assert poly.optic_league_id == "cfl"
    assert poly.market_types["moneyline"] == MarketType.MONEYLINE
    assert poly.market_types["spread"] == MarketType.POINT_SPREAD
    assert poly.market_types["total"] == MarketType.GAME_TOTAL
    assert poly.market_rules == (
        pm.mlb_total_rule,
        pm.mlb_spread_rule,
        pm.mlb_moneyline_rule,
    )
    assert poly.team_name_aliases == FOOTBALL_POLY_TEAM_NAME_ALIASES


def test_cfl_poly_moneyline():
    cfg = _tip_cfg().POLYMARKET
    assert cfg is not None
    out = pm.mlb_moneyline_rule(
        "Hamilton Tiger-Cats vs. British Columbia Lions", cfg)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.market_type.scope == Scope.GAME
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm._norm_name("Hamilton Tiger-Cats", "mlb_suffix")
    assert out.team_b == pm._norm_name("British Columbia Lions", "mlb_suffix")


def test_cfl_poly_total():
    cfg = _tip_cfg().POLYMARKET
    assert cfg is not None
    out = pm.mlb_total_rule(
        "Hamilton Tiger-Cats vs. British Columbia Lions: O/U 55.5", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.line == 55.5
    assert out.side_mode == pm.SideMode.OVER_UNDER


def test_cfl_poly_spread():
    cfg = _tip_cfg().POLYMARKET
    assert cfg is not None
    out = pm.mlb_spread_rule("Spread: British Columbia Lions (-4.5)", cfg)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    assert out.line == -4.5


def test_cfl_bc_lions_alias_matches_optic():
    """Poly full name must resolve to Optic's short 'BC Lions'."""
    cfg = _tip_cfg().POLYMARKET
    assert cfg is not None
    poly = pm._norm_name("British Columbia Lions", "mlb_suffix")
    optic = pm._norm_name("BC Lions", "mlb_suffix")
    with pm.team_alias_scope(cfg.team_name_aliases):
        assert pm._name_match(poly, optic, "mlb_suffix")


def test_cfl_optic_stays_game_lines():
    """Period / team-total / player Optic ids stay NFL+NCAAF."""
    cfg = _tip_cfg()
    assert cfg.OPTIC.table_types == {
        "moneyline": MarketType.MONEYLINE,
        "point_spread": MarketType.POINT_SPREAD,
        "total_points": MarketType.GAME_TOTAL,
    }
    for key in (
        "team_total",
        "1st_half_moneyline_3-way",
        "player_passing_yards",
        "1st_quarter_point_spread",
    ):
        assert key not in cfg.OPTIC.table_types


