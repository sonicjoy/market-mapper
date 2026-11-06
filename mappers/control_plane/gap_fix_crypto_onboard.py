"""Draft mapping_league when crypto RFQ meta is not on the tip."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import _parse_symbol
from mappers.control_plane.crypto_optic_match import catalogue_sides
from mappers.control_plane.gap_crypto_catalogue import catalogue_lookup
from mappers.control_plane.gap_fix_onboard import gap_onboard_enabled, try_onboard_league_pin
from mappers.control_plane.gap_fix_poly_leagues import sport_for
from mappers.control_plane.gap_optic_discover import discover_optic_league_id
from mappers.control_plane.rows import LeagueRow

_CRYPTO_BOOK = "crypto.com"


def try_crypto_league_onboard(
    store: Any,
    row: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
    fixtures_fn: Any,
    fixtures: dict[str, list[dict[str, Any]]],
) -> bool:
    """Onboard crypto meta_league when catalogue + Optic bind uniquely."""
    if not gap_onboard_enabled():
        return False
    symbol = str(row.get("symbol") or "")
    parsed = _parse_symbol(symbol)
    if parsed is None:
        return False
    meta = str(parsed.get("token") or "").strip().upper()
    if not meta:
        return False
    cat = row.get("catalogue") if isinstance(row.get("catalogue"), dict) else None
    if cat is None:
        cat = catalogue_lookup(symbol)
    if not cat.get("ok"):
        return False
    optic_id = _resolve_optic_id(store, cat, fixtures_fn, rows, fixtures)
    if not optic_id:
        return False
    sport = sport_for(optic_id, rows, fixtures)
    return try_onboard_league_pin(
        store,
        optic_id=optic_id,
        sport=sport,
        source_token=meta,
        book=_CRYPTO_BOOK,
        pins=pins,
        skipped=skipped,
        seen=seen,
        rows=rows,
        fixtures=fixtures,
        gap_key=symbol,
        harvest_book="crypto",
    )


def _resolve_optic_id(
    _store: Any,
    cat: dict[str, Any],
    _fixtures_fn: Any,
    _rows: list[LeagueRow],
    _fixtures: dict[str, list[dict[str, Any]]],
) -> str | None:
    """Unique Optic league for catalogue home/away on kickoff day."""
    sides = catalogue_sides(cat)
    if sides is None:
        return None
    day = str(cat.get("meta_event_date") or "")[:10]
    return discover_optic_league_id(cat, sides=sides, day=day)
