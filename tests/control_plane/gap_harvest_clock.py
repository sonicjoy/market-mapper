"""Freeze harvest calendar day for fixture stubs dated 2026-09-19."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

HARVEST_TODAY = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def freeze_gap_harvest_clock(monkeypatch: Any, *, now: datetime | None = None) -> datetime:
    """Pin gap harvest ``today`` so close-window tests do not drift with the clock."""
    clock = now or HARVEST_TODAY
    import datetime as datetime_mod

    real_datetime = datetime_mod.datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return clock.replace(tzinfo=None)
            base = clock if clock.tzinfo else clock.replace(tzinfo=UTC)
            return base.astimezone(tz)

    for mod in (
        "mappers.control_plane.gap_fix",
        "mappers.control_plane.gap_fix_optic_abbr_codes",
        "mappers.control_plane.gap_fix_crypto_empty",
    ):
        monkeypatch.setattr(f"{mod}.datetime", FrozenDatetime)

    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_optic_empty.dt",
        SimpleNamespace(
            now=lambda tz=None: (
                clock.astimezone(tz)
                if tz is not None and clock.tzinfo
                else clock.replace(tzinfo=tz) if tz is not None else clock.replace(tzinfo=None)
            ),
            fromisoformat=real_datetime.fromisoformat,
        ),
    )
    return clock
