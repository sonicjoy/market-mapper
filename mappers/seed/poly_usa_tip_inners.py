"""Enabled Polymarket US inner codes from the activated mapping tip."""

from __future__ import annotations

from typing import Any

from mappers.seed.poly_usa_exchange import (
    POLY_USA_BOOK,
    exchange_enabled,
    find_exchange,
    us_league_code,
)


def enabled_us_inners_from_tip(leagues: list[Any]) -> list[str]:
    """Distinct ``slug_prefix`` / ``source_league_id`` for enabled USA pins."""
    codes: set[str] = set()
    for row in leagues:
        if getattr(row, "tombstone", False) or not getattr(row, "enabled", True):
            continue
        usa = find_exchange(getattr(row, "exchanges", None) or [], POLY_USA_BOOK)
        if usa is None or not exchange_enabled(usa):
            continue
        code = us_league_code(row).strip().casefold()
        if code:
            codes.add(code)
    return sorted(codes)
