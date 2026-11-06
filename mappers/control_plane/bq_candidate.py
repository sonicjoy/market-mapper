"""BigQuery candidate insert (COW deltas or legacy full clone)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mappers.control_plane.bq_cow import (
    sparse_entity_deltas,
    sparse_league_deltas,
    sparse_market_rule_deltas,
)
from mappers.control_plane.cow_diff import snapshot_change_counts
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.store import RuleSetReceipt


def insert_candidate(
    store: Any,
    *,
    parent_rule_set_id: str,
    proposal_id: str,
    entities: list[EntityRow] | None = None,
    leagues: list[LeagueRow] | None = None,
    market_rules: list[MarketRuleRow] | None = None,
) -> RuleSetReceipt:
    """Append candidate receipt; COW writes only deltas when enabled."""
    parent_ent = store.entities_for(parent_rule_set_id)
    parent_lg = store.leagues_for(parent_rule_set_id)
    parent_mr = store.market_rules_for(parent_rule_set_id)
    ent = entities if entities is not None else parent_ent
    lg = leagues if leagues is not None else parent_lg
    mr = market_rules if market_rules is not None else parent_mr
    sha = _logical_sha(ent, lg, mr)
    receipt = _candidate_receipt(store, parent_rule_set_id, proposal_id, sha)
    receipt.change_summary = snapshot_change_counts(
        parent_ent, ent, parent_lg, lg, parent_mr, mr
    )
    # Logical sizes are known here, so validate need not re-coalesce to count.
    receipt.entity_count = len(ent)
    receipt.league_count = len(lg)
    receipt.market_rule_count = len(mr)
    if store.get_receipt(receipt.rule_set_id) is not None:
        return receipt
    if store.cow_enabled:
        written = (
            sparse_entity_deltas(parent_ent, entities),
            sparse_league_deltas(parent_lg, leagues),
            sparse_market_rule_deltas(parent_mr, market_rules),
        )
    else:
        written = (ent, lg, mr)
    _write_layers(store, receipt, written)
    store._insert_receipt(
        receipt,
        entity_count=len(ent),
        league_count=len(lg),
        rule_count=len(mr),
    )
    return receipt


def _write_layers(
    store: Any,
    receipt: RuleSetReceipt,
    written: tuple[list[EntityRow], list[LeagueRow], list[MarketRuleRow]],
) -> None:
    """Persist the candidate's rows, then seed the layer cache with them."""
    ent, lg, mr = written
    store._insert_entities(receipt.rule_set_id, ent)
    store._insert_leagues(receipt.rule_set_id, lg)
    store._insert_market_rules(receipt.rule_set_id, mr)
    store.note_candidate(receipt, entities=ent, leagues=lg, market_rules=mr)


def _logical_sha(
    ent: list[EntityRow],
    lg: list[LeagueRow],
    mr: list[MarketRuleRow],
) -> str:
    payload = {
        "entities": [{k: v for k, v in e.__dict__.items() if k != "tombstone"} for e in ent],
        "leagues": [{k: v for k, v in row.__dict__.items() if k != "tombstone"} for row in lg],
        "market_rules": [{k: v for k, v in row.__dict__.items() if k != "tombstone"} for row in mr],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _candidate_receipt(
    store: Any,
    parent_id: str,
    proposal_id: str,
    sha: str,
) -> RuleSetReceipt:
    return RuleSetReceipt(
        rule_set_id=f"P_{sha[:12]}",
        parent_rule_set_id=parent_id,
        snapshot_sha256=sha,
        proposal_ids=[proposal_id],
        created_via="ui",
        environment=store.environment,
    )


