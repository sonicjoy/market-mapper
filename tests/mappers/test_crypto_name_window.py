"""Crypto tennis stamped hours early binds by exact names inside a window."""

from __future__ import annotations

from mappers.crypto_name_window import name_window_entries
from mappers.exchanges.optic import Fixture
from mappers.pipeline import ScheduleEntry
from mappers.shared import MatchKey


def _entry(home: str, away: str, utc: str) -> ScheduleEntry:
    return ScheduleEntry(Fixture(
        fixture_id=utc, game_id=utc, sportradar_id=None,
        start_et="2026-10-19T03:30:00", start_date=utc,
        home="h", away="a", home_name=home, away_name=away,
        team_map={}, odds=[], is_live=False,
    ))


def _index(*entries: ScheduleEntry) -> dict:
    return {MatchKey("2026-10-19", f"h{i}", "a"): [e] for i, e in enumerate(entries)}


def test_binds_early_stamp_across_et_midnight() -> None:
    e = _entry("James McCabe", "Elias Ymer", "2026-10-19T07:30:00Z")
    hit = name_window_entries(
        _index(e), "James McCabe", "Elias Ymer", "2026-10-19T02:00:00+00:00",
    )
    assert hit == ([e], False)


def test_flipped_orientation() -> None:
    e = _entry("Mert Alkaya", "Andre Ilagan", "2026-10-19T07:15:00Z")
    hit = name_window_entries(
        _index(e), "Andre Ilagan", "Mert Alkaya", "2026-10-19T02:00:00+00:00",
    )
    assert hit == ([e], True)


def test_outside_window_unmapped() -> None:
    e = _entry("James McCabe", "Elias Ymer", "2026-10-19T07:30:00Z")
    assert name_window_entries(
        _index(e), "James McCabe", "Elias Ymer", "2026-10-18T10:00:00+00:00",
    ) is None


def test_two_fixtures_in_window_fail_closed() -> None:
    a = _entry("James McCabe", "Elias Ymer", "2026-10-19T07:30:00Z")
    b = _entry("James McCabe", "Elias Ymer", "2026-10-19T12:30:00Z")
    assert name_window_entries(
        _index(a, b), "James McCabe", "Elias Ymer", "2026-10-19T09:00:00+00:00",
    ) is None


def test_near_name_does_not_bind() -> None:
    e = _entry("James McCabe", "Elias Ymer", "2026-10-19T07:30:00Z")
    assert name_window_entries(
        _index(e), "J McCabe", "Elias Ymer", "2026-10-19T07:30:00+00:00",
    ) is None
