"""In-memory proposal / rule-set store for control-plane tests.

Supports Git-style COW: seed stores a dense base; candidates store only
deltas (upserts + tombstones) when ``cow=True``. Reads always reconstruct
the logical snapshot via tip→root last-write-wins — ``cow=False`` only
changes what ``insert_candidate`` persists, not how ``*_for`` reads.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from mappers.control_plane.cow_diff import (
    diff_entities,
    diff_leagues,
    diff_market_rules,
    snapshot_change_counts,
)
from mappers.control_plane.cow_rebuild import (
    coalesce_entities,
    coalesce_leagues,
    coalesce_market_rules,
)
from mappers.control_plane.cow_validity import (
    InMemoryValidityStore,
    ValidityWindow,
    opens_for_activation,
)
from mappers.control_plane.models import ProposalRecord
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow

PARITY_EVENT_TYPES = frozenset(
    {
        "rule_parity_mismatch",
        "rule_parity_ok",
        "tip_alignment_stale",
        "tip_alignment_ok",
    }
)
_PARITY_OK_EVENT_TYPES = frozenset({"rule_parity_ok", "tip_alignment_ok"})


def _parity_event_view(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize an audit row for the console Parity page."""
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    raw_count = payload.get("mismatch_count")
    if raw_count is None and row.get("event_type") in _PARITY_OK_EVENT_TYPES:
        mismatch_count = 0
    elif raw_count is None:
        mismatches = payload.get("mismatches") or []
        mismatch_count = len(mismatches) if isinstance(mismatches, list) else 0
    else:
        mismatch_count = int(raw_count)
    return {
        "event_id": row.get("event_id"),
        "event_type": row.get("event_type"),
        "occurred_at": row.get("occurred_at"),
        "rule_set_id": row.get("rule_set_id"),
        "league": row.get("league"),
        "sportsbook": row.get("sportsbook"),
        "reason_code": row.get("reason_code"),
        "mismatch_count": mismatch_count,
        "payload": payload,
    }


def _now() -> str:
    """UTC ISO timestamp for audit rows."""
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    """Allocate a short prefixed opaque id."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class WorkItemRow:
    """One mapping_work_items inbox row."""

    work_item_id: str
    fingerprint: str
    source: str
    status: str
    league: str | None = None
    sportsbook: str | None = None
    severity: str | None = None
    request_extraction: dict[str, Any] | None = None
    proposal_id: str | None = None
    gap_event_id: str | None = None
    occurrence_count: int = 1
    summary: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_seen_at: str | None = None


@dataclass
class RuleSetReceipt:
    """Immutable rule-set receipt (mirrors mapping_rule_sets)."""

    rule_set_id: str
    parent_rule_set_id: str | None
    snapshot_sha256: str
    proposal_ids: list[str]
    created_via: str
    environment: str
    activated: bool = False
    change_summary: dict[str, int] | None = None
    # Logical sizes recorded at insert so validate need not re-coalesce.
    entity_count: int | None = None
    league_count: int | None = None
    market_rule_count: int | None = None


class ProposalStore(Protocol):
    """Persistence contract used by the control-plane service."""

    environment: str
    allow_activate: bool
    audits: list[dict[str, Any]]

    @property
    def current_rule_set_id(self) -> str | None: ...

    def append_audit(self, event: dict[str, Any]) -> None: ...

    def get_proposal_by_request(self, request_id: str) -> ProposalRecord | None: ...

    def put_proposal(self, proposal: ProposalRecord) -> None: ...

    def get_proposal(self, proposal_id: str) -> ProposalRecord | None: ...

    def list_proposals(self) -> list[ProposalRecord]: ...

    def entities_for(self, rule_set_id: str) -> list[EntityRow]: ...

    def leagues_for(self, rule_set_id: str) -> list[LeagueRow]: ...

    def market_rules_for(self, rule_set_id: str) -> list[MarketRuleRow]: ...

    def insert_candidate(
        self,
        *,
        parent_rule_set_id: str,
        proposal_id: str,
        entities: list[EntityRow] | None = None,
        leagues: list[LeagueRow] | None = None,
        market_rules: list[MarketRuleRow] | None = None,
    ) -> RuleSetReceipt: ...

    def activate(self, rule_set_id: str) -> None: ...

    @property
    def activated_rule_set_id(self) -> str | None: ...

    def get_receipt(self, rule_set_id: str) -> RuleSetReceipt | None: ...

    def list_work_items(self, *, status: str | None = None) -> list[WorkItemRow]: ...

    def get_work_item(self, work_item_id: str) -> WorkItemRow | None: ...

    def put_work_item(self, item: WorkItemRow) -> None: ...

    def list_parity_events(self, *, limit: int = 50) -> list[dict[str, Any]]: ...


def _snapshot_sha(
    entities: list[EntityRow],
    leagues: list[LeagueRow],
    market_rules: list[MarketRuleRow],
) -> str:
    """Content hash for candidate rule_set_id derivation (logical full)."""
    payload = {
        "entities": [{k: v for k, v in e.__dict__.items() if k != "tombstone"} for e in entities],
        "leagues": [{k: v for k, v in league.__dict__.items() if k != "tombstone"} for league in leagues],
        "market_rules": [
            {k: v for k, v in rule.__dict__.items() if k != "tombstone"} for rule in market_rules
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class InMemoryStore:
    """Append-only-ish store for unit tests and local dry-runs (COW by default)."""

    environment: str = "test"
    allow_activate: bool = True
    cow: bool = True
    rule_sets: dict[str, RuleSetReceipt] = field(default_factory=dict)
    entities: dict[str, list[EntityRow]] = field(default_factory=dict)
    leagues: dict[str, list[LeagueRow]] = field(default_factory=dict)
    market_rules: dict[str, list[MarketRuleRow]] = field(default_factory=dict)
    proposals: dict[str, ProposalRecord] = field(default_factory=dict)
    work_items: dict[str, WorkItemRow] = field(default_factory=dict)
    audits: list[dict[str, Any]] = field(default_factory=list)
    current_entities: list[EntityRow] = field(default_factory=list)
    current_leagues: list[LeagueRow] = field(default_factory=list)
    current_market_rules: list[MarketRuleRow] = field(default_factory=list)
    validity: InMemoryValidityStore = field(default_factory=InMemoryValidityStore)
    _current_rule_set_id: str | None = None
    _request_index: dict[str, str] = field(default_factory=dict)
    _fingerprint_index: dict[str, str] = field(default_factory=dict)

    def seed_rule_set(
        self,
        *,
        rule_set_id: str,
        entities: list[EntityRow],
        leagues: list[LeagueRow] | None = None,
        market_rules: list[MarketRuleRow] | None = None,
        activate: bool = False,
    ) -> None:
        """Install a dense baseline shadow (or active) rule set."""
        league_rows = leagues or []
        rule_rows = market_rules or []
        sha = _snapshot_sha(entities, league_rows, rule_rows)
        self.rule_sets[rule_set_id] = RuleSetReceipt(
            rule_set_id=rule_set_id,
            parent_rule_set_id=None,
            snapshot_sha256=sha,
            proposal_ids=[],
            created_via="seed",
            environment=self.environment,
            activated=activate,
        )
        self.entities[rule_set_id] = deepcopy(entities)
        self.leagues[rule_set_id] = deepcopy(league_rows)
        self.market_rules[rule_set_id] = deepcopy(rule_rows)
        if activate or self._current_rule_set_id is None:
            self._current_rule_set_id = rule_set_id
            if activate:
                self._materialize(rule_set_id)

    def _lineage_ids(self, rule_set_id: str) -> list[str]:
        """Tip → root rule_set_id chain."""
        chain: list[str] = []
        seen: set[str] = set()
        cur: str | None = rule_set_id
        while cur and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            receipt = self.rule_sets.get(cur)
            cur = receipt.parent_rule_set_id if receipt else None
        return chain

    @property
    def current_rule_set_id(self) -> str | None:
        """Latest shadow/active rule set id for optimistic concurrency."""
        return self._current_rule_set_id

    @property
    def activated_rule_set_id(self) -> str | None:
        """Activated tip only; seed fallback is not an activation."""
        rid = self._current_rule_set_id
        if rid is None:
            return None
        rec = self.rule_sets.get(rid)
        if rec is not None and rec.activated:
            return rid
        return None

    def append_audit(self, event: dict[str, Any]) -> None:
        """Append one mapping_audit_events-shaped row."""
        self.audits.append(
            {
                "event_id": new_id("evt"),
                "occurred_at": _now(),
                "environment": self.environment,
                **event,
            }
        )

    def get_proposal_by_request(self, request_id: str) -> ProposalRecord | None:
        """Idempotent lookup by request_id."""
        pid = self._request_index.get(request_id)
        return self.proposals.get(pid) if pid else None

    def put_proposal(self, proposal: ProposalRecord) -> None:
        """Upsert a proposal and index its request_id."""
        self.proposals[proposal.proposal_id] = proposal
        self._request_index[proposal.request_id] = proposal.proposal_id

    def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        """Fetch one proposal by id."""
        return self.proposals.get(proposal_id)

    def list_proposals(self) -> list[ProposalRecord]:
        """Return all proposals (review queue stand-in)."""
        return list(self.proposals.values())

    def entities_for(self, rule_set_id: str) -> list[EntityRow]:
        """Logical entities (always tip→root COW coalesce)."""
        layers = [self.entities.get(rid, []) for rid in self._lineage_ids(rule_set_id)]
        return coalesce_entities(layers)

    def leagues_for(self, rule_set_id: str) -> list[LeagueRow]:
        """Logical leagues (always tip→root COW coalesce)."""
        layers = [self.leagues.get(rid, []) for rid in self._lineage_ids(rule_set_id)]
        return coalesce_leagues(layers)

    def market_rules_for(self, rule_set_id: str) -> list[MarketRuleRow]:
        """Logical market rules (always tip→root COW coalesce)."""
        layers = [self.market_rules.get(rid, []) for rid in self._lineage_ids(rule_set_id)]
        return coalesce_market_rules(layers)

    def stored_entity_deltas(self, rule_set_id: str) -> list[EntityRow]:
        """Raw stored entity rows (deltas only under COW) — for write-size tests."""
        return deepcopy(self.entities.get(rule_set_id, []))

    def insert_candidate(
        self,
        *,
        parent_rule_set_id: str,
        proposal_id: str,
        entities: list[EntityRow] | None = None,
        leagues: list[LeagueRow] | None = None,
        market_rules: list[MarketRuleRow] | None = None,
    ) -> RuleSetReceipt:
        """Insert a candidate; under COW persist only deltas vs parent."""
        parent_ent = self.entities_for(parent_rule_set_id)
        parent_lg = self.leagues_for(parent_rule_set_id)
        parent_mr = self.market_rules_for(parent_rule_set_id)
        ent = entities if entities is not None else parent_ent
        lg = leagues if leagues is not None else parent_lg
        mr = market_rules if market_rules is not None else parent_mr
        sha = _snapshot_sha(ent, lg, mr)
        rule_set_id = f"P_{sha[:12]}"
        receipt = RuleSetReceipt(
            rule_set_id=rule_set_id,
            parent_rule_set_id=parent_rule_set_id,
            snapshot_sha256=sha,
            proposal_ids=[proposal_id],
            created_via="proposal",
            environment=self.environment,
            activated=False,
            change_summary=snapshot_change_counts(
                parent_ent, ent, parent_lg, lg, parent_mr, mr
            ),
            entity_count=len(ent),
            league_count=len(lg),
            market_rule_count=len(mr),
        )
        self.rule_sets[rule_set_id] = receipt
        if self.cow:
            self.entities[rule_set_id] = (
                diff_entities(parent_ent, ent) if entities is not None else []
            )
            self.leagues[rule_set_id] = (
                diff_leagues(parent_lg, lg) if leagues is not None else []
            )
            self.market_rules[rule_set_id] = (
                diff_market_rules(parent_mr, mr) if market_rules is not None else []
            )
        else:
            self.entities[rule_set_id] = deepcopy(ent)
            self.leagues[rule_set_id] = deepcopy(lg)
            self.market_rules[rule_set_id] = deepcopy(mr)
        return receipt

    def _materialize(self, rule_set_id: str) -> None:
        """Refresh in-memory *_current caches from coalesced tip."""
        self.current_entities = self.entities_for(rule_set_id)
        self.current_leagues = self.leagues_for(rule_set_id)
        self.current_market_rules = self.market_rules_for(rule_set_id)

    def activate(self, rule_set_id: str) -> None:
        """Mark rule set current; materialize + stamp validity opens."""
        if not self.allow_activate:
            raise RuntimeError("activation disabled for this environment")
        previous_id = self._current_rule_set_id
        prev_ent = self.entities_for(previous_id) if previous_id else []
        prev_lg = self.leagues_for(previous_id) if previous_id else []
        prev_mr = self.market_rules_for(previous_id) if previous_id else []
        self.rule_sets[rule_set_id].activated = True
        self._current_rule_set_id = rule_set_id
        next_ent = self.entities_for(rule_set_id)
        next_lg = self.leagues_for(rule_set_id)
        next_mr = self.market_rules_for(rule_set_id)
        self._materialize(rule_set_id)
        opens = opens_for_activation(
            environment=self.environment,
            introduced_in_rule_set_id=rule_set_id,
            previous_entities=prev_ent,
            next_entities=next_ent,
            previous_leagues=prev_lg,
            next_leagues=next_lg,
            previous_market_rules=prev_mr,
            next_market_rules=next_mr,
        )
        self.validity.append_opens(opens)

    def rule_set_as_of(self, ts: str) -> str | None:
        """Latest activated/rolled-back rule_set_id with occurred_at <= ts."""
        events = [
            a
            for a in self.audits
            if a.get("event_type") in {"rule_set_activated", "rule_set_rolled_back"}
            and str(a.get("occurred_at", "")) <= ts
        ]
        if not events:
            return self._current_rule_set_id
        events.sort(key=lambda a: (str(a.get("occurred_at")), str(a.get("event_id"))))
        return str(events[-1].get("rule_set_id")) if events[-1].get("rule_set_id") else None

    def rule_history(self, *, table_kind: str, natural_key: str) -> list[ValidityWindow]:
        """On/off windows for one natural key."""
        return self.validity.history(table_kind=table_kind, natural_key=natural_key)

    def get_receipt(self, rule_set_id: str) -> RuleSetReceipt | None:
        """Return one rule-set receipt."""
        return self.rule_sets.get(rule_set_id)

    def list_work_items(self, *, status: str | None = None) -> list[WorkItemRow]:
        """Return inbox items, optionally filtered by status."""
        items = list(self.work_items.values())
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get_work_item(self, work_item_id: str) -> WorkItemRow | None:
        """Fetch one work item."""
        return self.work_items.get(work_item_id)

    def put_work_item(self, item: WorkItemRow) -> None:
        """Upsert a work item and index fingerprint."""
        self.work_items[item.work_item_id] = item
        self._fingerprint_index[item.fingerprint] = item.work_item_id

    def work_item_by_fingerprint(self, fingerprint: str) -> WorkItemRow | None:
        """Lookup by fingerprint for ingest upsert."""
        wid = self._fingerprint_index.get(fingerprint)
        return self.work_items.get(wid) if wid else None

    def list_parity_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent parity/tip-alignment audits, newest first."""
        rows = [a for a in self.audits if a.get("event_type") in PARITY_EVENT_TYPES]
        return [_parity_event_view(a) for a in reversed(rows[-limit:])]
