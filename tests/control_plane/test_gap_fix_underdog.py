"""Underdog league pin helpers."""

from __future__ import annotations

import pytest

from mappers.control_plane.gap_fix_underdog_leagues import (
    enable_underdog_pin,
    underdog_venue_token,
    venue_token_for_slug,
)
from mappers.control_plane.rows import LeagueRow


def _row(*, with_underdog: bool = False, token: str = "NFL") -> LeagueRow:
    exchanges = [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
        },
    ]
    if with_underdog:
        exchanges.append({
            "sportsbook": "underdog",
            "enabled": True,
            "parser_profile": "underdog_generic_v1",
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


def test_enable_underdog_pin_adds_exchange() -> None:
    payload = enable_underdog_pin(_row())
    books = {ex["sportsbook"]: ex for ex in payload["exchanges"]}
    assert books["underdog"]["enabled"] is True
    assert books["underdog"]["source_league_id"] == "NFL"
    assert underdog_venue_token(_row(with_underdog=True)) == "NFL"


# Tip slugs + Optic league ids as they stand on the activated prod tip P_baf456fa1a0e (2026-09-29).
@pytest.mark.parametrize(
    ("slug", "optic_league_id", "token"),
    [
        ("international_friendlies", "international_-_friendlies", "FIFA"),
        ("brazil_serie_a", "brazil_-_serie_a", "BRASILA"),
        ("saudi_pro_league", "saudi_arabia_-_saudi_league", "SAUDIPRO"),
        ("argentina_primera_nacional", "argentina_-_primera_nacional", "ARGNAC"),
        ("nhl", "nhl", "NHL"),
    ],
)
def test_new_underdog_leagues_have_a_venue_token(slug: str, optic_league_id: str, token: str) -> None:
    """harvest_underdog_gaps only drafts leagues venue_token_for_slug knows."""
    assert venue_token_for_slug(slug) == token
    assert venue_token_for_slug("renamed_slug", optic_league_id) == token


def test_club_friendlies_are_not_the_national_team_friendlies() -> None:
    """UDXFIFA lists national teams; the club-friendlies tip league must not inherit the token."""
    assert venue_token_for_slug("international_club_friendlies", "international_-_club_friendlies") is None
