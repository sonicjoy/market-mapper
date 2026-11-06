"""DKEX league pin helpers."""

from __future__ import annotations

from mappers.control_plane.gap_fix_dkex_leagues import (
    dkex_venue_token,
    enable_dkex_pin,
    venue_token_for_slug,
)
from mappers.control_plane.rows import LeagueRow


def _row(*, with_dkex: bool = False, token: str = "NFL") -> LeagueRow:
    exchanges = [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
        },
    ]
    if with_dkex:
        exchanges.append({
            "sportsbook": "dkex",
            "enabled": True,
            "parser_profile": "dkex_generic_v1",
            "source_league_id": token,
            "settings": {"league": token},
        })
    return LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=exchanges,
    )


def test_enable_dkex_pin_adds_exchange() -> None:
    payload = enable_dkex_pin(_row())
    books = {ex["sportsbook"]: ex for ex in payload["exchanges"]}
    assert books["dkex"]["enabled"] is True
    assert books["dkex"]["source_league_id"] == "NFL"
    assert dkex_venue_token(_row(with_dkex=True)) == "NFL"


def test_ncaaf_maps_to_cfb_token() -> None:
    row = LeagueRow(
        league="ncaaf",
        sport="football",
        optic_league_id="ncaaf",
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=[{"sportsbook": "optic", "enabled": True, "parser_profile": "optic_standard_v1"}],
    )
    payload = enable_dkex_pin(row)
    books = {ex["sportsbook"]: ex for ex in payload["exchanges"]}
    assert books["dkex"]["source_league_id"] == "CFB"
    assert venue_token_for_slug("ncaaf") == "CFB"
