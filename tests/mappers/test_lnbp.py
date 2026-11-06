"""Mexico LNBP league config."""

from mappers.market_types import MarketType
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.sport import Sport, sport_for_league


def _lnbp_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "lnbp")
    return build_tip_league(row)


def test_lnbp_on_tip():
    assert any(r.league == "lnbp" for r in load_fixture().leagues)
    assert sport_for_league("lnbp") == Sport.BASKETBALL


def test_moneyline_only_configs_match_live_probe():
    cfg = _lnbp_cfg()
    assert cfg.OPTIC.league_id == "mexico_-_lnbp"
    assert cfg.OPTIC.table_types["moneyline"] == MarketType.MONEYLINE


def test_no_unverified_platforms_are_wired():
    cfg = _lnbp_cfg()
    assert cfg.PX is None
    assert cfg.CRYPTO is None
    assert cfg.POLYMARKET is None
