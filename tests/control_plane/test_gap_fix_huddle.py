"""Huddle league pin helpers and dry-run blockers."""

from __future__ import annotations

from mappers.control_plane.dry_run_league import thin_dry_run_league
from mappers.control_plane.gap_fix_huddle_leagues import (
    enable_huddle_pin,
    huddle_competition_id,
)
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.seed.tip_factories import apply_tip_exchange_settings, build_tip_league
from mappers.vocab.football_huddle import NFL_COMPETITION_ID

_CID = NFL_COMPETITION_ID


def _nfl_row(*, with_huddle: bool = False) -> LeagueRow:
    exchanges = [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
        },
    ]
    if with_huddle:
        exchanges.append({
            "sportsbook": "huddle",
            "enabled": True,
            "parser_profile": "huddle_nfl_v1",
            "source_league_id": _CID,
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


def test_dry_run_blocks_huddle_without_competition_id() -> None:
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        exchanges=[
            ExchangePin(
                sportsbook="huddle",
                enabled=True,
                parser_profile="huddle_nfl_v1",
            ),
        ],
    )
    blockers = thin_dry_run_league([], payload)["blockers"]
    assert any("competition_id" in b for b in blockers)


def test_enable_huddle_pin_adds_exchange() -> None:
    row = _nfl_row()
    payload = enable_huddle_pin(row)
    books = {ex["sportsbook"]: ex for ex in payload["exchanges"]}
    assert books["huddle"]["enabled"] is True
    assert books["huddle"]["source_league_id"] == _CID
    assert huddle_competition_id(_nfl_row(with_huddle=True)) == _CID


def test_apply_tip_overlays_huddle_competition_id() -> None:
    row = _nfl_row(with_huddle=True)
    cfg = apply_tip_exchange_settings(build_tip_league(row), row)
    assert cfg.HUDDLE is not None
    assert cfg.HUDDLE.competition_ids == (_CID,)
