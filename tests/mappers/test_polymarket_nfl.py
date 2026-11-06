"""NFL Polymarket wiring — game-line MVP (ML / spread / total).

Question forms byte-checked against live gamma event
nfl-car-ari-2026-08-07 (Panthers vs. Cardinals, 2026-08-05).
"""

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType, Scope
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league


def _nfl_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "nfl")
    return build_tip_league(row)


def _nfl_poly():
    poly = _nfl_cfg().POLYMARKET
    assert poly is not None
    return poly


def test_nfl_polymarket_wired():
    cfg = _nfl_poly()
    assert cfg.slug_prefix == "nfl"
    assert cfg.optic_league_id == "nfl"
    assert cfg.market_types["moneyline"] == MarketType.MONEYLINE
    assert cfg.market_types["spread"] == MarketType.POINT_SPREAD
    assert cfg.market_types["total"] == MarketType.GAME_TOTAL
    assert cfg.market_rules == (
        pm.mlb_total_rule,
        pm.mlb_spread_rule,
        pm.mlb_moneyline_rule,
    )


def test_nfl_poly_moneyline_hof():
    cfg = _nfl_poly()
    out = pm.mlb_moneyline_rule("Panthers vs. Cardinals", cfg)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.market_type.scope == Scope.GAME
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm._norm_name("Panthers", "mlb_suffix")
    assert out.team_b == pm._norm_name("Cardinals", "mlb_suffix")


def test_nfl_poly_total_hof():
    cfg = _nfl_poly()
    out = pm.mlb_total_rule("Panthers vs. Cardinals: O/U 35.5", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.line == 35.5
    assert out.side_mode == pm.SideMode.OVER_UNDER


def test_nfl_poly_total_abbr_form():
    """Alternate total wording on the same event."""
    cfg = _nfl_poly()
    out = pm.mlb_total_rule("CAR vs. ARI: O/U 36.5", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.line == 36.5


def test_nfl_poly_spread_hof():
    cfg = _nfl_poly()
    out = pm.mlb_spread_rule("Spread: Panthers (-1.5)", cfg)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    assert out.line == -1.5


def test_nfl_poly_drops_team_total_and_1h():
    """Out-of-MVP Poly forms on the HOF event must not false-match."""
    cfg = _nfl_poly()
    assert pm.parse_question("Cardinals Team Total: O/U 17.5", cfg) is None
    assert pm.parse_question("Panthers vs. Cardinals: 1H O/U 17.5", cfg) is None
    assert pm.parse_question("Panthers vs. Cardinals: 1H Moneyline", cfg) is None
    assert pm.parse_question("1H Spread: Panthers (-0.5)", cfg) is None
