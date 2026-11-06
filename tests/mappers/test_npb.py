"""NPB (Japan baseball) league config"""

from mappers.market_types import MarketType
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.sport import Sport, sport_for_league


def _npb_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "npb")
    return build_tip_league(row)


def test_npb_on_tip():
    assert any(r.league == "npb" for r in load_fixture().leagues)
    assert sport_for_league("npb") == Sport.BASEBALL


def test_optic_config_matches_confirmed_live_markets():
    cfg = _npb_cfg()
    assert cfg.OPTIC.league_id == "npb"
    assert cfg.OPTIC.table_types["moneyline"] == MarketType.MONEYLINE
    assert cfg.OPTIC.table_types["run_line"] == MarketType.POINT_SPREAD
    assert cfg.OPTIC.table_types["total_runs"] == MarketType.GAME_TOTAL


def test_no_px_crypto_polymarket_wired_for_v1():
    cfg = _npb_cfg()
    assert cfg.PX is None
    assert cfg.CRYPTO is None
    assert cfg.POLYMARKET is None
