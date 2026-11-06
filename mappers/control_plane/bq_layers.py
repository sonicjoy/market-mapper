"""Batched COW layer loading with a process-local cache.

The console used to walk the lineage one ancestor at a time: a `get_receipt`
query plus a content query per step (two BigQuery jobs per ancestor, ~0.7s each
in job startup alone). At a chain depth of ~50 that is ~100 sequential jobs to
answer one page load.

This module replaces that with one parent-map query plus one ``IN UNNEST``
query per content table, and caches the result. Caching is safe because a
``rule_set_id``'s stored rows are immutable: the content tables are append-only
and ``insert_candidate`` returns early for an id that already has a receipt.
Only the tip pointer needs invalidating, which happens on activate.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery

from BigQuery.mapping_rule_rows import (
    ENTITIES_CURRENT_TABLE,
    ENTITIES_TABLE,
    LEAGUES_TABLE,
    MARKET_RULES_TABLE,
    RULE_SETS_TABLE,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.seed.league_meta import league_settings_from_exchanges

ENTITIES = "entities"
LEAGUES = "leagues"
MARKET_RULES = "market_rules"

# Chain depth is ~50 today; chunk anyway so a deep lineage cannot blow the
# query-parameter limit.
_ID_CHUNK = 500

QueryFn = Callable[[str, list[Any] | None], list[Any]]

_PARENTS_SQL = f"""
select rule_set_id, parent_rule_set_id from `{RULE_SETS_TABLE}`
"""  # nosec B608 — table name is a module constant

# ORDER BY keeps within-layer row order identical to the per-ancestor loaders,
# so coalesce results do not change.
_ENTITIES_SQL = f"""
select rule_set_id, league, entity_type, canonical_key, canonical_name,
       enabled, aliases, notes, ifnull(tombstone, false) as tombstone
from `{ENTITIES_TABLE}` where rule_set_id in unnest(@ids)
order by rule_set_id, league, entity_type, canonical_key
"""  # nosec B608

_LEAGUES_SQL = f"""
select rule_set_id, league, sport, optic_league_id, extra_optic_league_ids,
       fixture_source, fixture_horizon_hours, enabled, output_order,
       exchanges, notes, ifnull(tombstone, false) as tombstone
from `{LEAGUES_TABLE}` where rule_set_id in unnest(@ids)
order by rule_set_id, league
"""  # nosec B608

# mapping_entities_current holds the tip already coalesced. `false as tombstone`
# lets these rows share the EntityRow builder: the table only ever stores live
# rows, because coalesce drops a tombstoned key rather than emitting it.
_ENTITIES_CURRENT_SQL = f"""
select rule_set_id, league, entity_type, canonical_key, canonical_name,
       enabled, aliases, notes, false as tombstone, ordinal
from `{ENTITIES_CURRENT_TABLE}`
order by ordinal
"""  # nosec B608

_MARKET_RULES_SQL = f"""
select rule_set_id, rule_id, rule_group_id, league, sportsbook, rule_kind,
       source_key_type, source_key, action, canonical_market_type, priority,
       enabled, confidence, match_operator, market_family, notes, settlement_note,
       line_offset, yes_side, side_swap, official_description, citation_url,
       ifnull(tombstone, false) as tombstone
from `{MARKET_RULES_TABLE}` where rule_set_id in unnest(@ids)
order by rule_set_id, league, sportsbook, priority, source_key
"""  # nosec B608


def _alias_dict(alias: Any) -> dict[str, Any]:
    """Normalize a nested BigQuery record to a plain dict."""
    return dict(alias.items()) if hasattr(alias, "items") else dict(alias)


def entity_row(row: Any) -> EntityRow:
    """Build an EntityRow from one BigQuery result row."""
    return EntityRow(
        league=str(row.league),
        entity_type=str(row.entity_type),
        canonical_key=str(row.canonical_key),
        canonical_name=row.canonical_name,
        aliases=[_alias_dict(alias) for alias in row.aliases or []],
        enabled=bool(row.enabled),
        notes=row.notes,
        tombstone=bool(row.tombstone),
    )


def league_row(row: Any) -> LeagueRow:
    """Build a LeagueRow from one BigQuery result row."""
    exchanges = [_alias_dict(ex) for ex in row.exchanges or []]
    settings = dict(getattr(row, "settings", None) or {})
    if not settings:
        settings = league_settings_from_exchanges(exchanges)
    return LeagueRow(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=str(row.optic_league_id),
        extra_optic_league_ids=list(row.extra_optic_league_ids or []),
        fixture_source=str(row.fixture_source),
        fixture_horizon_hours=float(row.fixture_horizon_hours or 0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order or []),
        exchanges=exchanges,
        notes=row.notes,
        tombstone=bool(row.tombstone),
        settings=settings,
    )


def _optional_float(value: Any) -> float | None:
    """Null line offset when the cell is blank."""
    if value is None or value == "":
        return None
    return float(value)


def _optional_text(value: Any) -> str | None:
    """Null yes-side when the cell is blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    """Null side-swap when the cell is blank. False is a real value."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        return None
    return bool(value)


def market_rule_row(row: Any) -> MarketRuleRow:
    """Build a MarketRuleRow from one BigQuery result row."""
    return MarketRuleRow(
        rule_id=str(row.rule_id),
        league=row.league,
        sportsbook=str(row.sportsbook),
        rule_kind=str(row.rule_kind),
        source_key_type=str(row.source_key_type),
        source_key=str(row.source_key),
        action=str(row.action),
        canonical_market_type=row.canonical_market_type,
        priority=int(row.priority or 0),
        enabled=bool(row.enabled),
        confidence=str(row.confidence or "manual"),
        match_operator=str(row.match_operator or "exact"),
        notes=row.notes,
        tombstone=bool(row.tombstone),
        line_offset=_optional_float(getattr(row, "line_offset", None)),
        yes_side=_optional_text(getattr(row, "yes_side", None)),
        side_swap=_optional_bool(getattr(row, "side_swap", None)),
        official_description=_optional_text(getattr(row, "official_description", None)),
        citation_url=_optional_text(getattr(row, "citation_url", None)),
        rule_group_id=_optional_text(getattr(row, "rule_group_id", None)),
        market_family=_optional_text(getattr(row, "market_family", None)),
        settlement_note=_optional_text(getattr(row, "settlement_note", None)),
    )


def market_rule_insert_row(rule_set_id: str, row: MarketRuleRow) -> dict[str, Any]:
    """Candidate-table row. Preserves columns the console pin does not edit."""
    return {
        "rule_set_id": rule_set_id,
        "rule_id": row.rule_id,
        "rule_group_id": row.rule_group_id,
        "league": row.league,
        "sportsbook": row.sportsbook,
        "rule_kind": row.rule_kind,
        "source_key_type": row.source_key_type,
        "source_key": row.source_key,
        "match_operator": row.match_operator,
        "market_family": row.market_family,
        "canonical_market_type": row.canonical_market_type,
        "action": row.action,
        "priority": row.priority,
        "enabled": row.enabled,
        "confidence": row.confidence,
        "notes": row.notes,
        "settlement_note": row.settlement_note,
        "line_offset": row.line_offset,
        "yes_side": row.yes_side,
        "side_swap": row.side_swap,
        "official_description": row.official_description,
        "citation_url": row.citation_url,
        "tombstone": bool(row.tombstone),
    }


_LOADERS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    ENTITIES: (_ENTITIES_SQL, entity_row),
    LEAGUES: (_LEAGUES_SQL, league_row),
    MARKET_RULES: (_MARKET_RULES_SQL, market_rule_row),
}


def _chunks(ids: Sequence[str]) -> Iterator[Sequence[str]]:
    """Split ids into query-parameter sized batches."""
    for start in range(0, len(ids), _ID_CHUNK):
        yield ids[start : start + _ID_CHUNK]


def fetch_layers(query: QueryFn, kind: str, ids: Sequence[str]) -> dict[str, list[Any]]:
    """Load rows for many rule_set_ids at once, grouped by rule_set_id."""
    sql, build = _LOADERS[kind]
    grouped: dict[str, list[Any]] = {rid: [] for rid in ids}
    for chunk in _chunks(ids):
        params = [bigquery.ArrayQueryParameter("ids", "STRING", list(chunk))]
        for row in query(sql, params):
            grouped.setdefault(str(row.rule_set_id), []).append(build(row))
    return grouped


def walk_lineage(parents: dict[str, str | None], rule_set_id: str) -> list[str]:
    """Tip → root chain; stops on a cycle or an unknown parent."""
    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = rule_set_id
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parents.get(cur)
    return chain


@dataclass(frozen=True)
class EntityBase:
    """``mapping_entities_current`` as a pre-coalesced layer for one ancestor."""

    rule_set_id: str
    rows: list[EntityRow]


def load_entity_base(query: QueryFn) -> EntityBase | None:
    """Read the materialized tip, or None when it cannot stand in for a walk.

    The table is a disposable cache: Terraform can replace it and leave it empty
    until the next activation, and rows written before ``ordinal`` existed cannot
    reproduce the coalesce order. Both cases return None so the caller walks the
    lineage instead. A stale-but-complete base is still safe — it is a truthful
    coalesce of *some* ancestor, and the caller only uses it as one.

    Query failures are swallowed for the same reason. This is an optimization on
    top of a correct walk, so an image running ahead of the Terraform apply (no
    ``ordinal`` column yet) should lose the shortcut, not the read.
    """
    try:
        rows = list(query(_ENTITIES_CURRENT_SQL, None))
    except GoogleAPICallError:
        return None
    if not rows:
        return None
    stamps = {str(row.rule_set_id) for row in rows}
    if len(stamps) != 1 or any(row.ordinal is None for row in rows):
        return None
    return EntityBase(stamps.pop(), [entity_row(row) for row in rows])


class LayerCache:
    """Process-local COW layer + tip cache shared by every console request.

    Callers must treat returned layers as read-only; ``coalesce_*`` deepcopies
    rows on the way out, so no caller ever sees a cached object.
    """

    def __init__(self, *, tip_ttl_sec: float = 15.0) -> None:
        """Cache layers forever; bound only the tip pointer by TTL."""
        self._lock = threading.RLock()
        self._tip_ttl = max(0.0, tip_ttl_sec)
        self._parents: dict[str, str | None] = {}
        self._layers: dict[str, dict[str, list[Any]]] = {kind: {} for kind in _LOADERS}
        self._tip: tuple[float, str | None] | None = None
        self._base: EntityBase | None = None
        self._base_loaded = False

    def clear(self) -> None:
        """Drop everything (tests / forced refresh)."""
        with self._lock:
            self._tip = None
            self._parents = {}
            self._base = None
            self._base_loaded = False
            for cached in self._layers.values():
                cached.clear()

    def invalidate_tip(self) -> None:
        """Force the next tip read to re-query."""
        with self._lock:
            self._tip = None

    def set_tip(self, rule_set_id: str | None) -> None:
        """Record a tip we just activated, avoiding a streaming-buffer race."""
        with self._lock:
            self._tip = (time.monotonic(), rule_set_id)

    def tip(self, load: Callable[[], str | None]) -> str | None:
        """Cached current tip; TTL-bounded and invalidated on activate."""
        now = time.monotonic()
        with self._lock:
            hit = self._tip
            if hit is not None and now - hit[0] < self._tip_ttl:
                return hit[1]
        value = load()
        with self._lock:
            self._tip = (time.monotonic(), value)
        return value

    def note_candidate(
        self,
        rule_set_id: str,
        parent_rule_set_id: str | None,
        layers: dict[str, list[Any]],
    ) -> None:
        """Seed a just-written candidate so reading it needs no round trip."""
        with self._lock:
            self._parents[rule_set_id] = parent_rule_set_id
            for kind, rows in layers.items():
                self._layers[kind][rule_set_id] = list(rows)

    def lineage(self, query: QueryFn, rule_set_id: str) -> list[str]:
        """Tip→root chain from the cached parent map, reloaded on an unknown id."""
        with self._lock:
            known = rule_set_id in self._parents
        if not known:
            self._load_parents(query)
        with self._lock:
            return walk_lineage(self._parents, rule_set_id)

    def _load_parents(self, query: QueryFn) -> None:
        """Refresh the whole parent map in one query (the table is tiny)."""
        fetched = {
            str(row.rule_set_id): (
                str(row.parent_rule_set_id) if row.parent_rule_set_id else None
            )
            for row in query(_PARENTS_SQL, None)
        }
        with self._lock:
            # Keep locally seeded candidates the query may not see yet.
            for key, value in self._parents.items():
                fetched.setdefault(key, value)
            self._parents = fetched

    def set_entity_base(self, rule_set_id: str, rows: Sequence[EntityRow]) -> None:
        """Record a base we just materialized, saving the read-back query."""
        with self._lock:
            self._base = EntityBase(rule_set_id, list(rows))
            self._base_loaded = True

    def entity_base(self, query: QueryFn) -> EntityBase | None:
        """Materialized tip, loaded at most once per process."""
        with self._lock:
            if self._base_loaded:
                return self._base
        base = load_entity_base(query)
        with self._lock:
            if not self._base_loaded:
                self._base, self._base_loaded = base, True
            return self._base

    def entity_layers(self, query: QueryFn, rule_set_id: str) -> list[list[Any]]:
        """Entity layers tip→root, ending at the base when it is an ancestor.

        Substituting the base for the tail is exact rather than approximate: its
        rows are the coalesce of that ancestor in ``ordinal`` order, which is the
        same sequence the skipped layers would have produced. Coalesce still sees
        every newer layer first, so newer edits and tombstones win as before.
        """
        ids = self.lineage(query, rule_set_id)
        base = self.entity_base(query)
        if base is None or base.rule_set_id not in ids:
            return self.layers(query, ENTITIES, ids)
        head = ids[: ids.index(base.rule_set_id)]
        return self.layers(query, ENTITIES, head) + [base.rows]

    def layers(self, query: QueryFn, kind: str, ids: Sequence[str]) -> list[list[Any]]:
        """Layers for ids in order, fetching only the ones not cached yet."""
        cached = self._layers[kind]
        with self._lock:
            missing = [rid for rid in ids if rid not in cached]
        if missing:
            fetched = fetch_layers(query, kind, missing)
            with self._lock:
                for rid in missing:
                    cached.setdefault(rid, fetched.get(rid, []))
        with self._lock:
            return [cached.get(rid, []) for rid in ids]
