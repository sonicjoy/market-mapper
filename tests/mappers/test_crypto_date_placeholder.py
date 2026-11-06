"""Crypto date-only EVENT_DATE unique-binds Optic pairs across placeholder stamps."""

from __future__ import annotations

from mappers.exchanges.optic import Fixture
from mappers.pipeline import (
    ScheduleEntry,
    _crypto_schedule_entries,
)
from mappers.shared import MatchKey, is_crypto_date_placeholder, is_et_midnight


def _entry(date: str, home: str, away: str, *, utc: str) -> ScheduleEntry:
    return ScheduleEntry(Fixture(
        fixture_id=f"{home}-{away}",
        game_id=f"g-{home}-{away}",
        sportradar_id=None,
        start_et=f"{date}T15:00:00",
        start_date=utc,
        home=home,
        away=away,
        home_name=home,
        away_name=away,
        team_map={},
        odds=[],
        is_live=False,
    ))


def test_et_midnight_detects_eastern_midnight_only() -> None:
    assert is_et_midnight("2026-09-13T04:00:00+00:00")
    assert is_et_midnight("2026-01-15T05:00:00+00:00")
    assert not is_et_midnight("2026-01-15T04:00:00+00:00")
    assert not is_et_midnight("2026-09-11T19:00:00+00:00")
    assert not is_et_midnight("2026-09-13T04:00:00")


def test_crypto_placeholder_includes_fixed_utc_four_am() -> None:
    assert is_crypto_date_placeholder("2026-09-13T04:00:00+00:00")
    assert is_crypto_date_placeholder("2026-01-15T04:00:00+00:00")
    assert is_crypto_date_placeholder("2026-01-15T05:00:00+00:00")
    assert not is_crypto_date_placeholder("2026-09-11T19:00:00+00:00")
    assert not is_crypto_date_placeholder("2026-09-13T16:30:00+00:00")


def test_placeholder_binds_unique_other_day_pair() -> None:
    friday = _entry(
        "2026-09-11", "SEV", "VAL", utc="2026-09-11T19:00:00Z",
    )
    index = {MatchKey("2026-09-11", "SEV", "VAL"): [friday]}
    hit = _crypto_schedule_entries(
        index, "SEV", "VAL", "2026-09-13T04:00:00+00:00",
    )
    assert hit is not None
    entries, flipped = hit
    assert entries == [friday]
    assert flipped is False


def test_placeholder_fails_closed_on_two_meetings() -> None:
    a = _entry("2026-09-11", "SEV", "VAL", utc="2026-09-11T19:00:00Z")
    b = _entry("2026-09-20", "SEV", "VAL", utc="2026-09-20T19:00:00Z")
    index = {
        MatchKey("2026-09-11", "SEV", "VAL"): [a],
        MatchKey("2026-09-20", "SEV", "VAL"): [b],
    }
    assert _crypto_schedule_entries(
        index, "SEV", "VAL", "2026-09-13T04:00:00+00:00",
    ) is None


def test_real_kickoff_does_not_cross_dates() -> None:
    friday = _entry(
        "2026-09-11", "SEV", "VAL", utc="2026-09-11T19:00:00Z",
    )
    index = {MatchKey("2026-09-11", "SEV", "VAL"): [friday]}
    assert _crypto_schedule_entries(
        index, "SEV", "VAL", "2026-09-13T16:30:00+00:00",
    ) is None


def test_winter_utc_four_am_stamp_binds_unique_pair() -> None:
    meeting = _entry(
        "2026-01-14", "SEV", "VAL", utc="2026-01-15T01:00:00Z",
    )
    index = {MatchKey("2026-01-14", "SEV", "VAL"): [meeting]}
    hit = _crypto_schedule_entries(
        index, "SEV", "VAL", "2026-01-15T04:00:00+00:00",
    )
    assert hit is not None
    assert hit[0] == [meeting]


def test_exact_et_date_still_wins() -> None:
    sunday = _entry(
        "2026-09-13", "GET", "DEP", utc="2026-09-13T16:30:00Z",
    )
    index = {MatchKey("2026-09-13", "GET", "DEP"): [sunday]}
    hit = _crypto_schedule_entries(
        index, "GET", "DEP", "2026-09-13T16:30:00+00:00",
    )
    assert hit is not None
    assert hit[0] == [sunday]
    assert hit[1] is False
