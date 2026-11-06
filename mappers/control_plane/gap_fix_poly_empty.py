"""Harvest Polymarket US codes for close fixtures when RFQ inventory is empty.

Gap-propose's RFQ walk only sees UNMAPPED leftovers in a 3h window, so UFC
``ryagan`` / tennis ``jsinxx`` never draft while the card is still
horizon-blocked. This sweeper walks every wired US inner for kickoffs
inside ``CLOSE_HOURS`` (24h) and reuses ``harvest_poly_side``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.gap_fix_optic_empty import _league_games
from mappers.control_plane.gap_fix_poly import harvest_poly_side
from mappers.control_plane.gap_fix_poly_bq import (
    OpticRowsFn,
    UsEventsFn,
    fetch_close_us_events,
    optic_rows_from_cache,
)
from mappers.control_plane.gap_fix_slots import PinSlots
from mappers.control_plane.gap_inventory import MAX_EVENTS
from mappers.control_plane.pipeline_gap_memory import cgroup_memory_ratio
from mappers.control_plane.poly_us_match import best_fixture, shift_day
from mappers.poly_usa_code_bind import within_hours
from mappers.seed.poly_usa_exchange import us_league_code

logger = logging.getLogger(__name__)

CLOSE_HOURS = 24
_COMBAT_INNERS = frozenset({"ufc", "mma", "boxing"})
FixturesFn = Callable[..., list[dict[str, Any]]]


def harvest_missing_poly_usa_codes(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    us_events_fn: UsEventsFn | None = None,
    optic_rows_fn: OpticRowsFn | None = None,
    fixtures_fn: FixturesFn | None = None,
    now: datetime | None = None,
) -> None:
    """Draft Poly US codes for close Optic sides missing from the tip."""
    if us_events_fn is None and fixtures_fn is not None:
        return
    before = len(pins)
    clock = now or datetime.now(tz=UTC)
    try:
        stats = _harvest(
            store, pins, skipped, seen, us_events_fn, optic_rows_fn, fixtures_fn, clock,
        )
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest poly_usa_close failed")
        skipped.append({"book": "poly_usa_close", "reason": f"harvest_error:{exc}"[:160]})
        return
    if stats is not None:
        _log_poly_usa_close(
            phase="done",
            events=stats["events"],
            close=stats["close"],
            pins=len(pins) - before,
        )


def _log_poly_usa_close(**fields: Any) -> None:
    """Phase log for poly_usa_close (start before BQ, loaded after, done at exit)."""
    ratio = cgroup_memory_ratio()
    if ratio is not None:
        fields = {**fields, "mem_pct": f"{ratio * 100:.0f}"}
    extra = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("pipeline gap-fix stage=probe book=poly_usa_close %s", extra)


def _harvest(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    us_events_fn: UsEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    fixtures_fn: FixturesFn | None,
    now: datetime,
) -> dict[str, int] | None:
    """Load close US events and draft unique-bind aliases."""
    prefixes = _wired_prefixes(store)
    if not prefixes:
        return None
    _log_poly_usa_close(phase="start", inners=len(prefixes))
    events, optic_rows = _load(
        store, prefixes, us_events_fn, optic_rows_fn, fixtures_fn,
    )
    events = _events_within_day_window(events, now)
    _log_poly_usa_close(
        phase="loaded",
        events=len(events),
        optic_rows=len(optic_rows),
    )
    by_inner = _fixtures_by_inner(store, prefixes, optic_rows)
    close = [
        row for row in events
        if _event_is_close(
            row,
            by_inner.get(str(row.get("inner") or "").casefold(), []),
            now,
        )
    ]
    if not close:
        return {"events": len(events), "close": 0}
    inners = _ordered_prefixes({str(row.get("inner") or "").casefold() for row in close})
    extra, extra_skip = harvest_poly_side(
        store, inners, close, optic_rows, official_events=[],
        slots=PinSlots(limit=MAX_EVENTS), persist_ttl=False,
    )
    skipped.extend(extra_skip)
    _absorb(pins, seen, extra)
    return {"events": len(events), "close": len(close)}


def _wired_prefixes(store: Any) -> list[str]:
    """Enabled polymarket_usa inner codes on the tip, combat first."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    codes: set[str] = set()
    for row in store.leagues_for(rid):
        if not row.enabled or row.tombstone:
            continue
        code = us_league_code(row).casefold()
        if code:
            codes.add(code)
    return _ordered_prefixes(codes)


def _ordered_prefixes(codes: set[str]) -> list[str]:
    """Combat inners first so UFC is not crowded out."""
    return sorted(
        (code for code in codes if code),
        key=lambda code: (0 if code in _COMBAT_INNERS else 1, code),
    )


def _load(
    store: Any,
    prefixes: Sequence[str],
    us_events_fn: UsEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    fixtures_fn: FixturesFn | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Injected events/rows, else BQ close RFQ events + warmed Optic cache."""
    events = (
        us_events_fn()
        if us_events_fn is not None
        else fetch_close_us_events(list(prefixes))
    )
    if optic_rows_fn is not None:
        return events, optic_rows_fn()
    stubbed = _optic_rows_from_fixtures(store, prefixes, fixtures_fn)
    if stubbed is not None:
        return events, stubbed
    return events, optic_rows_from_cache(store, prefixes)


def _events_within_day_window(
    events: list[dict[str, Any]], now: datetime,
) -> list[dict[str, Any]]:
    """Drop far-future events before the Optic join."""
    return [
        row for row in events
        if _event_day_within_prefilter(str(row.get("date") or ""), now)
    ]


def _optic_rows_from_fixtures(
    store: Any,
    prefixes: Sequence[str],
    fixtures_fn: FixturesFn | None,
) -> list[dict[str, Any]] | None:
    """Harvest stub optic rows from ``fixtures_fn`` when injected."""
    if fixtures_fn is None:
        return None
    wanted = {str(p).casefold() for p in prefixes if p}
    rows: list[dict[str, Any]] = []
    optic_ids: set[str] = set()
    for lg in _tip_leagues(store):
        code = us_league_code(lg).casefold()
        if code not in wanted:
            continue
        rows.extend(_league_games(lg, fixtures_fn))
        oid = str(lg.optic_league_id or "").strip()
        if oid:
            optic_ids.add(oid)
        optic_ids.update(
            str(x).strip() for x in (lg.extra_optic_league_ids or []) if str(x).strip()
        )
    if rows:
        return rows
    flat: list[dict[str, Any]] = []
    for oid in optic_ids:
        for row in fixtures_fn(oid, horizon_hours=96.0):
            if str(row.get("optic_league_id") or "") in optic_ids:
                flat.append(row)
    return flat


def _optic_row_league_id(row: dict[str, Any]) -> str:
    """Top-level optic_league_id, else nested ``league.id`` from cache/http shape."""
    top = str(row.get("optic_league_id") or "").strip()
    if top:
        return top
    league = row.get("league") or {}
    if isinstance(league, dict):
        return str(league.get("id") or "").strip()
    return str(league).strip()


def _fixtures_by_inner(
    store: Any,
    prefixes: Sequence[str],
    optic_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Optic fixtures grouped by Poly US inner — avoids O(events × all fixtures)."""
    wanted = {str(p).casefold() for p in prefixes if p}
    oid_to_inner: dict[str, str] = {}
    for lg in _tip_leagues(store):
        code = us_league_code(lg).casefold()
        if code not in wanted:
            continue
        oid = str(lg.optic_league_id or "").strip()
        if oid:
            oid_to_inner[oid] = code
        oid_to_inner.update(
            {
                str(extra).strip(): code
                for extra in (lg.extra_optic_league_ids or [])
                if str(extra).strip()
            },
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in optic_rows:
        oid = _optic_row_league_id(row)
        inner = oid_to_inner.get(oid)
        if not inner:
            continue
        if oid and not str(row.get("optic_league_id") or "").strip():
            row["optic_league_id"] = oid
        grouped[inner].append(row)
    return dict(grouped)


def _tip_leagues(store: Any) -> list[Any]:
    """Enabled tip leagues."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    return [row for row in store.leagues_for(rid) if row.enabled and not row.tombstone]


def _event_is_close(
    event: dict[str, Any],
    optic_rows: list[dict[str, Any]],
    now: datetime,
) -> bool:
    """True when Optic kickoff or event date sits inside CLOSE_HOURS."""
    hit = best_fixture(event, optic_rows)
    start = str((hit or {}).get("fx", {}).get("start_date") or "")
    if start:
        return within_hours(start, now, CLOSE_HOURS)
    return _event_day_is_close(str(event.get("date") or ""), now)


def _event_day_within_prefilter(day: str, now: datetime) -> bool:
    """Event date ±2 calendar days; looser than the 24h close gate."""
    text = (day or "")[:10]
    if not text:
        return False
    today = now.astimezone(UTC).date().isoformat()
    window = {shift_day(today, delta) for delta in range(-2, 3)}
    window.discard("")
    return text in window


def _event_day_is_close(day: str, now: datetime) -> bool:
    """Event YYYY-MM-DD within ±1 calendar day of ``now`` when Optic kickoff is unknown."""
    text = (day or "")[:10]
    if not text:
        return False
    today = now.astimezone(UTC).date().isoformat()
    return text in {today, shift_day(today, -1), shift_day(today, 1)}


def _absorb(
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    extra: list[dict[str, Any]],
) -> None:
    """Append newly drafted pins that the parent harvest has not seen."""
    for pin in extra:
        ident = _ident(pin)
        if ident is None or ident in seen:
            continue
        seen.add(ident)
        pins.append(pin)


def _ident(pin: dict[str, Any]) -> tuple[str, str, str] | None:
    """Dedupe key matching gap_fix._pin_identity for aliases and league pins."""
    if str(pin.get("kind") or "") == "mapping_league":
        slug = str(pin.get("league") or "")
        return ("mapping_league", slug, str(pin.get("optic_league_id") or "")) if slug else None
    aliases = pin.get("aliases") or []
    if not aliases:
        return None
    return (
        str(pin.get("league") or ""),
        str(pin.get("canonical_key") or ""),
        str(aliases[0].get("alias_value") or ""),
    )
