"""Shape a seed snapshot (Milestone 1 IR) into BigQuery row dicts.

Pure transforms — no BigQuery dependency, so the row shapes are unit
testable without credentials.  Column sets mirror the Terraform schemas
in mm-infrastructure (`modules/general_us/schemas/markets/mapping_*.sql`).
"""

from __future__ import annotations

import uuid
from typing import Any

from mappers.seed.models import SnapshotIR

RULE_SETS_TABLE = "markets_us.mapping_rule_sets"
LEAGUES_TABLE = "markets_us.mapping_leagues"
MARKET_RULES_TABLE = "markets_us.mapping_market_rules"
ENTITIES_TABLE = "markets_us.mapping_entities"
AUDIT_EVENTS_TABLE = "markets_us.mapping_audit_events"
WORK_ITEMS_TABLE = "markets_us.mapping_work_items"
VALIDITY_TABLE = "markets_us.mapping_rule_validity"
ENTITIES_CURRENT_TABLE = "markets_us.mapping_entities_current"
HARVEST_TTL_TABLE = "markets_us.mapping_harvest_ttl"

# Written on seed.  Activation is a separate event type that this module
# never emits — `mapping_rule_current` stays empty until a trader flips it.
SEEDED_EVENT_TYPE = "rule_set_seeded"


def rule_set_row(
    snap: SnapshotIR,
    *,
    environment: str,
    source_revision: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_set_id": snap.rule_set_id,
        "parent_rule_set_id": None,
        "snapshot_sha256": snap.snapshot_sha256,
        "source_revision": source_revision,
        "created_via": snap.created_via,
        "proposal_ids": [],
        "engine_contract_version": snap.engine_contract_version,
        "expected_league_count": len(snap.leagues),
        "expected_market_rule_count": len(snap.market_rules),
        "expected_entity_count": len(snap.entities),
        "canonical_markets": snap.canonical_markets,
        "created_at": snap.created_at,
        "created_by": snap.created_by,
        "notes": notes,
        "environment": environment,
    }


def _exchange_row(ex: Any) -> dict[str, Any]:
    return {
        "sportsbook": ex.sportsbook,
        "enabled": ex.enabled,
        "parser_profile": ex.parser_profile,
        "settings_schema_version": ex.settings_schema_version,
        "source_league_id": ex.source_league_id,
        "market_rule_group_ids": list(ex.market_rule_group_ids),
        "settings": ex.settings,
        "gap_profile": None,
        "gap_policies": [],
        "notes": None,
    }


def league_rows(snap: SnapshotIR) -> list[dict[str, Any]]:
    return [
        {
            "rule_set_id": snap.rule_set_id,
            "league": lg.league,
            "sport": lg.sport,
            "optic_league_id": lg.optic_league_id,
            "extra_optic_league_ids": list(lg.extra_optic_league_ids),
            "fixture_source": lg.fixture_source,
            "fixture_horizon_hours": lg.fixture_horizon_hours,
            "enabled": lg.enabled,
            "output_order": list(lg.output_order),
            "exchanges": [_exchange_row(ex) for ex in lg.exchanges],
            "fixture_overrides": [],
            "crosswalk_rules": [],
            "notes": lg.notes,
            "settings": dict(lg.settings or {}),
        }
        for lg in snap.leagues
    ]


def market_rule_rows(snap: SnapshotIR) -> list[dict[str, Any]]:
    return [
        {
            "rule_set_id": snap.rule_set_id,
            "rule_id": r.rule_id,
            "rule_group_id": r.rule_group_id,
            "league": r.league,
            "sportsbook": r.sportsbook,
            "rule_kind": r.rule_kind,
            "source_key_type": r.source_key_type,
            "source_key": r.source_key,
            "source_selection_key": None,
            "match_operator": r.match_operator,
            "market_family": r.market_family,
            "period": None,
            "effective_from_date": None,
            "effective_to_date": None,
            "canonical_market_type": r.canonical_market_type,
            "target_optic_odd_id": None,
            "action": r.action,
            "priority": r.priority,
            "enabled": r.enabled,
            "confidence": r.confidence,
            "evidence_refs": [],
            "created_from_gap_event_id": None,
            "proposal_id": None,
            "notes": r.notes,
            "settlement_note": r.settlement_note,
            "line_offset": r.line_offset,
            "yes_side": r.yes_side,
            "side_swap": r.side_swap,
            "official_description": r.official_description,
            "citation_url": r.citation_url,
        }
        for r in snap.market_rules
    ]


def _alias_row(alias: Any) -> dict[str, Any]:
    return {
        "alias_id": alias.alias_id,
        "sportsbook": alias.sportsbook,
        "alias_kind": alias.alias_kind,
        "alias_value": alias.alias_value,
        "normalized_alias_value": None,
        "normalization_profile": alias.normalization_profile,
        "disambiguation_id": None,
        "disambiguation_name": None,
        "priority": None,
        "enabled": alias.enabled,
        "confidence": alias.confidence,
        "evidence_refs": [],
        "created_from_gap_event_id": None,
        "proposal_id": None,
        "notes": None,
    }


def entity_rows(snap: SnapshotIR) -> list[dict[str, Any]]:
    return [
        {
            "rule_set_id": snap.rule_set_id,
            "league": e.league,
            "entity_type": e.entity_type,
            "canonical_key": e.canonical_key,
            "canonical_name": e.canonical_name,
            "enabled": e.enabled,
            "aliases": [_alias_row(a) for a in e.aliases],
            "notes": None,
        }
        for e in snap.entities
    ]


def seeded_event_row(
    snap: SnapshotIR,
    *,
    environment: str,
    occurred_at: str,
    actor_subject: str | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Audit receipt for a shadow load.  Never activates the rule set."""
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "request_id": snap.rule_set_id,
        "event_type": SEEDED_EVENT_TYPE,
        "occurred_at": occurred_at,
        "environment": environment,
        "rule_set_id": snap.rule_set_id,
        "previous_rule_set_id": None,
        "expected_rule_set_id": None,
        "proposal_id": None,
        "mapping_run_id": None,
        "mapping_key_hash": None,
        "league": None,
        "sportsbook": None,
        "artifact_type": "rule_set",
        "artifact_id": snap.rule_set_id,
        "actor_subject": actor_subject,
        "actor_role": "service",
        "status": "shadow",
        "reason_code": None,
        "payload": {
            "snapshot_sha256": snap.snapshot_sha256,
            "engine_contract_version": snap.engine_contract_version,
            "source_revision": source_revision,
            "league_count": len(snap.leagues),
            "market_rule_count": len(snap.market_rules),
            "entity_count": len(snap.entities),
            "missing_profiles": snap.missing_profiles,
        },
    }
