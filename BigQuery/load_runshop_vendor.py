"""Stub loader for Runshop vendor market dictionary into BigQuery.

The full dictionary is ~14k TOML rows — too large for ``mapping_market_rules``.
Target table: ``raw_ingestion_us.runshop_vendor_markets`` with columns matching
``RunshopMarket`` (id, market, value, selection, sport_id) plus ``insert_time``.

A future fetch job should replace TOML conversion with a vendor CSV/API pull.
Until then, operators can load from TOML once:

    python -m BigQuery.load_runshop_vendor --from-toml config/world_cup/runshop_markets.toml

Mapper stamping continues to read TOML via ``runshop_vendor.load_vendor_markets``
until BQ read path is wired in ``stamp_runshop_rows``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from mappers.exchanges.runshop_crosswalk import load_runshop_markets
from mappers.exchanges.runshop_vendor import VENDOR_TABLE

SCHEMA = [
    bigquery.SchemaField("id", "INTEGER"),
    bigquery.SchemaField("market", "STRING"),
    bigquery.SchemaField("value", "FLOAT"),
    bigquery.SchemaField("selection", "STRING"),
    bigquery.SchemaField("sport_id", "INTEGER"),
    bigquery.SchemaField("insert_time", "TIMESTAMP"),
]


def _ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(VENDOR_TABLE)
    except NotFound:
        table = bigquery.Table(VENDOR_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="insert_time",
        )
        client.create_table(table)


def load_from_toml(client: bigquery.Client, path: Path) -> int:
    """One-shot import of archive TOML into the vendor table."""
    _ensure_table(client)
    insert_time = datetime.now(UTC)
    markets = load_runshop_markets(path)
    rows = [
        {
            "id": m.id,
            "market": m.market,
            "value": m.value,
            "selection": m.selection,
            "sport_id": m.sport_id,
            "insert_time": insert_time.isoformat(),
        }
        for m in markets
    ]
    errors = client.insert_rows_json(VENDOR_TABLE, rows)
    if errors:
        raise RuntimeError(f"insert_rows_json failed: {errors[:3]}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Runshop vendor dictionary")
    parser.add_argument(
        "--from-toml",
        type=Path,
        required=True,
        help="Path to runshop_markets.toml",
    )
    args = parser.parse_args(argv)
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])
    count = load_from_toml(client, args.from_toml)
    print(f"loaded {count} vendor rows into {VENDOR_TABLE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
