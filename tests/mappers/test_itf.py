"""Wiring coverage for "itf_men" / "itf_women" (tip-only)."""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

import pytest  # noqa: E402

from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.exchanges.kalshi import KalshiConfig  # noqa: E402
from mappers.market_types import MarketType  # noqa: E402
from mappers.seed.fixture_store import load_fixture  # noqa: E402
from mappers.seed.tip_factories import build_tip_league  # noqa: E402
from mappers.sport import Sport, sport_for_league  # noqa: E402
from mappers.vocab.tennis_aliases import TENNIS_TEAM_NAME_ALIASES  # noqa: E402
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES  # noqa: E402


def _tip_cfg(league: str):
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == league)
    return build_tip_league(row)


@pytest.mark.parametrize(
    ("league", "optic_id"),
    [
        ("itf_men", "itf_men"),
        ("itf_women", "itf_women"),
    ],
)
def test_league_value_equals_optic_league_id(league, optic_id):
    cfg = _tip_cfg(league)
    assert league == optic_id
    assert cfg.OPTIC.league_id == league
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.optic_league_id == league


@pytest.mark.parametrize("league", ["itf_men", "itf_women"])
def test_classified_as_tennis(league):
    assert sport_for_league(league) == Sport.TENNIS
    assert _tip_cfg(league).sport == Sport.TENNIS


def test_fetchable_and_uses_the_tennis_subscription_secret():
    from fetch.tip import optic_api_key_secret

    tennis_secret = "opticodds_parlay_tennis_access_key"
    for league in ("itf_men", "itf_women"):
        assert optic_api_key_secret(str(league)) == tennis_secret


def test_shares_the_itf_slug_prefix():
    men = _tip_cfg("itf_men")
    women = _tip_cfg("itf_women")
    assert men.POLYMARKET is not None and women.POLYMARKET is not None
    assert men.POLYMARKET.slug_prefix == "itf"
    assert women.POLYMARKET.slug_prefix == "itf"
    assert men.POLYMARKET.optic_league_id != women.POLYMARKET.optic_league_id


@pytest.mark.parametrize("league", ["itf_men", "itf_women"])
def test_reuses_atp_market_taxonomy(league):
    cfg = _tip_cfg(league)
    assert cfg.POLYMARKET is not None and cfg.OPTIC is not None
    assert cfg.POLYMARKET.market_types == pm.TENNIS_MARKET_TYPES
    assert cfg.POLYMARKET.market_rules is pm.tennis_market_rules
    assert cfg.POLYMARKET.question_style == "tennis_prefix"
    assert cfg.OPTIC.table_types == dict(TENNIS_OPTIC_TABLE_TYPES)
    assert cfg.POLYMARKET.team_name_aliases == TENNIS_TEAM_NAME_ALIASES


@pytest.mark.parametrize(
    ("league", "meta"),
    [
        ("itf_men", "ITF"),
        ("itf_women", "ITF"),
    ],
)
def test_exchange_feed_wiring(league, meta):
    cfg = _tip_cfg(league)
    crypto = cfg.CRYPTO
    assert KalshiConfig(sport=Sport.TENNIS) == cfg.KALSHI
    assert cfg.PX is None
    assert crypto is not None
    assert crypto.league == meta
    assert crypto.symbol_prefix == "TENNIS"
    assert crypto.contract_types == {"Moneyline": MarketType.MONEYLINE}


def test_crypto_meta_maps_both_itf_leagues():
    men = build_tip_league(next(r for r in load_fixture().leagues if r.league == "itf_men"))
    women = build_tip_league(
        next(r for r in load_fixture().leagues if r.league == "itf_women")
    )
    assert men.CRYPTO is not None and men.CRYPTO.league == "ITF"
    assert women.CRYPTO is not None and women.CRYPTO.league == "ITF"


