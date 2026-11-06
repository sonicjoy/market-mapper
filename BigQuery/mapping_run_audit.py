"""Append mapping run lifecycle rows to markets_us.mapping_audit_events."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from BigQuery.mapping_rule_rows import AUDIT_EVENTS_TABLE
from mappers.seed.audit import run_completed_event, run_started_event

_TEST_PROJECT = "marketmaking-test"


def _environment(project: str) -> str:
    return "test" if project == _TEST_PROJECT else "prod"


def _append_audit(client: bigquery.Client, row: dict[str, Any]) -> None:
    payload = row.get("payload")
    if payload is not None and not isinstance(payload, str):
        row = {**row, "payload": json.dumps(payload, sort_keys=True)}
    errors = client.insert_rows_json(
        AUDIT_EVENTS_TABLE, [row], row_ids=[row["event_id"]],
    )
    if errors:
        raise RuntimeError(f"audit insert failed: {errors}")


def append_run_lifecycle(
    mapping_run_id: str,
    *,
    phase: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit append; never raises to caller."""
    project = os.environ.get("GCP_PROJECT", "")
    if not project:
        return
    env = _environment(project)
    try:
        client = bigquery.Client(project=project)
        if phase == "started":
            row = run_started_event(
                mapping_run_id=mapping_run_id,
                environment=env,
                payload=payload,
            )
        else:
            row = run_completed_event(
                mapping_run_id=mapping_run_id,
                environment=env,
                payload=payload,
            )
        _append_audit(client, row)
    except Exception as exc:
        print(f"WARN: mapping run audit ({phase}) failed: {exc}", file=sys.stderr)


def read_mapping_run_meta(mappings_path: str) -> dict[str, Any]:
    run_path = Path(mappings_path).parent / "mapping_run.json"
    if not run_path.exists():
        return {}
    return json.loads(run_path.read_text(encoding="utf-8"))
