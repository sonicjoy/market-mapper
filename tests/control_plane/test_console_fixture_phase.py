"""Fixture phase helpers for Coverage and Unmapped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mappers.control_plane.console_fixture_phase import (
    IN_PLAY_LOOKBACK_HOURS,
    coverage_matches_phase,
    is_complete_status,
    normalize_fixture_phase,
    row_is_open,
    row_matches_phase,
    row_phase_from_optic,
    row_phase_from_ttko,
)


def test_normalize_fixture_phase_defaults_live() -> None:
    assert normalize_fixture_phase(None) == "live"
    assert normalize_fixture_phase("LIVE") == "live"
    assert normalize_fixture_phase("pre") == "pre"


def test_row_phase_from_optic_delayed_is_pre() -> None:
    assert row_phase_from_optic("delayed", ttko_hours=-1.0) == "pre"
    assert row_phase_from_optic("live", ttko_hours=2.0) == "live"
    assert row_phase_from_optic("unplayed", ttko_hours=-1.0) == "pre"


def test_row_is_open_drops_stale_kickoffs() -> None:
    assert row_is_open(None) is True
    assert row_is_open(2.0) is True
    assert row_is_open(-1.0) is True
    assert row_is_open(-(IN_PLAY_LOOKBACK_HOURS + 1)) is False


def test_row_matches_phase_prefers_optic_status() -> None:
    live_row = {"optic_status": "live", "ttko_hours": 4.0}
    pre_row = {"optic_status": "delayed", "ttko_hours": -1.0}
    assert row_matches_phase(live_row, "live") is True
    assert row_matches_phase(live_row, "pre") is False
    assert row_matches_phase(pre_row, "pre") is True
    assert row_matches_phase(pre_row, "live") is False


def test_complete_status_never_matches_either_tab() -> None:
    row = {"optic_status": "completed", "ttko_hours": -1.0}
    assert is_complete_status("completed") is True
    assert row_phase_from_optic("completed", ttko_hours=-1.0) is None
    assert row_matches_phase(row, "live") is False
    assert row_matches_phase(row, "pre") is False


def test_missing_status_falls_back_to_start_time() -> None:
    assert row_phase_from_optic(None, ttko_hours=2.0) == "pre"
    assert row_phase_from_optic("", ttko_hours=-2.0) == "live"
    assert row_phase_from_optic(None, ttko_hours=None) == "pre"


def test_date_only_kickoff_uses_match_day_for_live() -> None:
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    assert row_phase_from_ttko(4.0, kickoff_day=today, date_only=True) == "live"
    assert row_phase_from_ttko(4.0, kickoff_day=tomorrow, date_only=True) == "pre"
    row = {
        "kickoff_date_only": True,
        "kickoff_day": today.isoformat(),
        "ttko_hours": 4.0,
    }
    assert row_matches_phase(row, "live") is True
    assert row_matches_phase(row, "pre") is False


def test_coverage_status_field_does_not_affect_phase() -> None:
    row = {"status": "matched", "ttko_hours": -1.0}
    assert row_matches_phase(row, "live") is True


def test_coverage_matches_phase_status_precedes_start_time() -> None:
    delayed_started = {"optic_status": "delayed", "ttko_hours": -1.0}
    live_upcoming = {"optic_status": "live", "ttko_hours": 2.0}
    missing_status_started = {"ttko_hours": -1.0}
    assert coverage_matches_phase(delayed_started, "pre") is True
    assert coverage_matches_phase(delayed_started, "live") is False
    assert coverage_matches_phase(live_upcoming, "live") is True
    assert coverage_matches_phase(live_upcoming, "pre") is False
    assert coverage_matches_phase(missing_status_started, "live") is True
