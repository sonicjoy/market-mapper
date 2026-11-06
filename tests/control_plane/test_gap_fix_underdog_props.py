"""Unmapped Underdog props are Optic supply, not parser gaps (alerts 2026-11-03)."""

from __future__ import annotations

import pytest

from mappers.control_plane import gap_fix_underdog_rfq as rfq
from mappers.control_plane.gap_ledger import _residual
from mappers.control_plane.rows import LeagueRow


@pytest.fixture(autouse=True)
def _no_optic_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rfq, "cached_optic_fixtures", lambda _league: [])


def _reason(key: str, venue: str, product: str, slug: str) -> str:
    skipped: list[dict[str, str]] = []
    rows = [
        LeagueRow(
            league=slug,
            sport="",
            optic_league_id=slug.upper(),
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=72.0,
            enabled=True,
            output_order=[],
            exchanges=[],
        )
    ]
    rfq._pin_matchup(slug, venue, product, "", key, rows, [], [], skipped)
    assert len(skipped) == 1
    return skipped[0]["reason"]


@pytest.mark.parametrize(
    ("key", "venue", "product", "slug"),
    [
        ("UDXNFLRUSHRECYDS_NYJKC26NOV08_KCEMMJOHNSO34.5", "NFL", "RUSHRECYDS", "nfl"),
        ("UDXNBAPRA_ATLWAS26NOV04_WASTRAYOUNG34.5", "NBA", "PRA", "nba"),
        ("UDXNBAPRA_ATLWAS26NOV04_ATLONYOKONGW19.5", "NBA", "PRA", "nba"),
        ("UDXNBAPRA_MILBOS26NOV04_MILMYLTURNER16.5", "NBA", "PRA", "nba"),
    ],
)
def test_alerted_props_are_supply_not_needs_code(key: str, venue: str, product: str, slug: str) -> None:
    reason = _reason(key, venue, product, slug)
    assert reason == rfq.PROP_SUPPLY
    assert _residual(reason)


def test_unknown_team_market_still_needs_code() -> None:
    reason = _reason("UDXNBAWINMARGIN_ATLWAS26NOV04_O5.5", "NBA", "WINMARGIN", "nba")
    assert reason == "needs_code"


def test_known_market_without_teams_stays_missing_optic() -> None:
    reason = _reason("UDXNBATOTAL_ATLWAS26NOV04_O225.5", "NBA", "TOTAL", "nba")
    assert reason == "missing_optic"
