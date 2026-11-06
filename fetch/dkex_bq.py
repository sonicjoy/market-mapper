"""Write the latest DKEX catalogue snapshot from BigQuery to the run dir.

    python -m fetch.dkex_bq --league nfl --out-dir data/2026-10-03/10_15

The mapping VM never calls DKEX.  The ``dkex-catalogue`` CronJob on the
GKE dkex-pool fetches the live REST catalogue (``fetch.dkex``) and appends
it to ``raw_ingestion_us.dkex_raw`` (``BigQuery.load_dkex_raw``), one load
job per fetch.  This reads the newest ``api`` snapshot -- the rows that
share the latest ``insert_time``, as for ``novig_raw`` -- and writes their
``data`` blobs verbatim to ``dkex_markets.jsonl``, the file the DKEX pass
reads.

The catalogue is the whole venue book, so ``--league`` is accepted for
the orchestrator's contract and ignored.  A snapshot older than
``MAX_AGE`` writes nothing and exits 1: a missing file makes the DKEX
pass skip, which is better than stamping a stale book.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

from google.cloud import bigquery

TABLE = "raw_ingestion_us.dkex_raw"
#: The CronJob runs every 15 minutes; two missed ticks is a dead feed.
MAX_AGE = timedelta(minutes=45)

# The outer read repeats the freshness bound.  ``r.insert_time = snap.s`` is
# only known at run time, so on its own it prunes nothing and every run
# scanned the whole table (~160 GB on 2026-10-28; 0.6 GB with the bound).
# The bound cannot drop a row: ``snap.s`` already satisfies it.
_SQL = f"""
with snap as (
  select max(insert_time) as s
  from `{{project}}.{TABLE}`
  where kind = 'api'
    and insert_time > timestamp_sub(current_timestamp(), interval @max_age_s second)
)
select r.data
from `{{project}}.{TABLE}` r, snap
where r.kind = 'api' and r.insert_time = snap.s
  and r.insert_time > timestamp_sub(current_timestamp(), interval @max_age_s second)
"""  # nosec B608 — table name is a module constant


def read_snapshot(client: bigquery.Client, project: str, limit: int | None) -> list[str]:
    """``data`` lines of the newest fresh ``api`` snapshot; [] when none."""
    sql = _SQL.format(project=project)
    if limit is not None:
        sql += f"\nlimit {int(limit)}"
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "max_age_s", "INT64", int(MAX_AGE.total_seconds()),
            ),
        ],
    )
    return [row.data for row in client.query(sql, job_config=config).result() if row.data]


def write(out_dir: str, lines: list[str]) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dkex_markets.jsonl")
    with open(path, "w") as handle:
        for line in lines:
            handle.write(line.rstrip("\n") + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", nargs="*", help="ignored: the catalogue is the whole book")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-items", type=int, help="smoke test: cap the rows read")
    args = parser.parse_args(argv)

    project = os.environ["GCP_PROJECT"]
    lines = read_snapshot(bigquery.Client(project=project), project, args.max_items)
    if not lines:
        print(
            f"FATAL: no {TABLE} api snapshot newer than {MAX_AGE} in {project} "
            "-- is the dkex-catalogue CronJob running?",
            file=sys.stderr,
        )
        return 1
    path = write(args.out_dir, lines)
    print(f"wrote {len(lines)} rows -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
