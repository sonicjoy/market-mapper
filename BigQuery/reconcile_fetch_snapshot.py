"""Compare local fetch JSONL to raw_ingestion_us exchange_fetch_raw rows."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery.exchange_fetch_snapshot import (
    fetch_time_from_dir,
    fetch_time_window,
    snapshot_id_from_dir,
)
from BigQuery.exchange_fetch_tables import TABLES

_SOURCES = (
    ("optic", "optic_fixtures_odds.jsonl", "data"),
    ("kalshi", "kalshi_markets.jsonl", "data"),
    ("polymarket", "polymarket_markets.jsonl", "data"),
    ("polymarket_usa", "polymarket_usa_markets.jsonl", "data"),
    ("crypto", "crypto_com_markets.jsonl", "data"),
)


def _file_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line:
                out.append(line)
    return out


def _digest(lines: list[str]) -> str:
    payload = "\n".join(sorted(lines)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bq_lines(
    client: bigquery.Client,
    table_key: str,
    snapshot_id: str,
    window: tuple[datetime, datetime],
) -> list[str]:
    """Read one snapshot's rows back out of a *_fetch_raw table.

    snapshot_id alone prunes nothing — the *_fetch_raw tables are
    append-only, so a bare point-read scans every daily partition.  The
    fetch_time band (see fetch_time_window) pins DATE(fetch_time) to one
    partition, two if the tick sits on UTC midnight.
    """
    table = TABLES[table_key]
    # polymarket_usa lands one row per market side, each carrying the market line.
    select = "SELECT DISTINCT data" if table_key == "polymarket_usa" else "SELECT data"
    sql = (
        f"{select} FROM `{table}` "  # nosec B608 - table is a module constant
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    )
    lo, hi = window
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("snapshot_id", "STRING", snapshot_id),
            bigquery.ScalarQueryParameter("fetch_time_lo", "TIMESTAMP", lo),
            bigquery.ScalarQueryParameter("fetch_time_hi", "TIMESTAMP", hi),
        ],
    )
    return [row.data for row in client.query(sql, job_config=cfg).result()]


def _reconcile_novig(
    data_dir: Path,
    client: bigquery.Client,
    snap: str,
    window: tuple[datetime, datetime],
) -> list[str]:
    errors: list[str] = []
    local = _file_lines(data_dir / "novig_events.jsonl")
    local += _file_lines(data_dir / "novig_markets.jsonl")
    remote = _bq_lines(client, "novig", snap, window)
    if len(local) != len(remote):
        errors.append(f"novig count local={len(local)} bq={len(remote)}")
    elif local and _digest(local) != _digest(remote):
        errors.append("novig sha256 mismatch")
    return errors


def _reconcile_px(
    data_dir: Path,
    client: bigquery.Client,
    snap: str,
    window: tuple[datetime, datetime],
) -> list[str]:
    errors: list[str] = []
    for key, fname in (("px_events", "prophetx_events.jsonl"), ("px_markets", "prophetx_markets.jsonl")):
        local = _file_lines(data_dir / fname)
        remote = _bq_lines(client, key, snap, window)
        if len(local) != len(remote):
            errors.append(f"{key} count local={len(local)} bq={len(remote)}")
        elif local and _digest(local) != _digest(remote):
            errors.append(f"{key} sha256 mismatch")
    return errors


def reconcile(data_dir: Path) -> list[str]:
    snap = snapshot_id_from_dir(data_dir)
    window = fetch_time_window(fetch_time_from_dir(data_dir))
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])
    errors: list[str] = []
    for key, fname, _col in _SOURCES:
        local = _file_lines(data_dir / fname)
        if not local:
            continue
        try:
            remote = _bq_lines(client, key, snap, window)
        except NotFound:
            if key != "polymarket_usa":
                raise
            continue
        if len(local) != len(remote):
            if key == "polymarket_usa" and not remote:
                continue
            errors.append(f"{key} count local={len(local)} bq={len(remote)}")
        elif _digest(local) != _digest(remote):
            errors.append(f"{key} sha256 mismatch")
    errors.extend(_reconcile_novig(data_dir, client, snap, window))
    errors.extend(_reconcile_px(data_dir, client, snap, window))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile fetch JSONL vs BQ snapshot")
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    errs = reconcile(args.data_dir)
    if errs:
        for e in errs:
            print(f"ALERT: reconcile {e}", file=sys.stderr)
        sys.exit(1)
    print(f"reconcile ok: {snapshot_id_from_dir(args.data_dir)}")


if __name__ == "__main__":
    main()
