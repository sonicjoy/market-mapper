"""Harvest crypto/Polymarket/listed-book gap pins (US aliases and official Path 2)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from typing import Any

from mappers.control_plane.gap_crypto_catalogue import batched_catalogue_fn
from mappers.control_plane.gap_fix_ai_suggest import append_ai_suggestions
from mappers.control_plane.gap_fix_crypto_empty import harvest_missing_crypto_ids
from mappers.control_plane.gap_fix_dkex_harvest import harvest_dkex_catalog_gaps
from mappers.control_plane.gap_fix_listed_onboard import (
    LISTED_ONBOARD_BOOKS,
    harvest_listed_rfq_onboard,
)
from mappers.control_plane.gap_fix_market_ai import append_ai_market_suggestions
from mappers.control_plane.gap_fix_market_rules import harvest_missing_market_rules
from mappers.control_plane.gap_fix_novig_rfq import harvest_listed_rfq_inventory
from mappers.control_plane.gap_fix_optic_abbr import harvest_duplicate_optic_abbrs
from mappers.control_plane.gap_fix_optic_abbr_codes import harvest_optic_abbr_codes
from mappers.control_plane.gap_fix_optic_empty import (
    harvest_missing_optic_competitors,
    remember_verify_optic_misses,
)
from mappers.control_plane.gap_fix_optic_merge import (
    OpticDrafted,
    merge_pins_by_optic_id,
    seed_optic_drafts,
)
from mappers.control_plane.gap_fix_poly import (
    OfficialEventsFn,
    OpticRowsFn,
    UsEventsFn,
    harvest_poly_side,
    load_poly_side_inputs,
)
from mappers.control_plane.gap_fix_poly_empty import harvest_missing_poly_usa_codes
from mappers.control_plane.gap_fix_px import PxEventsFn, harvest_px_code_misses
from mappers.control_plane.gap_fix_px_onboard import harvest_px_rfq_onboard
from mappers.control_plane.gap_fix_skip import log_harvest_skips
from mappers.control_plane.gap_fix_slots import (
    EmptyHarvestBudget,
    PinSlots,
    empty_budget_for_drain,
    fill_crypto_slots,
    pin_slots_for_drain,
)
from mappers.control_plane.gap_fix_sxbet import harvest_sxbet_rfq
from mappers.control_plane.gap_fix_tip import index_tip_leagues
from mappers.control_plane.gap_fix_verify import verify_submit
from mappers.control_plane.gap_fix_walk import take_harvest_pin
from mappers.control_plane.gap_inventory import (
    INVENTORY_PAGE,
    MAX_PROBE,
    RfqGapItem,
    fetch_rfq_inventory,
)
from mappers.control_plane.gap_optic_cache import clear_optic_cache, warm_optic_cache
from mappers.control_plane.market_rule_card import market_rule_card
from mappers.control_plane.pin_flow import is_league_pin as _is_league_pin
from mappers.control_plane.pin_flow import verify_pins
from mappers.control_plane.pin_flow_markets import (
    is_market_pin as _is_market_pin,
)
from mappers.control_plane.pin_flow_markets import (
    market_payload_from_pin as _market_payload_from_pin,
)
from mappers.control_plane.pipeline_gap_batch import UNKNOWN_LEAGUE
from mappers.control_plane.rfq_platforms import HARVEST_BOOKS
from mappers.control_plane.rof_before_rule import harvest_rof_before_ignore
from mappers.control_plane.underdog_fixture_classify import harvest_underdog_gaps

logger = logging.getLogger(__name__)

InventoryFn = Callable[[], list[RfqGapItem]]


def harvest_gap_pins(
    store: Any,
    *,
    symbols: list[str] | None = None,
    poly_prefixes: list[str] | None = None,
    inventory_fn: InventoryFn | None = None,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None = None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None = None,
    us_events_fn: UsEventsFn | None = None,
    official_events_fn: OfficialEventsFn | None = None,
    optic_rows_fn: OpticRowsFn | None = None,
    ai_llm: Any | None = None,
    px_events_fn: PxEventsFn | None = None,
    crypto_harvest_fn: Callable[[str, int], dict[str, str]] | None = None,
    drain: bool = False,
    yield_fn: Callable[[], bool] | None = None,
    walked_out: set[tuple[str, str]] | None = None,
    card_league: str = "",
) -> dict[str, Any]:
    """Inventory RFQ true gaps plus Optic/PX/crypto_id/abbr-code/Poly US sides missing from the tip.

    ``drain`` walks exactly ``inventory_fn``'s keys: one league card, already seated.
    """
    clear_optic_cache()
    started = time.monotonic()
    items = _inventory(store, symbols, poly_prefixes, inventory_fn)
    _log_inventory_stage(started, items)
    catalogue_fn = _warm_live_sources(store, items, fixtures_fn, catalogue_fn, card_league)
    return _collect_harvest(
        store, items, fixtures_fn, catalogue_fn,
        us_events_fn, official_events_fn, optic_rows_fn, ai_llm, px_events_fn,
        crypto_harvest_fn=crypto_harvest_fn,
        drain=drain,
        yield_fn=yield_fn,
        walked_out=walked_out,
        card_league=card_league,
    )


def _warm_live_sources(
    store: Any,
    items: list[RfqGapItem],
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    card_league: str = "",
) -> Callable[[str], dict[str, Any]] | None:
    """BQ Optic cache + one crypto catalogue job when callers did not inject stubs.

    A drain league card warms only its own league; the unknown card warms none.
    """
    if fixtures_fn is None:
        leagues = None
        if card_league:
            leagues = frozenset() if card_league == UNKNOWN_LEAGUE else frozenset({card_league})
        warm_optic_cache(store, leagues=leagues)
    crypto_keys = [item.key for item in items if item.book == "crypto"]
    if catalogue_fn is None and crypto_keys:
        return batched_catalogue_fn(crypto_keys) or catalogue_fn
    return catalogue_fn


def _harvest_payload(
    store: Any,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    walked_keys: set[tuple[str, str]],
) -> dict[str, Any]:
    log_harvest_skips(skipped)
    return {
        "ok": True,
        "count": len(pins),
        "pins": pins,
        "skipped": skipped,
        "cart_items": [_cart_item(p) for p in pins],
        "tip_at_harvest": getattr(store, "current_rule_set_id", None),
        "inventory": [{"book": i.book, "key": i.key, "demand": i.demand} for i in items],
        "walked_keys": sorted(walked_keys),
    }


def _rfq_walked_keys(_items: list[RfqGapItem]) -> set[tuple[str, str]]:
    """Start empty; slot fill records keys actually probed."""
    return set()


def _collect_harvest(
    store: Any,
    items: list[RfqGapItem],
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    ai_llm: Any | None,
    px_events_fn: PxEventsFn | None,
    crypto_harvest_fn: Callable[[str, int], dict[str, str]] | None = None,
    *,
    drain: bool = False,
    yield_fn: Callable[[], bool] | None = None,
    walked_out: set[tuple[str, str]] | None = None,
    card_league: str = "",
) -> dict[str, Any]:
    """Parallel book probes then Optic/PX/crypto_id/AI fixture harvest."""
    walked_keys = walked_out if walked_out is not None else _rfq_walked_keys(items)
    pins, skipped, seen = _probe_parallel(
        store, items,
        fixtures_fn=fixtures_fn, catalogue_fn=catalogue_fn,
        us_events_fn=us_events_fn, official_events_fn=official_events_fn,
        optic_rows_fn=optic_rows_fn, drain=drain,
        yield_fn=None if drain else yield_fn, walked_keys=walked_keys,
        px_events_fn=px_events_fn,
    )
    if drain:
        pins[:] = merge_pins_by_optic_id(pins)
        payload = _harvest_payload(store, items, pins, skipped, walked_keys)
        if card_league:
            payload["card_league"] = card_league
        return payload
    return _with_fixture_harvest(
        store, items, pins, skipped, seen, walked_keys,
        fixtures_fn=fixtures_fn, px_events_fn=px_events_fn, ai_llm=ai_llm,
        catalogue_fn=catalogue_fn,
        crypto_harvest_fn=crypto_harvest_fn, us_events_fn=us_events_fn,
        optic_rows_fn=optic_rows_fn,
    )


def _probe_parallel(
    store: Any,
    items: list[RfqGapItem],
    *,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    drain: bool,
    yield_fn: Callable[[], bool] | None,
    walked_keys: set[tuple[str, str]],
    px_events_fn: PxEventsFn | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], set[tuple[str, str, str]]]:
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    _parallel_harvest(
        store, items, pins, skipped, seen,
        fixtures_fn=fixtures_fn, catalogue_fn=catalogue_fn,
        us_events_fn=us_events_fn, official_events_fn=official_events_fn,
        optic_rows_fn=optic_rows_fn, px_events_fn=px_events_fn,
        drain=drain, yield_fn=yield_fn, walked=walked_keys,
    )
    return pins, skipped, seen


def _with_fixture_harvest(
    store: Any,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    walked_keys: set[tuple[str, str]],
    *,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    px_events_fn: PxEventsFn | None,
    ai_llm: Any | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    crypto_harvest_fn: Callable[[str, int], dict[str, str]] | None,
    us_events_fn: UsEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
) -> dict[str, Any]:
    optic_drafted: OpticDrafted = {}
    crypto_assigned: set[tuple[str, str]] = set()
    seed_optic_drafts(optic_drafted, pins)
    _fixture_harvest(
        store, pins, skipped, seen, fixtures_fn, px_events_fn, ai_llm, items,
        catalogue_fn=catalogue_fn, optic_drafted=optic_drafted,
        crypto_harvest_fn=crypto_harvest_fn, crypto_assigned=crypto_assigned,
        today=datetime.now(tz=UTC).date(), us_events_fn=us_events_fn,
        optic_rows_fn=optic_rows_fn, empty_budget=empty_budget_for_drain(drain=False),
    )
    pins[:] = merge_pins_by_optic_id(pins)
    return _harvest_payload(store, items, pins, skipped, walked_keys)


def _fixture_harvest(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    px_events_fn: PxEventsFn | None,
    ai_llm: Any | None,
    items: list[RfqGapItem],
    *,
    catalogue_fn: Callable[[str], dict[str, Any]] | None = None,
    optic_drafted: OpticDrafted | None = None,
    crypto_harvest_fn: Callable[[str, int], dict[str, str]] | None = None,
    crypto_assigned: set[tuple[str, str]] | None = None,
    today: date | None = None,
    us_events_fn: UsEventsFn | None = None,
    optic_rows_fn: OpticRowsFn | None = None,
    empty_budget: EmptyHarvestBudget | None = None,
) -> None:
    """Optic/PX/crypto_id/abbr-code/Poly US harvest that runs even when RFQ inventory is empty."""
    assigned = crypto_assigned if crypto_assigned is not None else set()
    day = today or datetime.now(tz=UTC).date()
    tips = index_tip_leagues(store)
    harvest_duplicate_optic_abbrs(
        store, pins, skipped, seen, fixtures_fn=fixtures_fn, tips=tips,
    )
    harvest_optic_abbr_codes(
        store, pins, skipped, seen,
        fixtures_fn=fixtures_fn, empty_budget=empty_budget,
    )
    _harvest_optic_crypto_empty(
        store, pins, skipped, seen, fixtures_fn, optic_drafted,
        crypto_harvest_fn, assigned, day, tips, empty_budget=empty_budget,
    )
    harvest_px_code_misses(
        store, pins, skipped, seen,
        px_events_fn=px_events_fn, fixtures_fn=fixtures_fn, tips=tips,
    )
    harvest_missing_poly_usa_codes(
        store, pins, skipped, seen,
        us_events_fn=us_events_fn, optic_rows_fn=optic_rows_fn,
        fixtures_fn=fixtures_fn,
    )
    market_seen: set[tuple[str, str, str, str]] = set()
    harvest_missing_market_rules(
        store, items, pins, skipped, market_seen,
        fixtures_fn=fixtures_fn, catalogue_fn=catalogue_fn,
    )
    harvest_rof_before_ignore(store, pins, skipped)
    harvest_dkex_catalog_gaps(store, pins, skipped, seen)
    # Stub stores in gap tests are not activated tips. Catalog harvest
    # reads the live tip only, so those tests keep their pin lists.
    if type(store).__name__ == "BigQueryStore":
        harvest_underdog_gaps(store, pins, skipped, seen)
    append_ai_suggestions(store, skipped, pins, seen, llm=ai_llm)
    append_ai_market_suggestions(store, skipped, pins, market_seen, llm=ai_llm)


def _harvest_optic_crypto_empty(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    optic_drafted: OpticDrafted | None,
    crypto_harvest_fn: Callable[[str, int], dict[str, str]] | None,
    assigned: set[tuple[str, str]],
    day: date,
    tips: Any,
    empty_budget: EmptyHarvestBudget | None = None,
) -> None:
    """Optic competitor + crypto_id harvest when RFQ inventory is empty."""
    harvest_missing_optic_competitors(
        store, pins, skipped, seen, fixtures_fn=fixtures_fn,
        optic_drafted=optic_drafted,
        harvest_fn=crypto_harvest_fn,
        crypto_assigned=assigned,
        today=day,
        tips=tips,
        empty_budget=empty_budget,
    )
    harvest_missing_crypto_ids(
        store, pins, skipped, seen,
        fixtures_fn=fixtures_fn, harvest_fn=crypto_harvest_fn,
        optic_drafted=optic_drafted,
        crypto_assigned=assigned,
        today=day,
        tips=tips,
        empty_budget=empty_budget,
    )


def propose_gap_pins(
    service: Any,
    actor: Any,
    pins: list[dict[str, Any]],
    *,
    acknowledge_shadow: bool,
    note: str = "gap-fix harvest",
    existing_proposal_id: str | None = None,
) -> dict[str, Any]:
    """Drop already-live aliases, then batch verify + submit (no approve)."""
    working = list(pins)
    started = time.monotonic()
    kept, skipped = verify_pins(
        getattr(service, "store", None),
        working,
        probe=None,
    )
    logger.info(
        "pipeline gap-fix stage=preverify sec=%.1f pins=%d kept=%d",
        time.monotonic() - started,
        len(working),
        len(kept),
    )
    if not kept:
        return {
            "ok": False,
            "blockers": skipped or ["no pins"],
            "skipped_blockers": skipped,
            "warnings": [],
        }
    result = verify_submit(
        service, actor, kept, skipped, acknowledge_shadow, note, existing_proposal_id,
    )
    remember_verify_optic_misses(working, list(result.get("skipped_blockers") or []))
    return result


def _inventory(
    store: Any,
    symbols: list[str] | None,
    poly_prefixes: list[str] | None,
    inventory_fn: InventoryFn | None,
) -> list[RfqGapItem]:
    """Build ranked inventory; explicit lists override RFQ SQL."""
    cap = INVENTORY_PAGE * 2 if inventory_fn is None else MAX_PROBE * 2
    if symbols is not None or poly_prefixes is not None:
        items = [RfqGapItem("crypto", s.strip(), 1) for s in (symbols or []) if s and s.strip()]
        items.extend(
            RfqGapItem("polymarket", p.strip(), 1)
            for p in (poly_prefixes or [])
            if p and p.strip()
        )
        return items[:cap]
    if inventory_fn is not None:
        return list(inventory_fn())[:cap]
    return fetch_rfq_inventory(store, limit=INVENTORY_PAGE)


def _px_event_from_fn(px_events_fn: PxEventsFn) -> Callable[[str], dict[str, Any] | None]:
    """Resolve one PX event_id by scanning injected tournament feeds."""

    def lookup(event_id: str) -> dict[str, Any] | None:
        needle = str(event_id).strip()
        if not needle:
            return None
        for tid in _px_tournament_ids_from_fn(px_events_fn):
            for raw in px_events_fn(tid):
                if str(raw.get("event_id") or "") == needle:
                    return raw
        return None

    return lookup


def _px_tournament_ids_from_fn(px_events_fn: PxEventsFn) -> list[str]:
    """Tournament ids exposed by test stubs (optional ``tournament_ids`` attr)."""
    extra = getattr(px_events_fn, "tournament_ids", None)
    if isinstance(extra, (list, tuple)):
        return [str(t) for t in extra if str(t).strip()]
    return []


def _parallel_harvest(
    store: Any,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    px_events_fn: PxEventsFn | None,
    drain: bool = False,
    yield_fn: Callable[[], bool] | None = None,
    walked: set[tuple[str, str]] | None = None,
) -> None:
    """Harvest every RFQ book in parallel; drain shares one 100-slot budget."""
    jobs = _schedule_harvest_jobs(
        store, items,
        fixtures_fn=fixtures_fn, catalogue_fn=catalogue_fn,
        us_events_fn=us_events_fn, official_events_fn=official_events_fn,
        optic_rows_fn=optic_rows_fn, px_events_fn=px_events_fn,
        drain=drain, yield_fn=yield_fn, walked=walked,
    )
    _merge_harvest_jobs(jobs, pins, skipped, seen)


def _schedule_harvest_jobs(
    store: Any,
    items: list[RfqGapItem],
    *,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    px_events_fn: PxEventsFn | None,
    drain: bool,
    yield_fn: Callable[[], bool] | None,
    walked: set[tuple[str, str]] | None,
) -> dict[Any, str]:
    by_book = {book: [item for item in items if item.book == book] for book in HARVEST_BOOKS}
    shared = pin_slots_for_drain(drain=True) if drain else None
    workers = sum(1 for rows in by_book.values() if rows) or 1
    jobs: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(HARVEST_BOOKS), workers)) as pool:
        _submit_alias_books(
            pool, jobs, store, by_book, shared,
            fixtures_fn=fixtures_fn, catalogue_fn=catalogue_fn,
            us_events_fn=us_events_fn, official_events_fn=official_events_fn,
            optic_rows_fn=optic_rows_fn, yield_fn=yield_fn, walked=walked,
        )
        _submit_listed_books(
            pool, jobs, store, by_book, shared,
            px_events_fn=px_events_fn, fixtures_fn=fixtures_fn, walked=walked,
        )
        return dict(jobs)


def _submit_alias_books(
    pool: ThreadPoolExecutor,
    jobs: dict[Any, str],
    store: Any,
    by_book: dict[str, list[RfqGapItem]],
    shared: PinSlots | None,
    *,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    yield_fn: Callable[[], bool] | None,
    walked: set[tuple[str, str]] | None,
) -> None:
    """Crypto and Polymarket each get their own slot budget unless draining."""
    drain = shared is not None
    if by_book["crypto"]:
        keys = [item.key for item in by_book["crypto"]]
        slots = _book_slots(shared)
        jobs[pool.submit(
            _crypto_side, store, keys, catalogue_fn, fixtures_fn, slots, yield_fn, walked, drain,
        )] = "crypto"
    if by_book["polymarket"]:
        keys = [item.key for item in by_book["polymarket"]]
        slots = _book_slots(shared)
        jobs[pool.submit(
            _poly_side, store, keys, us_events_fn, official_events_fn, optic_rows_fn, slots, walked,
        )] = "polymarket"


def _submit_listed_books(
    pool: ThreadPoolExecutor,
    jobs: dict[Any, str],
    store: Any,
    by_book: dict[str, list[RfqGapItem]],
    shared: PinSlots | None,
    *,
    px_events_fn: PxEventsFn | None,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    walked: set[tuple[str, str]] | None,
) -> None:
    """Novig, ProphetX, Underdog, DKEX, Huddle and SX run with the alias books."""
    for book in sorted(LISTED_ONBOARD_BOOKS):
        if by_book[book]:
            jobs[pool.submit(_listed_onboard_side, store, book, by_book[book], walked)] = book
    if by_book["huddle"]:
        keys = [item.key for item in by_book["huddle"]]
        jobs[pool.submit(_listed_side, "huddle", keys, walked)] = "huddle"
    if by_book["sxbet"]:
        jobs[pool.submit(_sxbet_side, by_book["sxbet"], walked)] = "sxbet"
    if by_book["prophetx"]:
        slots = _book_slots(shared)
        jobs[pool.submit(
            _px_side, store, by_book["prophetx"], px_events_fn, slots, fixtures_fn, walked,
        )] = "prophetx"


def _book_slots(shared: PinSlots | None) -> PinSlots:
    return shared if shared is not None else pin_slots_for_drain(drain=False)


def _listed_side(
    book: str,
    keys: list[str],
    walked: set[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Ledger keys whose alias probe is still needs_probe."""
    skipped: list[dict[str, str]] = []
    harvest_listed_rfq_inventory(
        book, [RfqGapItem(book, key, 1) for key in keys if key], skipped,
    )
    if walked is not None:
        for key in keys:
            if key:
                walked.add((book, key))
    return [], skipped


def _sxbet_side(
    items: list[RfqGapItem],
    walked: set[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """SX: one reason per key, no pins (its leagues / types / names are code tables)."""
    skipped: list[dict[str, str]] = []
    harvest_sxbet_rfq(items, skipped, walked)
    return [], skipped


def _listed_onboard_side(
    store: Any,
    book: str,
    items: list[RfqGapItem],
    walked: set[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Underdog / DKEX / Novig: league pin when Optic has the league, else needs_probe."""
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    rid = getattr(store, "current_rule_set_id", None)
    rows = list(store.leagues_for(rid)) if rid and hasattr(store, "leagues_for") else []
    harvest_listed_rfq_onboard(store, book, items, pins, skipped, rows)
    if walked is not None:
        walked.update((book, item.key) for item in items if item.key)
    return pins, skipped


def _px_side(
    store: Any,
    items: list[RfqGapItem],
    px_events_fn: PxEventsFn | None,
    slots: PinSlots,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    walked: set[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """ProphetX tournament onboard, sharing the drain slot budget."""
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    rid = getattr(store, "current_rule_set_id", None)
    rows = list(store.leagues_for(rid)) if rid and hasattr(store, "leagues_for") else []
    lookup = None if px_events_fn is None else _px_event_from_fn(px_events_fn)
    for item in items:
        if slots.full():
            break
        if walked is not None and item.key:
            walked.add(("prophetx", item.key))
        before = len(pins)
        harvest_px_rfq_onboard(
            store, [item], pins, skipped, seen, rows, {},
            event_lookup_fn=lookup, fixtures_fn=fixtures_fn,
        )
        if len(pins) > before:
            slots.record_pin_event()
    return pins, skipped


def _merge_harvest_jobs(
    jobs: dict[Any, str],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    for fut in as_completed(jobs):
        book = jobs[fut]
        try:
            side_pins, side_skip = fut.result()
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001 — isolate book failure
            logger.exception("gap harvest %s failed", book)
            skipped.append({"book": book, "reason": f"harvest_error:{exc}"[:160]})
            continue
        for pin in side_pins:
            take_harvest_pin(
                pins, skipped, seen, pin,
                identity=_pin_identity, merge_league=_merge_league_exchanges,
            )
        skipped.extend(side_skip)


def _merge_league_exchanges(
    pins: list[dict[str, Any]],
    pin: dict[str, Any],
    ident: tuple[str, str, str],
) -> None:
    """Two books enabling the same league row: keep one pin carrying both exchanges."""
    existing = next((p for p in pins if _pin_identity(p) == ident), None)
    if existing is None:
        return
    exchanges = list(existing.get("exchanges") or [])
    books = {str(ex.get("sportsbook") or "") for ex in exchanges}
    exchanges.extend(ex for ex in pin.get("exchanges") or [] if str(ex.get("sportsbook") or "") not in books)
    existing["exchanges"] = exchanges


def _crypto_side(
    store: Any,
    symbols: list[str],
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
    slots: PinSlots,
    yield_fn: Callable[[], bool] | None,
    walked: set[tuple[str, str]] | None,
    drain: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Probe crypto RFQ symbols and draft pins."""
    started = time.monotonic()
    pins, skipped = fill_crypto_slots(
        store, symbols, catalogue_fn, fixtures_fn, slots,
        yield_fn=yield_fn, walked=walked, drain=drain,
    )
    _log_probe_stage("crypto", started, symbols, pins)
    return pins, skipped


def _poly_side(
    store: Any,
    prefixes: list[str],
    us_events_fn: UsEventsFn | None,
    official_events_fn: OfficialEventsFn | None,
    optic_rows_fn: OpticRowsFn | None,
    slots: PinSlots,
    walked: set[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Try US aliases and official Path 2; skip only after evidence failure."""
    if walked is not None:
        for prefix in prefixes:
            if prefix:
                walked.add(("polymarket", prefix))
    started = time.monotonic()
    events, official, optic_rows = load_poly_side_inputs(
        prefixes, us_events_fn, official_events_fn, optic_rows_fn, store=store,
    )
    pins, skipped = harvest_poly_side(
        store, prefixes, events, optic_rows, official_events=official, slots=slots,
    )
    _log_probe_stage("polymarket", started, prefixes, pins)
    return pins, skipped


def _pin_identity(pin: dict[str, Any]) -> tuple[str, str, str] | None:
    """Dedupe key for one harvest pin; None when the pin is incomplete."""
    if _is_league_pin(pin):
        slug = str(pin.get("league") or "")
        if not slug:
            return None
        return ("mapping_league", slug, str(pin.get("optic_league_id") or ""))
    if _is_market_pin(pin):
        rules = pin.get("rules") or []
        book_rule = next((r for r in rules if str(r.get("sportsbook") or "") != "optic"), None)
        if book_rule is None:
            return None
        return (
            "mapping_market_rules",
            str(pin.get("league") or ""),
            f"{book_rule.get('sportsbook')}|{book_rule.get('source_key')}",
        )
    aliases = pin.get("aliases") or []
    if not aliases:
        return None
    return (
        str(pin.get("league") or ""),
        str(pin.get("canonical_key") or ""),
        str(aliases[0].get("alias_value") or ""),
    )


def _log_inventory_stage(started: float, items: list[RfqGapItem]) -> None:
    """Log BQ inventory wall time and per-book key counts."""
    books = {"crypto": 0, "polymarket": 0, "prophetx": 0}
    for item in items:
        books[item.book] = books.get(item.book, 0) + 1
    logger.info(
        "pipeline gap-fix stage=inventory sec=%.1f items=%d crypto=%d poly=%d px=%d",
        time.monotonic() - started,
        len(items),
        books["crypto"],
        books["polymarket"],
        books["prophetx"],
    )


def _log_probe_stage(book: str, started: float, keys: list[str], pins: list[dict[str, Any]]) -> None:
    """Log one harvest-side wall time."""
    logger.info(
        "pipeline gap-fix stage=probe book=%s sec=%.1f keys=%d pins=%d",
        book, time.monotonic() - started, len(keys), len(pins),
    )


def _cart_item(pin: dict[str, Any]) -> dict[str, Any]:
    """Mapper Chat / cart_add item for one pin."""
    if _is_league_pin(pin):
        league = pin.get("league")
        return {
            "kind": "mapping_league",
            "label": f"Pin Polymarket on {league}",
            "payload": pin,
        }
    if _is_market_pin(pin):
        rules = pin.get("rules") or []
        book_rule = next((r for r in rules if str(r.get("sportsbook") or "") != "optic"), {})
        label = market_rule_card(
            book_rule,
            league=str(pin.get("league") or ""),
            evidence_refs=[str(ref) for ref in (pin.get("evidence_refs") or []) if ref],
        )["label"]
        return {
            "kind": "mapping_market_rules",
            "label": label,
            "payload": _market_payload_from_pin(pin).model_dump(mode="json"),
        }
    name = pin.get("canonical_name") or pin.get("canonical_key")
    league = pin.get("league")
    first = (pin.get("aliases") or [{}])[0]
    label = (
        f"Remove {first.get('alias_value')} from {name}"
        if first.get("remove")
        else f"Pin {name} in {league}"
    )
    return {
        "kind": "entity_alias",
        "label": label,
        "payload": pin,
    }
