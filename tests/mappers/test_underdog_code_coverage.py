"""Underdog league set and market tables live in code, not on the tip."""

from __future__ import annotations

from mappers.exchanges.underdog import parse_contract
from mappers.exchanges.underdog_pass import soccer_basis_stated
from mappers.market_types import MarketType
from mappers.seed.overlay_taxonomy import overlay_underdog
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport
from mappers.vocab.underdog_markets import (
    MARKETS_BY_SPORT,
    UNDERDOG_LEAGUE_SLUGS,
    market_types_for_sport,
)
from tests.mappers.test_overlay_taxonomy import _map_row
from tests.mappers.test_tip_leagues import _row


def test_leagues_the_tip_never_enabled_map_underdog_from_code() -> None:
    run = resolve_run_leagues({}, [
        _row("ucl", optic="uefa_-_champions_league"),
        _row("wnba", sport="basketball", optic="wnba"),
    ])
    assert run["ucl"].UNDERDOG is not None
    assert run["ucl"].UNDERDOG.market_types["moneyline"] is MarketType.MONEYLINE_3WAY
    assert run["wnba"].UNDERDOG is not None
    assert run["wnba"].UNDERDOG.market_types["player_points"] is MarketType.PLAYER_POINTS


def test_tip_underdog_rules_never_change_the_code_table() -> None:
    run = resolve_run_leagues({}, [_row("ucl", optic="uefa_-_champions_league")])
    cfg = run["ucl"].UNDERDOG
    rule = _map_row(
        league="ucl", sportsbook="underdog", key_type="product_period", key="TOTAL",
        canonical=MarketType.GAME_TOTAL.value,
    )
    assert overlay_underdog(cfg, [rule], run["ucl"]) is cfg


def test_sport_tables_cover_every_sport_a_code_league_can_have() -> None:
    assert len(UNDERDOG_LEAGUE_SLUGS) >= 28
    for sport in (Sport.FOOTBALL, Sport.BASKETBALL, Sport.HOCKEY, Sport.SOCCER, Sport.TENNIS, Sport.MMA):
        assert MARKETS_BY_SPORT.get(sport), sport
        assert market_types_for_sport(sport)


def test_colombia_primera_a_maps_underdog_though_the_tip_pins_none() -> None:
    """UDXDIMAYOR* (2026-10-14): the tip row has no underdog exchange; the code set enables it."""
    run = resolve_run_leagues({}, [_row("colombia_primera_a", optic="colombia_-_primera_a")])
    cfg = run["colombia_primera_a"].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["moneyline"] is MarketType.MONEYLINE_3WAY


def test_ecuador_ligapro_maps_underdog_though_the_tip_pins_none() -> None:
    """UDXECULIGAP* (listed 2026-10-21): GAMEWIN, SPREAD, TOTAL, BTTS on the tip-less ecuador_serie_a."""
    run = resolve_run_leagues({}, [_row("ecuador_serie_a", optic="ecuador_-_serie_a")])
    cfg = run["ecuador_serie_a"].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["moneyline"] is MarketType.MONEYLINE_3WAY
    assert cfg.market_types["asian_handicap"] is MarketType.POINT_SPREAD
    assert cfg.market_types["total_goals"] is MarketType.GAME_TOTAL
    assert cfg.market_types["both_teams_to_score"] is MarketType.BTTS


_J1_GAME = (
    "J1 League match between JEF United Ichihara Chiba and Avispa Fukuoka "
    "originally scheduled for 1:00am ET on November 1, 2026"
)


def _j1(ticker: str, description: str, market_id: str) -> dict:
    return {
        "ticker": ticker,
        "description": description,
        "rules": "",
        "external_ids": {"optic_odds": {"fixture_id": "20261101A38509C4", "market_id": market_id}},
        "expires_at": "2026-11-02T00:00:00.000000Z",
    }


def test_japan_j1_maps_underdog_btts_from_code() -> None:
    """UDXJLEAGUE* (listed 2026-10-30): BTTS and BTTS1H state their period in the sentence."""
    run = resolve_run_leagues({}, [_row("japan_j1_league", optic="japan_-_j1_league")])
    cfg = run["japan_j1_league"].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["both_teams_to_score"] is MarketType.BTTS
    assert cfg.market_types["1st_half_both_teams_to_score"] is MarketType.FIRST_HALF_BTTS
    btts = _j1(
        "UDXJLEAGUEBTTS_AVIJEF26NOV01_BTTS",
        "Resolves Yes if both participating teams record at least 1 goals during the entire game "
        f"excluding extra time of {_J1_GAME}.",
        "both_teams_to_score",
    )
    assert parse_contract(btts) is not None
    assert soccer_basis_stated(MarketType.BTTS, btts["description"], "japan_j1_league")


def test_japan_j1_payment_criterion_contracts_map_nothing() -> None:
    """J1 GAMEWIN / SPREAD / TOTAL say only "according to the filed Payment Criterion" (2026-10-30).

    The spread's strike ("greater than -2.5" on home minus away) reads as JEF +2.5 while its title
    reads "JEF United Ichihara Chiba -2.5?", so the side is not knowable from the listing.
    """
    vague = "Resolves Yes according to the filed Payment Criterion."
    for ticker, market_id in (
        ("UDXJLEAGUEGAMEWIN_AVIJEF26NOV01_AVI", "moneyline"),
        ("UDXJLEAGUESPREAD_AVIJEF26NOV01_JEF2.5", "asian_handicap"),
        ("UDXJLEAGUETOTAL_AVIJEF26NOV01_4.5", "total_goals"),
    ):
        assert parse_contract(_j1(ticker, vague, market_id)) is None, ticker
