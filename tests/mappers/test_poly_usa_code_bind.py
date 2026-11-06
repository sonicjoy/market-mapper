"""Gateway team abbreviations unique-bind onto Optic names (ryagan → Ryan Gandra)."""

from __future__ import annotations

from datetime import UTC, datetime

from mappers.poly_usa_code_bind import (
    day_overlaps_hours,
    orient_codes,
    unique_code_side,
    within_hours,
)

_START = "2026-09-19T23:00:00Z"


def test_unique_code_side_binds_name_tokens_when_abbr_differs() -> None:
    args = ("RGY9", "ODZ", "Ryan Gandra", "Ozzy Diaz")
    assert unique_code_side("ryagan", *args) == "home"
    assert unique_code_side("ozzdia", *args) == "away"
    assert unique_code_side("zzz", *args) == ""


def test_orient_codes_same_and_flip() -> None:
    args = ("RGY9", "ODZ", "Ryan Gandra", "Ozzy Diaz")
    assert orient_codes("ryagan", "ozzdia", *args) == "same"
    assert orient_codes("ozzdia", "ryagan", *args) == "flip"
    assert orient_codes("ryagan", "ryagan", *args) == ""


def test_day_overlaps_hours_covers_event_date() -> None:
    now = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)
    assert within_hours(_START, now, 24) is True
    assert within_hours("2026-09-25T00:00:00Z", now, 24) is False
    assert day_overlaps_hours("2026-09-19", now, 24) is True
    assert day_overlaps_hours("2026-09-25", now, 24) is False
