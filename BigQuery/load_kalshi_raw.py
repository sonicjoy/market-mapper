"""Append raw Kalshi markets JSONL to raw_ingestion_us.kalshi_raw.

Each line of the input JSONL becomes one row in the target table,
with the whole JSON blob stored verbatim as a string in the `data`
column.  `insert_time` is populated by the column's
CURRENT_TIMESTAMP default.

The table accumulates snapshots (one append per fetch) and is
day-partitioned on insert_time.  Schema defined in
mm-infrastructure/modules/general_us/schemas/raw_ingestion/kalshi_raw.sql.

Usage:
    .venv/bin/python -m BigQuery.load_kalshi_raw PATH/TO/kalshi_markets.jsonl
"""

import argparse
import io
import json
import os
import sys

from google.cloud import bigquery

TABLE = "raw_ingestion_us.kalshi_raw"


def load(path: str) -> None:
    print(f"Reading {path}...")
    buf = io.BytesIO()
    line_count = 0
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            # Wrap each original JSON record as a single-column row
            # whose `data` field is the original JSON string verbatim.
            wrapped = json.dumps({"data": line}).encode("utf-8")
            buf.write(wrapped)
            buf.write(b"\n")
            line_count += 1

    if line_count == 0:
        sys.exit(f"No rows to load from {path}")

    buf.seek(0)
    print(f"  {line_count} rows, {buf.getbuffer().nbytes:,} bytes")

    print(f"Appending to {TABLE}...")
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])

    # Explicit schema with only `data`: omitting `insert_time` lets
    # BQ apply the column's CURRENT_TIMESTAMP default.
    job_config = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField("data", "STRING")],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_file(buf, TABLE, job_config=job_config)
    job.result()
    if job.errors:
        print("ERRORS:")
        for err in job.errors:
            print(f"  {err}")
        sys.exit(1)

    print(f"  Appended {job.output_rows} rows")


def main():
    parser = argparse.ArgumentParser(
        description="Append raw Kalshi markets JSONL to BigQuery.",
    )
    parser.add_argument("file", help="Path to kalshi_markets.jsonl")
    args = parser.parse_args()
    load(args.file)


if __name__ == "__main__":
    main()
