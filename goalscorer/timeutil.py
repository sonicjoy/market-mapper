"""UTC time helpers (one place to patch in tests)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta


def utcnow() -> datetime:
    """Current time, timezone-aware UTC."""
    return datetime.now(UTC)


def day_start(day: date) -> datetime:
    """Midnight UTC at the start of `day`."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def day_window(day: date, days: int = 1) -> tuple[datetime, datetime]:
    """[midnight of `day`, midnight `days` later) in UTC."""
    start = day_start(day)
    return start, start + timedelta(days=days)
