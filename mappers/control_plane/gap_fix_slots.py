"""Walk harvest inventory until pin-producing slots fill."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.gap_fix_draft import collect_crypto_probe_pins
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted
from mappers.control_plane.gap_fix_preprobe import try_crypto_offline_probe
from mappers.control_plane.gap_fix_tip import index_tip_leagues
from mappers.control_plane.gap_fix_walk import ensure_walk_recorded
from mappers.control_plane.gap_harvest_ttl import load_dead_buckets, save_dead_buckets
from mappers.control_plane.gap_inventory import (
    MAX_EMPTY_HARVEST_PINS,
    MAX_EVENTS,
    drop_dead_buckets,
    note_unproductive,
    series_bucket,
)
from mappers.control_plane.gap_mapping_batch import lookup_mappings_batch

DRAIN_CARD_SLOTS = 100

logger = logging.getLogger(__name__)

# Keys probed per round.
_WINDOW = 8
FixturesFn = Callable[..., list[dict[str, Any]]]
Hits = dict[str, list[dict[str, Any]]]
Pair = tuple[str, dict[str, Any]]


class EmptyHarvestBudget:
    """Shared pin cap for empty-RFQ fixture sweepers (abbr / missing / crypto)."""

    def __init__(self, limit: int = MAX_EMPTY_HARVEST_PINS) -> None:
        self.limit = limit
        self._filled = 0

    def remaining(self) -> int:
        return max(0, self.limit - self._filled)

    def full(self) -> bool:
        return self._filled >= self.limit

    def record(self, added: int) -> None:
        if added > 0:
            self._filled = min(self.limit, self._filled + added)


class PinSlots:
    """One book's budget of pin-producing events this harvest tick."""

    def __init__(self, limit: int = MAX_EVENTS) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._filled = 0

    def full(self) -> bool:
        """True when this book has already drafted ``limit`` pin events."""
        with self._lock:
            return self._filled >= self.limit

    def record_pin_event(self) -> None:
        """Count one inventory key that produced a pin."""
        with self._lock:
            if self._filled < self.limit:
                self._filled += 1


def pin_slots_for_drain(*, drain: bool) -> PinSlots:
    """Drain cards share 100 pin events. Legacy harvest keeps one budget per book."""
    return PinSlots(limit=DRAIN_CARD_SLOTS if drain else MAX_EVENTS)


def empty_budget_for_drain(*, drain: bool) -> EmptyHarvestBudget:
    """Drain RFQ cards do not mix in empty-fixture pins."""
    limit = 0 if drain else MAX_EMPTY_HARVEST_PINS
    return EmptyHarvestBudget(limit=limit)


class _Walk:
    """Shared state for one book's slot walk."""

    def __init__(
        self,
        book: str,
        slots: PinSlots,
        yield_fn: Callable[[], bool] | None,
        walked: set[tuple[str, str]] | None,
        *,
        drain: bool = False,
    ) -> None:
        self.book = book
        self.slots = slots
        self.yield_fn = yield_fn
        self.walked = walked
        # Drain keys each get a ledger outcome. A series skip would leave them
        # unchecked, so inventory never empties and the worker stalls.
        self.series_skip = not drain
        self.persist_dead = self.series_skip and yield_fn is None
        self.dead: set[str] = load_dead_buckets(book) if self.persist_dead else set()
        self.streaks: dict[str, int] = {}
        self.pins: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self.seen: set[tuple[str, str, str]] = set()
        self.optic_drafted: OpticDrafted = {}
        self.used_by_league: dict[str, set[str]] = {}

    def stop(self) -> bool:
        return self.slots.full() or (self.yield_fn is not None and self.yield_fn())

    def run(
        self,
        keys: list[str],
        rows_for: Callable[[list[str]], list[Pair]],
        collect: Callable[[str, dict[str, Any]], str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Probe a window, then draft key by key until slots fill or yield fires."""
        remaining = list(keys)
        while remaining and not self.stop():
            remaining = drop_dead_buckets(remaining, self.book, self.dead)
            window, remaining = remaining[:_WINDOW], remaining[_WINDOW:]
            if window and not self._draft(rows_for(window), collect):
                break
        if self.persist_dead:
            save_dead_buckets(self.book, self.dead)
        return self.pins, self.skipped

    def _draft(
        self, pairs: list[Pair], collect: Callable[[str, dict[str, Any]], str],
    ) -> bool:
        """False once the walk must stop; undrafted keys stay not_walked."""
        for key, row in pairs:
            if self.stop():
                return False
            if series_bucket(self.book, key) in self.dead:
                continue
            before_pins, before_skip = len(self.pins), len(self.skipped)
            bucket = collect(key, row)
            if self.walked is not None:
                self.walked.add((self.book, key))
            self._record(before_pins, bucket, _skip_reason(self.skipped, before_skip, row), row)
            ensure_walk_recorded(
                self.book, key, self.pins, self.skipped, before_pins, before_skip, row=row,
            )
        return True

    def _record(self, before: int, bucket: str, kind: str, row: dict[str, Any]) -> None:
        """Credit a pin-producing event or count toward skipping the series."""
        if len(self.pins) > before:
            self.slots.record_pin_event()
            self.streaks[bucket] = 0
            return
        if not self.series_skip:
            return
        if row.get("offline_dead"):
            self.dead.add(bucket)
        else:
            note_unproductive(self.dead, self.streaks, bucket, kind)
        if bucket in self.dead:
            logger.info(
                "pipeline gap-fix skip bucket=%s reason=%s misses=%s",
                bucket, kind, self.streaks.get(bucket, 0),
            )


def fill_crypto_slots(
    store: Any,
    symbols: list[str],
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    fixtures_fn: FixturesFn | None,
    slots: PinSlots,
    *,
    yield_fn: Callable[[], bool] | None = None,
    walked: set[tuple[str, str]] | None = None,
    drain: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Probe crypto until pin slots fill; skip Optic-less sports after misses."""
    tips = index_tip_leagues(store)
    walk = _Walk("crypto", slots, yield_fn, walked, drain=drain)
    hits = lookup_mappings_batch(symbols) if catalogue_fn is None else None

    def rows_for(window: list[str]) -> list[Pair]:
        return _window_rows(
            window,
            lambda key: try_crypto_offline_probe(store, key),
            lambda live: _probe_crypto_rows(store, live, catalogue_fn, fixtures_fn, tips, hits),
        )

    def collect(key: str, row: dict[str, Any]) -> str:
        collect_crypto_probe_pins(
            store, row, walk.pins, walk.skipped, walk.seen, walk.optic_drafted,
            tips=tips, used_by_league=walk.used_by_league,
        )
        return series_bucket("crypto", key, meta=str(row.get("meta_league") or ""))

    return walk.run(symbols, rows_for, collect)


def _window_rows(
    window: list[str],
    offline_fn: Callable[[str], dict[str, Any] | None],
    probe_fn: Callable[[list[str]], list[dict[str, Any]]],
) -> list[Pair]:
    """Key-derived skips, then one probe call for the rest, in window order."""
    keys = list(dict.fromkeys(key for key in window if key.strip()))
    offline = {key: row for key in keys if (row := offline_fn(key)) is not None}
    live = [key for key in keys if key not in offline]
    probed = dict(zip(live, probe_fn(live), strict=True)) if live else {}
    return [(key, offline.get(key) or probed[key]) for key in keys]


def _skip_reason(
    skipped: list[dict[str, str]], before: int, row: dict[str, Any],
) -> str:
    """Prefer collect skip reason so unknown_alias without Optic counts as a miss."""
    if len(skipped) > before:
        return str(skipped[-1].get("reason") or "")
    return str(row.get("kind") or "")


def _probe_crypto_rows(
    store: Any,
    symbols: list[str],
    catalogue_fn: Callable[[str], dict[str, Any]] | None,
    fixtures_fn: FixturesFn | None,
    tips: dict[str, Any],
    hits: Hits | None,
) -> list[dict[str, Any]]:
    """Probe one window."""
    args: dict[str, Any] = {"symbols": symbols, "tips": tips, "probe_limit": _WINDOW}
    if hits is not None:
        args["mapping_hits"] = hits
    if catalogue_fn is not None:
        args["catalogue_fn"] = catalogue_fn
    if fixtures_fn is not None:
        args["fixtures_fn"] = fixtures_fn
    probed = run_probe_crypto_gap(store, args)
    return list(probed.get("results") or [])
