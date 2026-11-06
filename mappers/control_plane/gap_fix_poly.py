"""Try-to-fix harvest for Polymarket / Polymarket US RFQ prefixes.

Skip only after an evidence miss. Wired US inners draft entity aliases;
unwired US inners and official Path 2 (slug_prefix on sportsbook=polymarket)
draft a mapping_league pin when Optic is unique.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import fallback_code, is_valid_bare_key
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.evidence_format import usa_alias_refs
from mappers.control_plane.gap_fix_onboard import stamp_gap_harvest_pin
from mappers.control_plane.gap_fix_poly_bq import (
    OfficialEventsFn,
    OpticRowsFn,
    UsEventsFn,
    fetch_optic_window,
    fetch_poly_official_events,
    fetch_poly_us_events,
    persist_us_events_ttl,
)
from mappers.control_plane.gap_fix_poly_leagues import (
    clone_source,
    disable_us_pin,
    enable_us_pin,
    onboard_pin,
    optic_ids_if_all_wired,
    patch_us_code,
    slug_from_optic_id,
    sport_for,
)
from mappers.control_plane.gap_fix_poly_official import try_official_prefix
from mappers.control_plane.gap_fix_slots import PinSlots
from mappers.control_plane.gap_fix_tip import (
    TipLeagueIndex,
    index_tip_leagues,
    indexed_has_optic,
    indexed_has_usa,
    indexed_optic_key,
    indexed_usa_owners,
)
from mappers.control_plane.poly_us_match import best_fixture, unique_optic_for_events
from mappers.control_plane.rows import LeagueRow
from mappers.seed.poly_usa_exchange import (
    NO_OPTIC_US_INNERS,
    POLY_USA_BOOK,
    us_inner_owner_ok,
    us_inner_targets,
    us_league_code,
)

__all__ = [
    "OfficialEventsFn",
    "OpticRowsFn",
    "UsEventsFn",
    "fetch_optic_window",
    "fetch_poly_official_events",
    "fetch_poly_us_events",
    "harvest_poly_side",
    "load_poly_side_inputs",
    "slug_from_optic_id",
]


def harvest_poly_side(
    store: Any,
    prefixes: list[str],
    events: list[dict[str, Any]],
    optic_rows: list[dict[str, Any]],
    official_events: list[dict[str, Any]] | None = None,
    slots: PinSlots | None = None,
    *,
    persist_ttl: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Draft Poly US aliases / official Path 2 pins; skip after a failed try."""
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    rows = _tip_leagues(store)
    ctx = {
        "by_code": _us_code_index(rows),
        "by_optic_id": _optic_index(rows),
        "fixtures": _fixtures_by_optic(optic_rows),
        "claimed": {}, "used": {}, "drafted_optics": {},
        "official": list(official_events or []),
        "seen": seen, "skipped": skipped,
        "tips": index_tip_leagues(store),
    }
    for prefix in prefixes:
        if slots is not None and slots.full():
            break
        key = prefix.strip().casefold()
        before = len(pins)
        _try_prefix(store, key, events, rows, pins, skipped, seen, ctx)
        if slots is not None and len(pins) > before:
            slots.record_pin_event()
    if persist_ttl:
        persist_us_events_ttl(events)
    return pins, skipped


def load_poly_side_inputs(
    prefixes: list[str],
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    store: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """US RFQ events, official-bridge rows, Optic ±10d window (not harvest cache)."""
    events = us_events_fn() if us_events_fn is not None else fetch_poly_us_events(prefixes)
    official = official_events_fn() if official_events_fn is not None else (
        [] if us_events_fn is not None else fetch_poly_official_events(prefixes)
    )
    optic_rows = optic_rows_fn() if optic_rows_fn is not None else _optic_window_for(store, prefixes)
    return events, official, optic_rows


def _optic_window_for(
    store: Any | None, prefixes: list[str],
) -> list[dict[str, Any]]:
    """±10d BQ window; filter to wired Optic ids when every prefix is on the tip."""
    if store is None:
        return fetch_optic_window()
    ids = optic_ids_if_all_wired(_tip_leagues(store), prefixes)
    if ids is None:
        return fetch_optic_window()
    return fetch_optic_window(optic_ids=ids) if ids else []


def _try_prefix(
    store: Any,
    key: str,
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    ctx: dict[str, Any],
) -> None:
    """Attempt one inventoried prefix; append pins or a post-try skip."""
    before = len(pins)
    try:
        _attempt_prefix(store, key, events, rows, pins, skipped, seen, ctx)
    finally:
        for pin in pins[before:]:
            if not str(pin.get("harvest_key") or ""):
                stamp_gap_harvest_pin(pin, book="polymarket", key=key or "(null)")


def _attempt_prefix(
    store: Any,
    key: str,
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    ctx: dict[str, Any],
) -> None:
    if not key or key == "(null)":
        skipped.append(_skip(key or "(null)", "poly_null_prefix"))
        return
    owners: list[LeagueRow] = ctx["by_code"].get(key) or []
    if _try_non_optic_book(key, owners, pins, skipped):
        return
    if not us_inner_owner_ok(key, owners):
        skipped.append(_skip(key, "us_code_collision"))
        return
    us_matched = [e for e in events if str(e.get("inner") or "").casefold() == key]
    official_matched = [
        e for e in ctx["official"] if str(e.get("prefix") or "").casefold() == key
    ]
    us_handled = _try_us(store, key, owners, us_matched, rows, ctx, pins, skipped, seen)
    off_handled = try_official_prefix(
        store, key, official_matched, rows, pins, skipped, ctx,
    )
    if not us_handled and not off_handled:
        skipped.append(_skip(key, "missing_us_events"))


def _try_non_optic_book(
    key: str,
    owners: list[LeagueRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> bool:
    """Skip SETKA/Modus; draft a USA disable when a tip row already stole the inner."""
    if key not in NO_OPTIC_US_INNERS:
        return False
    if len(owners) == 1:
        pins.append(disable_us_pin(owners[0]))
    skipped.append(_skip(key, "no_optic_book"))
    return True


def _try_us(
    store: Any,
    key: str,
    owners: list[LeagueRow],
    matched: list[dict[str, Any]],
    rows: list[LeagueRow],
    ctx: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> bool:
    """US inner path. True when aliases/league pins or a US skip were recorded."""
    if owners:
        return _try_wired(store, key, owners, matched, rows, ctx, pins, skipped, seen)
    if not matched:
        return False
    _try_unwired(store, key, matched, rows, ctx, pins, skipped, seen)
    return True


def _try_unwired(
    store: Any,
    key: str,
    matched: list[dict[str, Any]],
    rows: list[LeagueRow],
    ctx: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    """Enable US on a unique Optic tip row, or onboard a new league."""
    optic_id = unique_optic_for_events(matched, ctx["fixtures"])
    if not optic_id:
        skipped.append(_skip(key, "missing_optic"))
        return
    targets: list[LeagueRow] = ctx["by_optic_id"].get(optic_id) or []
    if len(targets) > 1:
        skipped.append(_skip(key, "optic_league_collision"))
        return
    drafted = ctx.setdefault("drafted_optics", {})
    existing = drafted.get(optic_id)
    if existing is not None:
        patch_us_code(existing, key)
        _draft_aliases(
            store, existing["league"], matched, ctx["fixtures"].get(optic_id) or [],
            pins, seen, ctx["claimed"], ctx["used"], ctx["tips"],
        )
        return
    if targets:
        _try_enable(store, key, targets[0], matched, ctx, pins, skipped, seen)
        return
    _try_onboard(store, key, optic_id, rows, ctx, pins, skipped)


def _try_wired(
    store: Any,
    key: str,
    owners: list[LeagueRow],
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    ctx: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> bool:
    """Draft aliases for every tip league that shares this US inner."""
    if not events:
        return False
    added = 0
    for row in us_inner_targets(key, owners, rows):
        n = _draft_aliases(
            store, row.league, events,
            ctx["fixtures"].get(row.optic_league_id) or [],
            pins, seen, ctx["claimed"], ctx["used"], ctx["tips"],
        )
        if n and us_league_code(row).casefold() != key:
            _try_enable(store, key, row, events, ctx, pins, skipped, seen)
        added += n
    if not added:
        skipped.append(_skip(key, "prefix_satisfied"))
    return True


def _try_enable(
    store: Any,
    key: str,
    row: LeagueRow,
    events: list[dict[str, Any]],
    ctx: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    """Enable or remap polymarket_usa on an existing tip league, then aliases."""
    current = us_league_code(row).casefold()
    optic_id = str(row.optic_league_id)
    drafted = ctx.setdefault("drafted_optics", {})
    if current != key:
        existing = drafted.get(optic_id)
        if existing is not None:
            patch_us_code(existing, key)
        else:
            pin = enable_us_pin(row, key)
            pins.append(pin)
            drafted[optic_id] = pin
    added = _draft_aliases(
        store, row.league, events, ctx["fixtures"].get(optic_id) or [],
        pins, seen, ctx["claimed"], ctx["used"], ctx["tips"],
    )
    if current == key and not added:
        skipped.append(_skip(key, "prefix_satisfied"))


def _try_onboard(
    store: Any,
    key: str,
    optic_id: str,
    rows: list[LeagueRow],
    ctx: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    """Onboard a new tip league when Optic is unique and no row owns it."""
    slug = slug_from_optic_id(optic_id)
    if not slug:
        skipped.append(_skip(key, "missing_optic"))
        return
    if slug.casefold() in {r.league.casefold() for r in rows if not r.tombstone}:
        skipped.append(_skip(key, "slug_collision"))
        return
    sport = sport_for(optic_id, rows, ctx["fixtures"])
    clone = clone_source(store, sport)
    if not clone:
        skipped.append(_skip(key, "missing_clone_source"))
        return
    pin = onboard_pin(slug, sport, optic_id, key, clone)
    pins.append(pin)
    ctx.setdefault("drafted_optics", {})[optic_id] = pin


def _draft_aliases(
    store: Any,
    league: str,
    events: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    claimed: dict[tuple[str, str], str],
    used: dict[str, set[str]],
    tips: dict[str, TipLeagueIndex],
) -> int:
    """Append entity_alias pins for uniquely matched fixtures. Return count."""
    before = len(pins)
    indexed = tips.get(league) or TipLeagueIndex()
    pool = used.setdefault(league, set(indexed.used))
    for event in events:
        hit = best_fixture(event, fixtures)
        if hit is None:
            continue
        for usa, abbr, oid, name in _oriented_pairs(event, hit["fx"], str(hit["orient"])):
            pin = _alias_pin(
                store, league, usa, abbr, oid, name, pool, seen, claimed, event, hit["fx"],
                indexed,
            )
            if pin is None:
                continue
            pins.append(pin)
            pool.add(str(pin["canonical_key"]).upper())
    return len(pins) - before


def _alias_pin(
    store: Any,
    league: str,
    usa: str,
    abbr: str,
    oid: str,
    name: str,
    pool: set[str],
    seen: set[tuple[str, str, str]],
    claimed: dict[tuple[str, str], str],
    event: dict[str, Any],
    fx: dict[str, Any],
    indexed: TipLeagueIndex,
) -> dict[str, Any] | None:
    """One Optic + polymarket_usa pin, or None on skip/collision."""
    key = _alias_key(league, oid, usa, abbr)
    if key is None or key in seen:
        return None
    resolved = _resolve_canonical(store, league, usa, abbr, oid, name, pool, indexed)
    if resolved is None:
        seen.add(key)
        return None
    canonical, entity_type, display = resolved
    if not _claim_usa(league, usa, canonical, claimed, indexed):
        return None
    seen.add(key)
    shown = str(display or name)
    return alias_payload(
        league, canonical, shown, entity_type,
        [optic_pin(str(oid)), {"sportsbook": POLY_USA_BOOK, "alias_kind": "code", "alias_value": usa}],
        usa_alias_refs(league, usa, event, str(oid), shown, fx),
    )


def _alias_key(league: str, oid: str, usa: str, abbr: str) -> tuple[str, str, str] | None:
    """Seen-key for one event side, or None when the pair is not pin-worthy."""
    if not oid or not usa or usa.casefold() == str(abbr or "").casefold():
        return None
    return (league, str(oid), usa.casefold())


def _resolve_canonical(
    store: Any,
    league: str,
    usa: str,
    abbr: str,
    oid: str,
    name: str,
    pool: set[str],
    indexed: TipLeagueIndex,
) -> tuple[str, str, str] | None:
    """(canonical, entity_type, display), or None when already fully pinned."""
    owner_key = indexed_optic_key(indexed, oid)
    want = match_entity_type_for_league(store, league)
    if not owner_key:
        canonical = str(abbr or "").strip()
        if not canonical or not is_valid_bare_key(canonical):
            canonical = fallback_code(str(name or usa), pool, str(oid))
        return canonical, want, name
    entity_type = indexed.types.get(owner_key, "") or want
    if entity_type not in ("team", "player", "fighter"):
        entity_type = want
    if indexed_has_optic(indexed, owner_key, oid) and indexed_has_usa(
        indexed, owner_key, usa,
    ):
        return None
    return owner_key, entity_type, indexed.names.get(owner_key) or name


def _claim_usa(
    league: str,
    usa: str,
    canonical: str,
    claimed: dict[tuple[str, str], str],
    indexed: TipLeagueIndex,
) -> bool:
    """True when this canonical may take the US code (no collision)."""
    owners = indexed_usa_owners(indexed, usa)
    if owners and canonical not in owners:
        return False
    claimed_key = (league, usa.casefold())
    taken = claimed.get(claimed_key)
    if taken and taken != canonical:
        return False
    claimed[claimed_key] = canonical
    return True


def _oriented_pairs(
    event: dict[str, Any],
    fx: dict[str, Any],
    orient: str,
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str]]:
    """((usa, abbr, oid, name), ...) in event home/away order."""
    if orient == "same":
        return (
            (str(event["home"]), str(fx["home_abbr"] or ""), str(fx["home_id"] or ""), str(fx["home_name"] or "")),
            (str(event["away"]), str(fx["away_abbr"] or ""), str(fx["away_id"] or ""), str(fx["away_name"] or "")),
        )
    return (
        (str(event["home"]), str(fx["away_abbr"] or ""), str(fx["away_id"] or ""), str(fx["away_name"] or "")),
        (str(event["away"]), str(fx["home_abbr"] or ""), str(fx["home_id"] or ""), str(fx["home_name"] or "")),
    )


def _tip_leagues(store: Any) -> list[LeagueRow]:
    """Non-tombstoned tip league rows."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    return [r for r in store.leagues_for(rid) if not r.tombstone]


def _us_code_index(rows: list[LeagueRow]) -> dict[str, list[LeagueRow]]:
    """Map enabled polymarket_usa inner codes to tip rows."""
    out: dict[str, list[LeagueRow]] = defaultdict(list)
    for row in rows:
        code = us_league_code(row).casefold()
        if code:
            out[code].append(row)
    return dict(out)


def _optic_index(rows: list[LeagueRow]) -> dict[str, list[LeagueRow]]:
    """Map Optic league ids to tip rows."""
    out: dict[str, list[LeagueRow]] = defaultdict(list)
    for row in rows:
        oid = str(row.optic_league_id or "").strip()
        if oid:
            out[oid].append(row)
    return dict(out)


def _fixtures_by_optic(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group Optic fixture rows by league id."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        oid = str(row.get("optic_league_id") or "").strip()
        if oid:
            out[oid].append(row)
    return dict(out)


def _skip(key: str, reason: str) -> dict[str, str]:
    """Polymarket harvest skip row."""
    return {"book": "polymarket", "key": key, "reason": reason}
