"""Append Runshop betbuilder price JSONL to raw_ingestion_us.runshop_prices.

Each line of the input JSONL becomes one row with typed columns matching
the betbuilder API response.  `insert_time` is stamped at load time (one
value per snapshot).  Rows whose (id, updateTimeStamp) pair already exist
in the table (within a 30-day partition window) are skipped.

The table is created on first run if missing, day-partitioned on
insert_time.

Usage:
    .venv/bin/python -m BigQuery.load_runshop_prices PATH/TO/runshop_prices.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

TABLE = "raw_ingestion_us.runshop_prices"
DEDUPE_LOOKBACK_DAYS = 30

SCHEMA = [
    bigquery.SchemaField("id", "INTEGER"),
    bigquery.SchemaField("txOddsFixtureID", "INTEGER"),
    bigquery.SchemaField("updateTimeStamp", "TIMESTAMP"),
    bigquery.SchemaField("marketIds", "INTEGER", mode="REPEATED"),
    bigquery.SchemaField("modelId", "INTEGER"),
    bigquery.SchemaField("price", "FLOAT"),
    bigquery.SchemaField("metadataId", "INTEGER"),
    bigquery.SchemaField("insert_time", "TIMESTAMP"),
]


def _parse_update_timestamp(value: str) -> datetime:
    """Parse betbuilder ISO timestamp to UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def update_timestamp_micros(value: str) -> int:
    """UNIX micros for updateTimeStamp — used for dedupe key comparison."""
    dt = _parse_update_timestamp(value)
    return int(dt.timestamp() * 1_000_000)


def dedupe_key(record: dict) -> tuple[int, int]:
    return (int(record["id"]), update_timestamp_micros(record["updateTimeStamp"]))


def read_jsonl(path: str) -> list[dict]:
    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _full_table_id(client: bigquery.Client, table_id: str) -> str:
    if table_id.count(".") == 2:
        return table_id
    return f"{client.project}.{table_id}"


def _ensure_table(client: bigquery.Client, table_id: str) -> bool:
    """Create the table if missing.  Returns True if the table was created."""
    full_id = _full_table_id(client, table_id)
    try:
        client.get_table(full_id)
        return False
    except NotFound:
        table = bigquery.Table(full_id, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="insert_time",
        )
        client.create_table(table)
        return True


def _fetch_existing_keys(client: bigquery.Client, table_id: str) -> set[tuple[int, int]]:
    full_id = _full_table_id(client, table_id)
    lookback_days = DEDUPE_LOOKBACK_DAYS
    sql = (
        "select id, unix_micros(updateTimeStamp) as update_micros\n"
        f"from `{full_id}`\n"  # nosec B608
        f"where insert_time >= timestamp_sub(current_timestamp(), interval {lookback_days} day)"  # nosec B608
    )
    rows = client.query(sql).result()
    return {(int(row.id), int(row.update_micros)) for row in rows}


def filter_new_records(
    records: list[dict],
    existing_keys: set[tuple[int, int]],
) -> list[dict]:
    return [rec for rec in records if dedupe_key(rec) not in existing_keys]


def stamp_insert_time(records: list[dict], insert_time: datetime) -> list[dict]:
    stamped = insert_time.astimezone(UTC).isoformat()
    out: list[dict] = []
    for rec in records:
        row = dict(rec)
        row["insert_time"] = stamped
        out.append(row)
    return out


def load(path: str) -> int:
    if not os.path.exists(path):
        print(f"No file at {path}, skipping")
        return 0

    print(f"Reading {path}...")
    records = read_jsonl(path)
    if not records:
        print(f"No rows to load from {path}")
        return 0

    print(f"  {len(records)} rows")
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])
    table_created = _ensure_table(client, TABLE)

    if table_created:
        existing_keys: set[tuple[int, int]] = set()
    else:
        existing_keys = _fetch_existing_keys(client, TABLE)

    new_records = filter_new_records(records, existing_keys)
    if not new_records:
        print("  0 new rows (all already in table)")
        return 0

    insert_time = datetime.now(UTC)
    rows = stamp_insert_time(new_records, insert_time)
    print(f"  {len(rows)} new rows to append")

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(rows, TABLE, job_config=job_config)
    job.result()
    if job.errors:
        print("ERRORS:")
        for err in job.errors:
            print(f"  {err}")
        sys.exit(1)

    print(f"  Appended {job.output_rows} rows")
    return int(job.output_rows or 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append Runshop betbuilder prices JSONL to BigQuery.",
    )
    parser.add_argument("file", help="Path to runshop_prices.jsonl")
    args = parser.parse_args()
    load(args.file)


if __name__ == "__main__":
    main()
