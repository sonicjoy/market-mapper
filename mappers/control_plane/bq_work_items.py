"""BigQuery work-item (inbox) persistence helpers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from google.cloud import bigquery

from BigQuery.mapping_rule_rows import AUDIT_EVENTS_TABLE, WORK_ITEMS_TABLE
from mappers.control_plane.store import PARITY_EVENT_TYPES, WorkItemRow

QueryParameter = bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter


def work_item_from_row(row: Any) -> WorkItemRow:
    """Map a BigQuery work-item row to WorkItemRow."""
    extraction = row.request_extraction
    if isinstance(extraction, str):
        extraction = json.loads(extraction)
    summary = None
    if isinstance(extraction, dict):
        summary = extraction.get("summary")
    return WorkItemRow(
        work_item_id=str(row.work_item_id),
        fingerprint=str(row.fingerprint),
        source=str(row.source),
        status=str(row.status),
        league=row.league,
        sportsbook=row.sportsbook,
        severity=row.severity,
        request_extraction=dict(extraction) if extraction else None,
        proposal_id=row.proposal_id,
        gap_event_id=row.gap_event_id,
        occurrence_count=int(row.occurrence_count or 1),
        summary=summary,
        created_at=str(row.created_at),
        updated_at=str(row.updated_at),
        last_seen_at=str(row.last_seen_at) if row.last_seen_at else None,
    )


class BqWorkItemsMixin:
    """Work-item CRUD mixed into BigQueryStore."""

    client: bigquery.Client
    environment: str

    def _query(
        self,
        sql: str,
        params: Sequence[QueryParameter] | None = None,
    ) -> list[Any]: ...

    def list_work_items(self, *, status: str | None = None) -> list[WorkItemRow]:
        """List inbox work items (latest row per work_item_id)."""
        sql = f"""
        select * from `{WORK_ITEMS_TABLE}`
        qualify row_number() over (
          partition by work_item_id order by updated_at desc
        ) = 1
        """  # nosec B608
        items = [work_item_from_row(row) for row in self._query(sql)]
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get_work_item(self, work_item_id: str) -> WorkItemRow | None:
        """Fetch one work item by id."""
        sql = f"""
        select * from `{WORK_ITEMS_TABLE}`
        where work_item_id = @wid
        order by updated_at desc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("wid", "STRING", work_item_id)]
        rows = self._query(sql, params)
        return work_item_from_row(rows[0]) if rows else None

    def work_item_by_fingerprint(self, fingerprint: str) -> WorkItemRow | None:
        """Lookup latest work item by fingerprint."""
        sql = f"""
        select * from `{WORK_ITEMS_TABLE}`
        where fingerprint = @fp
        order by updated_at desc limit 1
        """  # nosec B608
        params = [bigquery.ScalarQueryParameter("fp", "STRING", fingerprint)]
        rows = self._query(sql, params)
        return work_item_from_row(rows[0]) if rows else None

    def put_work_item(self, item: WorkItemRow) -> None:
        """Append one work-item version (append-only upsert)."""
        row = {
            "work_item_id": item.work_item_id,
            "fingerprint": item.fingerprint,
            "source": item.source,
            "status": item.status,
            "league": item.league,
            "sportsbook": item.sportsbook,
            "severity": item.severity,
            "request_extraction": json.dumps(item.request_extraction) if item.request_extraction else None,
            "suggestion_trace": None,
            "proposal_id": item.proposal_id,
            "gap_event_id": item.gap_event_id,
            "occurrence_count": item.occurrence_count,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "last_seen_at": item.last_seen_at,
            "environment": self.environment,
        }
        errors = self.client.insert_rows_json(WORK_ITEMS_TABLE, [row])
        if errors:
            raise RuntimeError(f"work item insert failed: {errors}")

    def list_parity_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Recent parity/tip-alignment audits (OK and mismatch), newest first."""
        sql = f"""
        select event_id, event_type, occurred_at, rule_set_id,
               league, sportsbook, reason_code, payload
        from `{AUDIT_EVENTS_TABLE}`
        where event_type in unnest(@event_types)
          and environment = @environment
        order by occurred_at desc limit @lim
        """  # nosec B608
        params: list[QueryParameter] = [
            bigquery.ArrayQueryParameter(
                "event_types", "STRING", sorted(PARITY_EVENT_TYPES)
            ),
            bigquery.ScalarQueryParameter("environment", "STRING", self.environment),
            bigquery.ScalarQueryParameter("lim", "INT64", limit),
        ]
        out: list[dict[str, Any]] = []
        for row in self._query(sql, params):
            payload = row.payload
            if isinstance(payload, str):
                payload = json.loads(payload)
            payload_dict = dict(payload or {})
            raw_count = payload_dict.get("mismatch_count")
            mismatch_count = int(raw_count) if raw_count is not None else 0
            out.append(
                {
                    "event_id": str(row.event_id),
                    "event_type": str(row.event_type),
                    "occurred_at": str(row.occurred_at),
                    "rule_set_id": row.rule_set_id,
                    "league": row.league,
                    "sportsbook": row.sportsbook,
                    "reason_code": row.reason_code,
                    "mismatch_count": mismatch_count,
                    "payload": payload_dict,
                }
            )
        return out
