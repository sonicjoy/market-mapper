"""BigQuery helpers for Git-style COW rule storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.mapping_rule_rows import (
    ENTITIES_CURRENT_TABLE,
    ENTITIES_TABLE,
    LEAGUES_TABLE,
    MARKET_RULES_TABLE,
    RULE_SETS_TABLE,
    VALIDITY_TABLE,
)
from mappers.control_plane.cow_diff import (
    diff_entities,
    diff_leagues,
    diff_market_rules,
)
from mappers.control_plane.cow_rebuild import (
    coalesce_entities,
    coalesce_leagues,
    coalesce_market_rules,
)
from mappers.control_plane.cow_validity import ValidityOpen, ValidityWindow, validity_windows
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.store import RuleSetReceipt


def lineage_ids(
    get_receipt: Any,
    rule_set_id: str,
) -> list[str]:
    """Tip → root chain via mapping_rule_sets parents."""
    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = rule_set_id
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        receipt = get_receipt(cur)
        cur = receipt.parent_rule_set_id if receipt else None
    return chain


def sparse_entity_deltas(
    parent: list[EntityRow],
    child: list[EntityRow] | None,
) -> list[EntityRow]:
    """Deltas to persist when child is the full logical candidate."""
    if child is None:
        return []
    return diff_entities(parent, child)


def sparse_league_deltas(
    parent: list[LeagueRow],
    child: list[LeagueRow] | None,
) -> list[LeagueRow]:
    """League deltas for a candidate."""
    if child is None:
        return []
    return diff_leagues(parent, child)


def sparse_market_rule_deltas(
    parent: list[MarketRuleRow],
    child: list[MarketRuleRow] | None,
) -> list[MarketRuleRow]:
    """Market-rule deltas for a candidate."""
    if child is None:
        return []
    return diff_market_rules(parent, child)


def coalesce_entity_layers(layers: list[list[EntityRow]]) -> list[EntityRow]:
    """Tip→root entity coalesce."""
    return coalesce_entities(layers)


def coalesce_league_layers(layers: list[list[LeagueRow]]) -> list[LeagueRow]:
    """Tip→root league coalesce."""
    return coalesce_leagues(layers)


def coalesce_market_rule_layers(
    layers: list[list[MarketRuleRow]],
) -> list[MarketRuleRow]:
    """Tip→root market-rule coalesce."""
    return coalesce_market_rules(layers)


def entity_current_rows(rule_set_id: str, entities: list[EntityRow]) -> list[dict[str, Any]]:
    """JSON rows for mapping_entities_current (WRITE_TRUNCATE load).

    ``ordinal`` records the coalesced tip order so a reader can substitute this
    table for the tail of a COW walk and rebuild the identical row sequence.
    Entity order decides which canonical wins an alias claimed by several, so a
    reader that ignores it would silently re-resolve collisions.
    """
    now = datetime.now(UTC).isoformat()
    return [
        {
            "rule_set_id": rule_set_id,
            "league": entity.league,
            "entity_type": entity.entity_type,
            "canonical_key": entity.canonical_key,
            "canonical_name": entity.canonical_name,
            "enabled": entity.enabled,
            "aliases": entity.aliases,
            "notes": entity.notes,
            "materialized_at": now,
            "ordinal": ordinal,
        }
        for ordinal, entity in enumerate(e for e in entities if not e.tombstone)
    ]


def validity_json_rows(opens: list[ValidityOpen]) -> list[dict[str, Any]]:
    """JSON rows for mapping_rule_validity inserts."""
    rows: list[dict[str, Any]] = []
    for open_row in opens:
        rows.append(
            {
                "validity_id": open_row.validity_id,
                "table_kind": open_row.table_kind,
                "natural_key": open_row.natural_key,
                "introduced_in_rule_set_id": open_row.introduced_in_rule_set_id,
                "effective_from": open_row.effective_from,
                "enabled": open_row.enabled,
                "environment": open_row.environment,
                "league": open_row.league,
                "payload": json.dumps(open_row.payload) if open_row.payload is not None else None,
            }
        )
    return rows


def windows_from_bq_rows(rows: list[Any]) -> list[ValidityWindow]:
    """Build windows from ordered validity opens loaded from BQ."""
    opens = [
        ValidityOpen(
            validity_id=str(row.validity_id),
            table_kind=str(row.table_kind),
            natural_key=str(row.natural_key),
            introduced_in_rule_set_id=str(row.introduced_in_rule_set_id),
            effective_from=str(row.effective_from),
            enabled=bool(row.enabled),
            environment=str(row.environment),
            league=row.league,
            payload=None,
        )
        for row in rows
    ]
    return validity_windows(opens)


# Re-export table names used by callers that import this module.
__all__ = [
    "ENTITIES_CURRENT_TABLE",
    "ENTITIES_TABLE",
    "LEAGUES_TABLE",
    "MARKET_RULES_TABLE",
    "RULE_SETS_TABLE",
    "VALIDITY_TABLE",
    "coalesce_entity_layers",
    "coalesce_league_layers",
    "coalesce_market_rule_layers",
    "entity_current_rows",
    "lineage_ids",
    "sparse_entity_deltas",
    "sparse_league_deltas",
    "sparse_market_rule_deltas",
    "validity_json_rows",
    "windows_from_bq_rows",
    "RuleSetReceipt",
    "bigquery",
]
