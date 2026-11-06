"""Wiring coverage for WNBA / NBA / NCAAB tip-only basketball leagues."""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.pipeline import _match_poly_fixture
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.vocab.basketball_markets import BASKETBALL_MARKET_TYPES, basketball_market_rules


def _tip_cfg(league: str):
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == league)
    return build_tip_league(row)


def test_wnba_multiexchange_tip_build():
    league = _tip_cfg("wnba")
    assert league.KALSHI is not None
    assert league.PX is not None
    assert league.CRYPTO is not None
    assert league.POLYMARKET is not None


def test_wnba_polymarket_config_present():
    cfg = _tip_cfg("wnba").POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "wnba"
    assert cfg.optic_league_id == "wnba"
    assert cfg.market_types == BASKETBALL_MARKET_TYPES
    assert cfg.market_rules == basketball_market_rules


def test_wnba_optic_league_id():
    assert _tip_cfg("wnba").OPTIC.league_id == "wnba"


def test_wnba_optic_table_types_covers_the_6_poly_forms():
    table_types = _tip_cfg("wnba").OPTIC.table_types
    assert {
        "moneyline", "point_spread", "total_points",
        "player_points", "player_rebounds", "player_assists",
    } <= set(table_types)
    assert table_types["moneyline"] == MarketType.MONEYLINE
    assert table_types["point_spread"] == MarketType.POINT_SPREAD
    assert table_types["total_points"] == MarketType.GAME_TOTAL
    assert table_types["player_points"] == MarketType.PLAYER_POINTS
    assert table_types["player_rebounds"] == MarketType.PLAYER_REBOUNDS
    assert table_types["player_assists"] == MarketType.PLAYER_ASSISTS


class _FX:
    """Minimal optic-fixture stand-in carrying only what _match_poly_fixture reads."""

    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _wnba_parsed(team_a_poly_name: str, team_b_poly_name: str, date: str):
    return pm.ParsedMarket(
        market_type=MarketType.MONEYLINE,
        team_a=pm._norm_name(team_a_poly_name, "mlb_suffix"),
        team_b=pm._norm_name(team_b_poly_name, "mlb_suffix"),
        side_mode=pm.SideMode.TEAM_LABEL,
        date=date,
    )


def test_wnba_alias_resolves_portland_fire_fixture():
    cfg = _tip_cfg("wnba").POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Portland Fire", "Toronto Tempo", "2026-07-28T23:00:00Z")]
    parsed = _wnba_parsed("PortlandFire", "Toronto Tempo", "2026-07-28")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_wnba_alias_without_scope_does_not_match():
    fixtures = [_FX("Portland Fire", "Toronto Tempo", "2026-07-28T23:00:00Z")]
    parsed = _wnba_parsed("PortlandFire", "Toronto Tempo", "2026-07-28")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_wnba_alias_regression_normal_franchise_still_matches():
    cfg = _tip_cfg("wnba").POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Chicago Sky", "Dallas Wings", "2026-07-28T23:00:00Z")]
    parsed = _wnba_parsed("Chicago Sky", "Dallas Wings", "2026-07-28")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_wnba_alias_genuinely_absent_team_still_drops():
    cfg = _tip_cfg("wnba").POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Chicago Sky", "Dallas Wings", "2026-07-28T23:00:00Z")]
    parsed = _wnba_parsed("Las Vegas Aces", "Indiana Fever", "2026-07-28")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None


def test_wnba_dileo_player_prop_entity_aliases_to_gustafson():
    cfg = _tip_cfg("wnba").POLYMARKET
    assert cfg is not None
    assert cfg.team_name_aliases.get("megan_dileo") == "megan_gustafson"
    with pm.team_alias_scope(cfg.team_name_aliases):
        parsed = pm.parse_question("Megan DiLeo: Points O/U 15.5", cfg)
    assert parsed is not None
    assert parsed.market_type == MarketType.PLAYER_POINTS
    assert parsed.entity == "megan_gustafson"
    bare = pm.parse_question("Megan DiLeo: Points O/U 15.5", cfg)
    assert bare is not None
    assert bare.entity == "megan_dileo"


def test_nba_polymarket_config_present():
    cfg = _tip_cfg("nba").POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "nba"
    assert cfg.optic_league_id == _tip_cfg("nba").OPTIC.league_id == "nba"
    assert cfg.market_types == BASKETBALL_MARKET_TYPES
    assert cfg.market_rules == basketball_market_rules
    assert cfg.team_name_aliases == {}


def test_nba_kalshi_and_px_tip_build():
    league = _tip_cfg("nba")
    assert league.KALSHI is not None
    assert league.PX is not None
    assert league.CRYPTO is not None


def test_nba_basketball_moneyline_question_resolves_via_league_config():
    cfg = _tip_cfg("nba").POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Boston Celtics vs. Miami Heat", cfg)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE


def test_nba_basketball_total_question_resolves_via_league_config():
    cfg = _tip_cfg("nba").POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Boston Celtics vs. Miami Heat: O/U 214.5", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL


def test_ncaab_polymarket_config_present():
    cfg = _tip_cfg("ncaab").POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "ncaab"
    assert cfg.optic_league_id == _tip_cfg("ncaab").OPTIC.league_id == "ncaab"
    assert cfg.market_types == BASKETBALL_MARKET_TYPES
    assert cfg.market_rules == basketball_market_rules
    assert cfg.team_name_aliases == {}


def test_ncaab_kalshi_and_px_tip_build():
    league = _tip_cfg("ncaab")
    assert league.KALSHI is not None
    assert league.PX is not None


def test_ncaab_basketball_moneyline_question_resolves_via_league_config():
    cfg = _tip_cfg("ncaab").POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Duke Blue Devils vs. UNC Tar Heels", cfg)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE


def test_ncaab_basketball_total_question_resolves_via_league_config():
    cfg = _tip_cfg("ncaab").POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Duke Blue Devils vs. UNC Tar Heels: O/U 148.5", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL


def test_ncaab_optic_table_types_has_player_types():
    table_types = _tip_cfg("ncaab").OPTIC.table_types
    assert "player_points" in table_types
    assert "player_rebounds" in table_types
    assert "player_assists" in table_types
