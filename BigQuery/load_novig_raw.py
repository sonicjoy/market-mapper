"""Append raw Novig events/markets JSONL to raw_ingestion_us.novig_raw.

Each line of the input JSONL becomes one row in the target table, with
the whole JSON blob stored verbatim as a string in the `data` column and
the feed it came from (`events` or `markets`) in `kind`.  `insert_time`
is populated by the column's CURRENT_TIMESTAMP default.

The table accumulates snapshots (one append per fetch) and is
day-partitioned on insert_time.  Schema defined in
mm-infrastructure/modules/general_us/schemas/raw_ingestion/novig_raw.sql.

Unlike kalshi_raw this carries a `kind` column: Novig's book only makes
sense as events + markets together (a market's eventId is the only route
to the Optic fixture id), so both feeds land in one table rather than two.

Usage:
    .venv/bin/python -m BigQuery.load_novig_raw \\
        --events PATH/novig_events.jsonl --markets PATH/novig_markets.jsonl
"""

import argparse
import io
import json
import os
import sys

from google.cloud import bigquery

TABLE = "raw_ingestion_us.novig_raw"


def _wrap(path: str, kind: str, buf: io.BytesIO) -> int:
    """Append every line of `path` to `buf` as a {kind, data} row."""
    if not path:
        return 0
    print(f"Reading {path}...")
    count = 0
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            # Wrap each original JSON record as a row whose `data` field is
            # the original JSON string verbatim.
            buf.write(json.dumps({"kind": kind, "data": line}).encode("utf-8"))
            buf.write(b"\n")
            count += 1
    print(f"  {count} {kind} rows")
    return count


def load(events_path: str | None, markets_path: str | None) -> None:
    buf = io.BytesIO()
    total = 0
    if events_path:
        total += _wrap(events_path, "events", buf)
    if markets_path:
        total += _wrap(markets_path, "markets", buf)

    if total == 0:
        sys.exit("No rows to load")

    buf.seek(0)
    print(f"  {total} rows, {buf.getbuffer().nbytes:,} bytes")

    print(f"Appending to {TABLE}...")
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])

    # Explicit schema without `insert_time` so BQ applies the column's
    # CURRENT_TIMESTAMP default.
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("kind", "STRING"),
            bigquery.SchemaField("data", "STRING"),
        ],
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
        description="Append raw Novig JSONL to BigQuery.",
    )
    parser.add_argument("--events", help="Path to novig_events.jsonl")
    parser.add_argument("--markets", help="Path to novig_markets.jsonl")
    args = parser.parse_args()
    if not args.events and not args.markets:
        parser.error("at least one of --events / --markets is required")
    load(args.events, args.markets)


if __name__ == "__main__":
    main()
