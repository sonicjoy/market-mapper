"""MERGE mapper cross-check blocklist so fold cannot pick blocked RFQ keys."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery

from BigQuery.polymarket_bq_util import bq_client, ensure_table, qualify, stage_and_merge

logger = logging.getLogger(__name__)

TABLE = "markets_us.optic_passthrough_blocklist"
STAGE = "markets_us.optic_passthrough_blocklist_stage"
KEY_COL = "rfq_key"
PARTITION_FIELD = "blocked_at"
CLUSTERING = ["sportsbook"]

_SCHEMA = [
    bigquery.SchemaField("rfq_key", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("sportsbook", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("token", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("league", "STRING"),
    bigquery.SchemaField("reason", "STRING"),
    bigquery.SchemaField("blocked_at", "TIMESTAMP", mode="REQUIRED"),
]


def ensure_blocklist(client: bigquery.Client) -> None:
    """Create the blocklist table when this project does not have it yet."""
    target = qualify(client, TABLE)
    ensure_table(client, target, _SCHEMA, PARTITION_FIELD, CLUSTERING)


def load_blocks_file(path: Path) -> int:
    """Load ``optic_crosscheck_blocks.jsonl`` into the blocklist table."""
    if not path.is_file():
        return 0
    rows: list[dict] = []
    now = datetime.now(UTC).isoformat()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = rec.get("rfq_key")
        if not key:
            continue
        rows.append({
            "rfq_key": key,
            "sportsbook": rec.get("sportsbook", ""),
            "token": rec.get("token", ""),
            "league": rec.get("league"),
            "reason": "optic_passthrough_disagree",
            "blocked_at": now,
        })
    if not rows:
        return 0
    client = bq_client()
    ensure_blocklist(client)
    stage = qualify(client, STAGE)
    target = qualify(client, TABLE)
    stage_and_merge(client, target, stage, _SCHEMA, rows, KEY_COL)
    logger.info("optic crosscheck blocklist: merged %d row(s)", len(rows))
    return len(rows)
