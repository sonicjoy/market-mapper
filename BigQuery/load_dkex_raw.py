"""Append a raw DKEX catalogue JSONL to raw_ingestion_us.dkex_raw.

Each line of ``dkex_markets.jsonl`` becomes one row whose ``data`` column
holds the record verbatim, with the source that produced it in ``kind``
(``api`` or ``reports``).  ``insert_time`` comes from the column default.
The table accumulates snapshots -- one append per fetch -- and is
day-partitioned on ``insert_time``.

``kind`` carries the SOURCE rather than the feed name (the Novig loader's
``events``/``markets`` split has no analogue here) because the two DKEX
sources differ in freshness, not in shape: ``reports`` rows are the
public T+1 CSV seed and ``api`` rows are the live venue catalogue.  A
query that cares whether it is looking at a live book -- and any query
about today's markets does -- must be able to tell them apart.

Usage:
    .venv/bin/python -m BigQuery.load_dkex_raw --markets PATH/dkex_markets.jsonl
"""

import argparse
import io
import json
import os
import sys

from google.cloud import bigquery

TABLE = "raw_ingestion_us.dkex_raw"


def _wrap(path: str, buf: io.BytesIO) -> int:
    """Append every line of `path` to `buf` as a {kind, data} row."""
    print(f"Reading {path}...")
    count = 0
    with open(path) as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            # The fetcher stamps each row with the source it came from;
            # promote it to a column so the T+1 seed is distinguishable
            # from the live catalogue without parsing the blob.
            try:
                kind = json.loads(line).get("source") or "unknown"
            except json.JSONDecodeError:
                kind = "unknown"
            buf.write(json.dumps({"kind": kind, "data": line}).encode("utf-8"))
            buf.write(b"\n")
            count += 1
    print(f"  {count} rows")
    return count


def load(markets_path: str) -> None:
    buf = io.BytesIO()
    total = _wrap(markets_path, buf)
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
        # The writer holds dataEditor on this table only. The default
        # CREATE_IF_NEEDED makes BQ check bigquery.tables.create on the
        # whole dataset, even though the table exists, and 403s.
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    job = client.load_table_from_file(buf, TABLE, job_config=job_config)
    job.result()
    if job.errors:
        print("ERRORS:")
        for err in job.errors:
            print(f"  {err}")
        sys.exit(1)
    print(f"  Appended {job.output_rows} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Append raw DKEX JSONL to BigQuery.")
    parser.add_argument("--markets", required=True, help="Path to dkex_markets.jsonl")
    args = parser.parse_args()
    load(args.markets)


if __name__ == "__main__":
    main()
