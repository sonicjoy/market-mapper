"""Official Polymarket Path 2 harvest (slug_prefix on sportsbook=polymarket)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix_poly_leagues import (
    clone_source,
    enable_official_pin,
    official_slug_prefix,
    onboard_official_pin,
    patch_official_prefix,
    slug_from_optic_id,
    sport_for,
)
from mappers.control_plane.gap_fix_poly_names import draft_official_name_overlays
from mappers.control_plane.gap_harvest_ttl import load_dead_buckets, save_dead_buckets
from mappers.control_plane.poly_us_match import unique_optic_for_questions
from mappers.control_plane.rows import LeagueRow

_POLY_DEAD = "polymarket"


def try_official_prefix(
    store: Any,
    key: str,
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    ctx: dict[str, Any],
) -> bool:
    """Pin official Path 2 when evidence uniquely matches Optic. True if handled."""
    if not events:
        return _already_wired(key, rows) and key in load_dead_buckets(_POLY_DEAD)
    if _already_wired(key, rows):
        return _overlay_wired(store, key, events, rows, pins, ctx)
    optic_id = unique_optic_for_questions(events, ctx["fixtures"])
    if not optic_id:
        skipped.append(_skip(key, "missing_optic"))
        return True
    drafted = ctx.setdefault("drafted_optics", {})
    existing = drafted.get(optic_id)
    if existing is not None:
        patch_official_prefix(existing, key)
        return True
    return _pin_official(store, key, optic_id, rows, pins, skipped, ctx, drafted)


def _overlay_wired(
    store: Any,
    key: str,
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> bool:
    """Name overlays for a wired prefix; TTL skips a 24h ambiguous miss."""
    if key in load_dead_buckets(_POLY_DEAD):
        return True
    skipped: list[dict[str, str]] = ctx.setdefault("skipped", [])
    before_pins, before_skip = len(pins), len(skipped)
    draft_official_name_overlays(store, key, events, rows, pins, ctx)
    if len(pins) == before_pins and any(
        str(row.get("reason") or "") == "name_ambiguous"
        for row in skipped[before_skip:]
    ):
        save_dead_buckets(_POLY_DEAD, {key})
    return True


def _already_wired(key: str, rows: list[LeagueRow]) -> bool:
    """True when some tip league already publishes this official prefix."""
    return any(official_slug_prefix(row).casefold() == key for row in rows)


def _pin_official(
    store: Any,
    key: str,
    optic_id: str,
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    ctx: dict[str, Any],
    drafted: dict[str, dict[str, Any]],
) -> bool:
    """Enable on a unique tip row, or onboard a new league."""
    targets: list[LeagueRow] = ctx["by_optic_id"].get(optic_id) or []
    if len(targets) > 1:
        skipped.append(_skip(key, "optic_league_collision"))
        return True
    if targets:
        return _enable_on_row(key, targets[0], pins, skipped, drafted, optic_id)
    return _onboard(store, key, optic_id, rows, ctx["fixtures"], pins, skipped, drafted)


def _enable_on_row(
    key: str,
    row: LeagueRow,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    drafted: dict[str, dict[str, Any]],
    optic_id: str,
) -> bool:
    """Add official slug_prefix unless a different prefix already occupies the pin."""
    current = official_slug_prefix(row).casefold()
    if current and current != key:
        skipped.append(_skip(key, "wrong_prefix_collision"))
        return True
    pin = enable_official_pin(row, key)
    pins.append(pin)
    drafted[optic_id] = pin
    return True


def _onboard(
    store: Any,
    key: str,
    optic_id: str,
    rows: list[LeagueRow],
    fixtures: dict[str, list[dict[str, Any]]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    drafted: dict[str, dict[str, Any]],
) -> bool:
    """Onboard optic + official Polymarket when the slug is free."""
    slug = slug_from_optic_id(optic_id)
    if not slug:
        skipped.append(_skip(key, "missing_optic"))
        return True
    if slug.casefold() in {r.league.casefold() for r in rows if not r.tombstone}:
        skipped.append(_skip(key, "slug_collision"))
        return True
    sport = sport_for(optic_id, rows, fixtures)
    clone = clone_source(store, sport)
    if not clone:
        skipped.append(_skip(key, "missing_clone_source"))
        return True
    pin = onboard_official_pin(slug, sport, optic_id, key, clone)
    pins.append(pin)
    drafted[optic_id] = pin
    return True


def _skip(key: str, reason: str) -> dict[str, str]:
    return {"book": "polymarket", "key": key, "reason": reason}
