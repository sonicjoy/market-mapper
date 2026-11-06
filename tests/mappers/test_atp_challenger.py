"""Wiring coverage for "atp_challenger" (tip-only via parser profiles)."""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.exchanges.kalshi import KalshiConfig  # noqa: E402
from mappers.market_types import MarketType  # noqa: E402
from mappers.seed.fixture_store import load_fixture  # noqa: E402
from mappers.seed.tip_factories import build_tip_league  # noqa: E402
from mappers.sport import Sport, sport_for_league  # noqa: E402
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES  # noqa: E402


def _challenger_cfg():
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "atp_challenger")
    return build_tip_league(row)


def _atp_cfg():
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "atp")
    return build_tip_league(row)


def test_league_value_equals_optic_league_id():
    cfg = _challenger_cfg()
    assert cfg.OPTIC.league_id == "atp_challenger"
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.optic_league_id == "atp_challenger"


def test_classified_as_tennis():
    assert sport_for_league("atp_challenger") == Sport.TENNIS
    assert _challenger_cfg().sport == Sport.TENNIS


def test_fetchable_and_uses_the_tennis_subscription_secret():
    from fetch.tip import optic_api_key_secret

    tennis_secret = "opticodds_parlay_tennis_access_key"
    assert optic_api_key_secret("atp_challenger") == tennis_secret
    assert optic_api_key_secret("atp") == tennis_secret


def test_shares_the_atp_slug_prefix_with_the_main_tour():
    challenger = _challenger_cfg()
    atp = _atp_cfg()
    assert challenger.POLYMARKET is not None and atp.POLYMARKET is not None
    assert challenger.POLYMARKET.slug_prefix == "atp"
    assert challenger.POLYMARKET.slug_prefix == atp.POLYMARKET.slug_prefix
    assert challenger.POLYMARKET.optic_league_id != atp.POLYMARKET.optic_league_id


def test_reuses_atp_market_taxonomy_verbatim():
    cfg = _challenger_cfg()
    assert cfg.POLYMARKET is not None and cfg.OPTIC is not None
    assert cfg.POLYMARKET.market_types == pm.TENNIS_MARKET_TYPES
    assert cfg.POLYMARKET.market_rules is pm.tennis_market_rules
    assert cfg.POLYMARKET.question_style == "tennis_prefix"
    assert cfg.OPTIC.table_types == dict(TENNIS_OPTIC_TABLE_TYPES)
    for market_id, mt in (
        ("moneyline", MarketType.MONEYLINE),
        ("set_handicap", MarketType.SET_HANDICAP),
        ("total_sets", MarketType.TOTAL_SETS),
        ("total_games", MarketType.MATCH_TOTAL_GAMES),
    ):
        assert cfg.OPTIC.table_types[market_id] == mt


def test_exchange_feed_wiring():
    cfg = _challenger_cfg()
    crypto = cfg.CRYPTO
    assert KalshiConfig(sport=Sport.TENNIS) == cfg.KALSHI
    assert cfg.PX is None
    assert crypto is not None
    assert crypto.league == "ATP Challenger"
    assert crypto.also_leagues == ("ATP",)
    assert crypto.symbol_prefix == "TENNIS"
    assert crypto.contract_types == {"Moneyline": MarketType.MONEYLINE}
    assert cfg.POLYMARKET is not None
    assert cfg.OPTIC is not None


def test_crypto_meta_league_maps_challenger_to_atp_challenger():
    cfg = _challenger_cfg()
    assert cfg.OPTIC.league_id == "atp_challenger"
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.league == "ATP Challenger"


