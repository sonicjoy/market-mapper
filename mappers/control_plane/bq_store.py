"""BigQuery persistence adapter for the M3a control plane."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions as gax_exceptions
from google.cloud import bigquery

from BigQuery.mapping_rule_rows import (
    AUDIT_EVENTS_TABLE,
    ENTITIES_TABLE,
    LEAGUES_TABLE,
    MARKET_RULES_TABLE,
    RULE_SETS_TABLE,
    VALIDITY_TABLE,
)
from mappers.control_plane.bq_cow import (
    coalesce_entity_layers,
    coalesce_league_layers,
    coalesce_market_rule_layers,
    windows_from_bq_rows,
)
from mappers.control_plane.bq_layers import (
    ENTITIES,
    LEAGUES,
    MARKET_RULES,
    LayerCache,
    market_rule_insert_row,
)
from mappers.control_plane.bq_proposals import (
    LIST_PROPOSALS_SQL,
    proposal_from_events,
    proposals_from_audit_rows,
)
from mappers.control_plane.bq_work_items import BqWorkItemsMixin, QueryParameter
from mappers.control_plane.models import BigQueryUnavailableError, ProposalRecord
from mappers.control_plane.request_metrics import record_bq_job
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.store import (
    RuleSetReceipt,
    new_id,
)
from mappers.seed.league_meta import league_settings_from_row, merge_league_meta_into_exchanges

_TERMINAL_PROPOSAL = frozenset({"approved", "activated", "rejected", "changes_requested"})


class BigQueryStore(BqWorkItemsMixin):
    """Persist proposals, candidate snapshots, and audit events in BigQuery."""

    allow_activate: bool
    audits: list[dict[str, Any]]

    def __init__(
        self,
        client: bigquery.Client,
        *,
        environment: str,
        allow_activate: bool,
        cow_enabled: bool = True,
        tip_ttl_sec: float = 15.0,
        review_window_days: int = 365,
    ) -> None:
        """Bind the store to one project/environment."""
        self.client = client
        self.environment = environment
        self.allow_activate = allow_activate
        self.cow_enabled = cow_enabled
        self.review_window_days = review_window_days
        self.audits = []
        self._proposal_cache: dict[str, ProposalRecord] = {}
        self._request_index: dict[str, str] = {}
        self._layer_cache = LayerCache(tip_ttl_sec=tip_ttl_sec)

    def _query(
        self,
        sql: str,
        params: Sequence[QueryParameter] | None = None,
    ) -> list[Any]:
        """Execute a parameterized query and materialize its rows."""
        config = bigquery.QueryJobConfig(query_parameters=params or [])
        record_bq_job()
        try:
            return list(self.client.query(sql, job_config=config).result())
        except gax_exceptions.Forbidden as exc:
            raise BigQueryUnavailableError(str(exc)) from exc
        except gax_exceptions.GoogleAPICallError as exc:
            if "USER_PROJECT_DENIED" in str(exc) or "403" in str(exc):
                raise BigQueryUnavailableError(str(exc)) from exc
            raise

    @property
    def activated_rule_set_id(self) -> str | None:
        """Activated tip only; no seed fallback."""
        sql = f"""
        select rule_set_id from `{AUDIT_EVENTS_TABLE}`
        where environment = @environment
          and event_type in ('rule_set_activated', 'rule_set_rolled_back')
        order by occurred_at desc, event_id desc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("environment", "STRING", self.environment)]
        rows = self._query(sql, params)
        return str(rows[0].rule_set_id) if rows else None

    @property
    def current_rule_set_id(self) -> str | None:
        """Cached activated tip (TTL-bounded; set directly on activate)."""
        return self._layer_cache.tip(self._load_current_rule_set_id)

    def _load_current_rule_set_id(self) -> str | None:
        """Return activated tip, falling back to latest shadow seed."""
        tip = self.activated_rule_set_id
        if tip:
            return tip
        sql = f"""
        select rule_set_id from `{RULE_SETS_TABLE}`
        where environment = @environment
          and created_via in ('seed', 'loader')
        order by created_at desc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("environment", "STRING", self.environment)]
        rows = self._query(sql, params)
        return str(rows[0].rule_set_id) if rows else None

    def append_audit(self, event: dict[str, Any]) -> None:
        """Append one lifecycle event to mapping_audit_events."""
        row = {
            "event_id": new_id("evt"),
            "occurred_at": datetime.now(UTC).isoformat(),
            "environment": self.environment,
            "mapping_run_id": None,
            "mapping_key_hash": None,
            "league": None,
            "sportsbook": None,
            "artifact_type": None,
            "artifact_id": None,
            "reason_code": None,
            "payload": None,
            "previous_rule_set_id": None,
            "rule_set_id": None,
            **event,
        }
        if row["payload"] is not None and not isinstance(row["payload"], str):
            row["payload"] = json.dumps(row["payload"], sort_keys=True)
        errors = self.client.insert_rows_json(AUDIT_EVENTS_TABLE, [row])
        if errors:
            raise RuntimeError(f"mapping audit insert failed: {errors}")

    def get_proposal_by_request(self, request_id: str) -> ProposalRecord | None:
        """Find a proposal by idempotency request_id.

        Checks the in-process index first: a proposal written moments ago is
        still in the streaming buffer, so the audit query can miss it and let a
        retry mint a second card.
        """
        cached = self._request_index.get(request_id)
        if cached is not None:
            return self.get_proposal(cached)
        sql = f"""
        select proposal_id from `{AUDIT_EVENTS_TABLE}`
        where request_id = @request_id and event_type = 'rule_proposed'
        order by occurred_at asc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("request_id", "STRING", request_id)]
        rows = self._query(sql, params)
        return self.get_proposal(str(rows[0].proposal_id)) if rows else None

    def put_proposal(self, proposal: ProposalRecord) -> None:
        """Cache transient state; durable state comes from audit events."""
        self._proposal_cache[proposal.proposal_id] = proposal.model_copy(deep=True)
        self._request_index[proposal.request_id] = proposal.proposal_id

    def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        """Rehydrate one proposal from its append-only lifecycle events."""
        cached = self._proposal_cache.get(proposal_id)
        sql = f"""
        select event_type, occurred_at, rule_set_id, actor_subject,
               expected_rule_set_id, payload
        from `{AUDIT_EVENTS_TABLE}`
        where proposal_id = @proposal_id
        order by occurred_at asc, event_id asc
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("proposal_id", "STRING", proposal_id)]
        rows = self._query(sql, params)
        if not rows:
            return cached
        record = proposal_from_events(proposal_id, rows)
        if record is not None and record.status in _TERMINAL_PROPOSAL:
            return record
        return cached or record

    def list_proposals(self) -> list[ProposalRecord]:
        """Return proposals visible in the append-only audit stream."""
        params = [
            bigquery.ScalarQueryParameter("window_days", "INT64", self.review_window_days)
        ]
        return proposals_from_audit_rows(self._query(LIST_PROPOSALS_SQL, params))

    def _cached_layers(self, kind: str, rule_set_id: str) -> list[list[Any]]:
        """Tip→root layers for one kind, batched and cached by rule_set_id."""
        ids = self._layer_cache.lineage(self._query, rule_set_id)
        return self._layer_cache.layers(self._query, kind, ids)

    def note_candidate(
        self,
        receipt: RuleSetReceipt,
        *,
        entities: list[EntityRow],
        leagues: list[LeagueRow],
        market_rules: list[MarketRuleRow],
    ) -> None:
        """Seed the cache with a candidate's just-written deltas."""
        self._layer_cache.note_candidate(
            receipt.rule_set_id,
            receipt.parent_rule_set_id,
            {ENTITIES: entities, LEAGUES: leagues, MARKET_RULES: market_rules},
        )

    def note_entity_base(self, rule_set_id: str, entities: list[EntityRow]) -> None:
        """Seed the cache with the tip we just materialized."""
        self._layer_cache.set_entity_base(rule_set_id, entities)

    def entities_for(self, rule_set_id: str) -> list[EntityRow]:
        """Logical entities (tip→root COW coalesce, tail served by the base)."""
        return coalesce_entity_layers(
            self._layer_cache.entity_layers(self._query, rule_set_id)
        )

    def leagues_for(self, rule_set_id: str) -> list[LeagueRow]:
        """Logical leagues (always tip→root COW coalesce)."""
        return coalesce_league_layers(self._cached_layers(LEAGUES, rule_set_id))

    def market_rules_for(self, rule_set_id: str) -> list[MarketRuleRow]:
        """Logical market_rules (always tip→root COW coalesce)."""
        return coalesce_market_rule_layers(self._cached_layers(MARKET_RULES, rule_set_id))

    def insert_candidate(
        self,
        *,
        parent_rule_set_id: str,
        proposal_id: str,
        entities: list[EntityRow] | None = None,
        leagues: list[LeagueRow] | None = None,
        market_rules: list[MarketRuleRow] | None = None,
    ) -> RuleSetReceipt:
        """Append candidate receipt; COW writes only deltas (no full clone)."""
        from mappers.control_plane.bq_candidate import insert_candidate as _insert

        return _insert(
            self,
            parent_rule_set_id=parent_rule_set_id,
            proposal_id=proposal_id,
            entities=entities,
            leagues=leagues,
            market_rules=market_rules,
        )

    def _candidate_receipt(self, parent_id: str, proposal_id: str, sha: str) -> RuleSetReceipt:
        """Build deterministic candidate receipt."""
        return RuleSetReceipt(
            rule_set_id=f"P_{sha[:12]}",
            parent_rule_set_id=parent_id,
            snapshot_sha256=sha,
            proposal_ids=[proposal_id],
            created_via="ui",
            environment=self.environment,
        )

    def _insert_entities(self, rule_set_id: str, entities: list[EntityRow]) -> None:
        """Load candidate entity deltas (may include tombstones)."""
        if not entities:
            return
        rows = [
            {
                "rule_set_id": rule_set_id,
                "league": entity.league,
                "entity_type": entity.entity_type,
                "canonical_key": entity.canonical_key,
                "canonical_name": entity.canonical_name,
                "enabled": entity.enabled,
                "aliases": entity.aliases,
                "notes": entity.notes,
                "tombstone": bool(entity.tombstone),
            }
            for entity in entities
        ]
        job = self.client.load_table_from_json(rows, ENTITIES_TABLE)
        job.result()
        if job.errors:
            raise RuntimeError(f"candidate entity load failed: {job.errors}")

    def _insert_leagues(self, rule_set_id: str, leagues: list[LeagueRow]) -> None:
        """Load candidate league deltas."""
        if not leagues:
            return
        rows = [
            {
                "rule_set_id": rule_set_id,
                "league": row.league,
                "sport": row.sport,
                "optic_league_id": row.optic_league_id,
                "extra_optic_league_ids": row.extra_optic_league_ids,
                "fixture_source": row.fixture_source,
                "fixture_horizon_hours": row.fixture_horizon_hours,
                "enabled": row.enabled,
                "output_order": row.output_order,
                "exchanges": merge_league_meta_into_exchanges(
                    list(row.exchanges),
                    league_settings_from_row(row),
                ),
                "fixture_overrides": [],
                "crosswalk_rules": [],
                "notes": row.notes,
                "tombstone": bool(row.tombstone),
            }
            for row in leagues
        ]
        job = self.client.load_table_from_json(rows, LEAGUES_TABLE)
        job.result()
        if job.errors:
            raise RuntimeError(f"candidate league load failed: {job.errors}")

    def _insert_market_rules(self, rule_set_id: str, rules: list[MarketRuleRow]) -> None:
        """Load candidate market_rules deltas."""
        if not rules:
            return
        rows = [market_rule_insert_row(rule_set_id, row) for row in rules]
        job = self.client.load_table_from_json(rows, MARKET_RULES_TABLE)
        job.result()
        if job.errors:
            raise RuntimeError(f"candidate market_rules load failed: {job.errors}")

    def _insert_receipt(
        self,
        receipt: RuleSetReceipt,
        *,
        entity_count: int,
        league_count: int,
        rule_count: int,
    ) -> None:
        """Clone parent metadata into one candidate mapping_rule_sets row."""
        sql = f"""
        insert into `{RULE_SETS_TABLE}`
        select @candidate_id, rule_set_id, @sha, source_revision, 'ui',
               [@proposal_id], engine_contract_version,
               @league_count, @rule_count,
               @entity_count, canonical_markets, current_timestamp(),
               'control-plane-service', 'M3a entity_alias proposal', @environment
        from `{RULE_SETS_TABLE}` where rule_set_id = @parent_id
        order by created_at desc limit 1
        """  # nosec B608
        params = [
            bigquery.ScalarQueryParameter("candidate_id", "STRING", receipt.rule_set_id),
            bigquery.ScalarQueryParameter("parent_id", "STRING", receipt.parent_rule_set_id),
            bigquery.ScalarQueryParameter("sha", "STRING", receipt.snapshot_sha256),
            bigquery.ScalarQueryParameter("proposal_id", "STRING", receipt.proposal_ids[0]),
            bigquery.ScalarQueryParameter("entity_count", "INT64", entity_count),
            bigquery.ScalarQueryParameter("league_count", "INT64", league_count),
            bigquery.ScalarQueryParameter("rule_count", "INT64", rule_count),
            bigquery.ScalarQueryParameter("environment", "STRING", self.environment),
        ]
        self._query(sql, params)

    def activate(self, rule_set_id: str) -> None:
        """Materialize current + validity opens when allow_activate is set."""
        if not self.allow_activate:
            raise RuntimeError("activation disabled")
        if self.get_receipt(rule_set_id) is None:
            raise KeyError(rule_set_id)
        from mappers.control_plane.bq_tip import apply_tip_change

        apply_tip_change(self, rule_set_id)
        # Set rather than invalidate: the rule_set_activated row is still in the
        # streaming buffer, so re-querying could return the previous tip.
        self._layer_cache.set_tip(rule_set_id)

    def rule_set_as_of(self, ts: str) -> str | None:
        """Latest activated tip with occurred_at <= ts."""
        sql = f"""
        select rule_set_id from `{AUDIT_EVENTS_TABLE}`
        where environment = @environment
          and event_type in ('rule_set_activated', 'rule_set_rolled_back')
          and occurred_at <= @ts
        order by occurred_at desc, event_id desc limit 1
        """  # nosec B608
        params = [
            bigquery.ScalarQueryParameter("environment", "STRING", self.environment),
            bigquery.ScalarQueryParameter("ts", "TIMESTAMP", ts),
        ]
        rows = self._query(sql, params)
        return str(rows[0].rule_set_id) if rows else None

    def rule_history(self, *, table_kind: str, natural_key: str) -> list[Any]:
        """On/off windows for one natural key."""
        sql = f"""
        select validity_id, table_kind, natural_key, introduced_in_rule_set_id,
               cast(effective_from as string) as effective_from, enabled,
               environment, league
        from `{VALIDITY_TABLE}`
        where environment = @environment
          and table_kind = @table_kind
          and natural_key = @natural_key
        order by effective_from asc, validity_id asc
        """  # nosec B608
        params = [
            bigquery.ScalarQueryParameter("environment", "STRING", self.environment),
            bigquery.ScalarQueryParameter("table_kind", "STRING", table_kind),
            bigquery.ScalarQueryParameter("natural_key", "STRING", natural_key),
        ]
        return windows_from_bq_rows(self._query(sql, params))

    def get_receipt(self, rule_set_id: str) -> RuleSetReceipt | None:
        """Load one immutable rule-set receipt."""
        sql = f"""
        select rule_set_id, parent_rule_set_id, snapshot_sha256,
               proposal_ids, created_via, environment
        from `{RULE_SETS_TABLE}` where rule_set_id = @rule_set_id
        order by created_at desc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("rule_set_id", "STRING", rule_set_id)]
        rows = self._query(sql, params)
        if not rows:
            return None
        row = rows[0]
        return RuleSetReceipt(
            rule_set_id=str(row.rule_set_id),
            parent_rule_set_id=row.parent_rule_set_id,
            snapshot_sha256=str(row.snapshot_sha256),
            proposal_ids=list(row.proposal_ids or []),
            created_via=str(row.created_via),
            environment=str(row.environment),
        )
