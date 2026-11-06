"""Polymarket US as its own tip exchange pin."""

from __future__ import annotations

from typing import Any

import pytest

from mappers.control_plane.dry_run_league import thin_dry_run_league
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.store import LeagueRow
from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.market_types import MarketType
from mappers.profiles.registry import POLY_USA_PROFILE_ID, lookup_profile
from mappers.profiles.types import LeagueBuildContext
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK, us_league_code
from mappers.seed.tip_exchange_build import build_tip_exchange_configs
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport
from mappers.vocab.poly_usa_console import SMT_RULE_KEY_TYPE, wired_canonical
from mappers.vocab.poly_usa_smt import smt_spec
from scripts.submit_poly_us_cards import build_payload
from scripts.submit_poly_us_inner_code_pins import (
    PIN_FIXES,
)
from scripts.submit_poly_us_inner_code_pins import (
    build_payload as build_inner_code_payload,
)


def _exchanges(us_code: str = "spl") -> list[dict[str, Any]]:
    return [
        {
            "sportsbook": "polymarket",
            "enabled": True,
            "parser_profile": "poly_generic_v1",
            "settings": {"slug_prefix": "epl"},
        },
        {
            "sportsbook": POLY_USA_BOOK,
            "enabled": True,
            "parser_profile": POLY_USA_PROFILE_ID,
            "source_league_id": us_code,
        },
    ]


def _league_row(
    league: str = "epl", sport: str = "soccer", optic: str = "england_-_premier_league",
) -> LeagueRow:
    return LeagueRow(
        league=league,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=_exchanges(),
    )


def test_poly_usa_profile_registered_for_every_poly_sport() -> None:
    for sport in (Sport.SOCCER, Sport.FOOTBALL, Sport.BASEBALL, Sport.MMA):
        profile = lookup_profile(POLY_USA_PROFILE_ID, sport)
        assert profile is not None, sport
        assert profile.sportsbook == POLY_USA_BOOK


def test_dry_run_accepts_polymarket_usa_pin() -> None:
    payload = MappingLeaguePayload(
        league="epl",
        sport="soccer",
        optic_league_id="epl",
        exchanges=[
            ExchangePin(
                sportsbook=POLY_USA_BOOK,
                enabled=True,
                parser_profile=POLY_USA_PROFILE_ID,
                source_league_id="spl",
            ),
        ],
    )
    assert thin_dry_run_league([], payload)["blockers"] == []


def test_dry_run_blocks_polymarket_usa_without_league_code() -> None:
    payload = MappingLeaguePayload(
        league="epl",
        sport="soccer",
        optic_league_id="epl",
        exchanges=[
            ExchangePin(
                sportsbook=POLY_USA_BOOK,
                enabled=True,
                parser_profile=POLY_USA_PROFILE_ID,
            ),
        ],
    )
    blockers = thin_dry_run_league([], payload)["blockers"]
    assert any("inner US league code" in b for b in blockers)


def test_poly_usa_league_ids_come_from_code_not_the_tip_pin() -> None:
    # The tip pin names "spl" (Saudi Pro League); code says EPL is gateway
    # league 9, and the pin is ignored.
    cfg = resolve_run_leagues({}, [_league_row()])["epl"]
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "epl"
    assert PolyUsaConfig(league_ids=frozenset({9})) == cfg.POLYMARKET_USA
    # Unrelated to Polymarket: the US config carries no Polymarket vocabulary.
    assert not hasattr(cfg.POLYMARKET_USA, "market_types")


def test_one_optic_league_reads_every_girone() -> None:
    row = _league_row(league="italy_serie_c", optic="italy_-_serie_c")
    cfg = resolve_run_leagues({}, [row])["italy_serie_c"]
    assert PolyUsaConfig(league_ids=frozenset({306, 307, 308})) == cfg.POLYMARKET_USA


def test_league_code_does_not_list_maps_no_poly_usa() -> None:
    row = _league_row(league="nowhere", optic="no_such_optic_league")
    assert resolve_run_leagues({}, [row])["nowhere"].POLYMARKET_USA is None


def test_tip_pin_builds_no_config() -> None:
    row = _league_row(league="ncaaf", sport="football", optic="ncaaf")
    row.exchanges = [_exchanges("cfb")[1]]
    ctx = LeagueBuildContext("ncaaf", Sport.FOOTBALL, "ncaaf", 96.0, ())
    _, _, _, _, poly, poly_usa, _, _, _, _, _ = build_tip_exchange_configs(row, ctx)
    assert poly is None
    assert poly_usa is None


def test_us_league_code_reads_the_usa_pin() -> None:
    assert us_league_code(_league_row()) == "spl"


def test_migration_moves_legacy_prefix_to_its_own_pin() -> None:
    row = _league_row(league="leagues_cup")
    row.exchanges = [
        {
            "sportsbook": "polymarket",
            "enabled": True,
            "parser_profile": "poly_generic_v1",
            "settings": {"slug_prefix": "lc", "us_slug_prefix": "lgscup"},
        },
    ]
    league = build_payload([row]).leagues[0]
    poly = next(ex for ex in league.exchanges if ex.sportsbook == "polymarket")
    usa = next(ex for ex in league.exchanges if ex.sportsbook == POLY_USA_BOOK)
    assert "us_slug_prefix" not in poly.settings
    assert poly.settings["slug_prefix"] == "lc"
    assert usa.source_league_id == "lgscup"
    assert usa.settings["slug_prefix"] == "lgscup"
    assert usa.enabled is True


def test_migration_covers_league_without_official_polymarket_pin() -> None:
    row = _league_row(league="ncaaf", sport="football")
    row.exchanges = [{"sportsbook": "kalshi", "enabled": True, "parser_profile": "kalshi_generic_v1"}]
    league = build_payload([row]).leagues[0]
    usa = next(ex for ex in league.exchanges if ex.sportsbook == POLY_USA_BOOK)
    assert usa.source_league_id == "cfb"


def test_migration_is_idempotent() -> None:
    row = _league_row()
    with pytest.raises(RuntimeError, match="already has polymarket_usa"):
        build_payload([row])


def test_inner_code_pin_fix_rewrites_live_codes() -> None:
    rows: list[LeagueRow] = []
    stale = {league: f"old-{code}" for league, code in PIN_FIXES.items()}
    for league, current in stale.items():
        row = _league_row(league=league)
        row.exchanges = [
            {
                "sportsbook": POLY_USA_BOOK,
                "enabled": True,
                "parser_profile": POLY_USA_PROFILE_ID,
                "source_league_id": current,
                "settings": {"slug_prefix": current},
            },
        ]
        rows.append(row)
    payload = build_inner_code_payload(rows)
    assert {lg.league for lg in payload.leagues} == set(PIN_FIXES)
    for lg in payload.leagues:
        usa = next(ex for ex in lg.exchanges if ex.sportsbook == POLY_USA_BOOK)
        assert usa.source_league_id == PIN_FIXES[lg.league]
        assert usa.settings["slug_prefix"] == PIN_FIXES[lg.league]


def test_inner_code_pin_fix_is_idempotent() -> None:
    league, code = next(iter(PIN_FIXES.items()))
    row = _league_row(league=league)
    row.exchanges = [
        {
            "sportsbook": POLY_USA_BOOK,
            "enabled": True,
            "parser_profile": POLY_USA_PROFILE_ID,
            "source_league_id": code,
            "settings": {"slug_prefix": code},
        },
    ]
    with pytest.raises(RuntimeError, match="no inner-code pin"):
        build_inner_code_payload([row])


def test_tip_sports_market_type_rows_never_change_the_enum_table() -> None:
    cfg = resolve_run_leagues({}, [_league_row()])["epl"]
    assert smt_spec("soccer_game_btts") == (MarketType.BTTS, "game_yn")
    assert wired_canonical(cfg, "soccer_game_btts") == MarketType.BTTS.value
    assert wired_canonical(cfg, "not_a_real_enum") is None
    assert SMT_RULE_KEY_TYPE == "sports_market_type"
