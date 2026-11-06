"""Rebuild a recent prod fetch tick from BigQuery as a replayable directory.

The checked-in corpus (``corpus.py``) is a frozen March-August 2026 set;
it cannot witness a venue, league or listing shape that appeared after
2026-08-13.  Every prod tick since 2026-08-19 is also appended, line for
line, to ``raw_ingestion_us.*_fetch_raw`` by ``BigQuery.load_exchange_fetch``
(``infra/run_pipeline.sh``, step ``load_fetch``).  This module reads one
``snapshot_id`` back and writes the same JSONL files the fetcher wrote on
the VM, so ``mappers.run <dir>`` replays it exactly as prod read it.

Why files and not ``MAP_SNAPSHOT_SOURCE=bq``: the engine's own BigQuery
hydrate keys crypto.com rows on the ``league`` column, which the loader
writes as null for every crypto row (``crypto_keys`` reads ``league``,
the catalogue carries ``eventMetaLEAGUE``) — 56,745 of 56,745 rows in
snapshot ``2026-09-30T15:00``.  A hydrate replay therefore maps zero
crypto.com games and a crypto regression can never show up.  The JSONL
reader falls back to ``eventMetaLEAGUE``, as prod does.

Coverage: optic, kalshi, polymarket, polymarket_usa, crypto.com, novig,
prophetx, SX Bet, Underdog, STX (markets and rosters).  Runshop, DKEX and Huddle inputs are not in
the fetch tables, so a materialized tick cannot witness those venues; the
tick's ``materialized.json`` records what it holds.

This module must not import from mappers/ or BigQuery/ (README design
rules): the table names and file names below are deliberate copies of
``BigQuery/exchange_fetch_tables.TABLES`` and
``mappers/snapshot_index.SnapshotIndex._ingest_jsonl``.

Usage:
    python -m regression.materialize 2026-09-30T15:00 --out /tmp/ticks
    python -m regression.materialize --latest --out /tmp/ticks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATASET = "raw_ingestion_us"

# (table, file the VM's fetcher writes); novig is one table, two files.
SOURCES = (
    ("optic_fetch_raw", "optic_fixtures_odds.jsonl"),
    ("kalshi_fetch_raw", "kalshi_markets.jsonl"),
    ("polymarket_fetch_raw", "polymarket_markets.jsonl"),
    ("polymarket_usa_fetch_raw", "polymarket_usa_markets.jsonl"),
    ("crypto_fetch_raw", "crypto_com_markets.jsonl"),
    ("px_events_fetch_raw", "prophetx_events.jsonl"),
    ("px_markets_fetch_raw", "prophetx_markets.jsonl"),
    ("sxbet_fetch_raw", "sxbet_markets.jsonl"),
    ("underdog_fetch_raw", "underdog_markets.jsonl"),
    ("stx_fetch_raw", "stx_markets.jsonl"),
    ("stx_players_fetch_raw", "stx_event_players.jsonl"),
)
NOT_IN_FETCH_TABLES = ("runshop", "dkex", "huddle")
# A table Terraform has not created yet reads as an empty file (the engine then skips the venue, as
# prod does without the file) and is named in the marker's ``not_covered``; any other table must exist.
OPTIONAL_TABLES = frozenset({"underdog_fetch_raw", "stx_fetch_raw", "stx_players_fetch_raw"})
NOVIG_FILES = {"events": "novig_events.jsonl", "markets": "novig_markets.jsonl"}

# One mapper tick either side of the snapshot instant: prunes the read to
# one daily partition (see BigQuery/exchange_fetch_snapshot.FETCH_TIME_SLACK).
SLACK = timedelta(minutes=15)

# A tick is complete only when every core source has rows.  A snapshot
# whose load_fetch step failed or is still running is refused rather than
# replayed half-empty, which would diff as mass removals.
REQUIRED = ("optic_fixtures_odds.jsonl", "kalshi_markets.jsonl", "crypto_com_markets.jsonl")

_ROWS_SQL = (
    "SELECT DISTINCT data FROM `{project}.{dataset}.{table}` "
    "WHERE fetch_time BETWEEN @lo AND @hi AND snapshot_id = @snap"
)
_NOVIG_SQL = (
    "SELECT kind, data FROM `{project}.{dataset}.novig_fetch_raw` "
    "WHERE fetch_time BETWEEN @lo AND @hi AND snapshot_id = @snap"
)
# Each query's result is read back as RANGES disjoint row ranges of its anonymous result table, in
# parallel: tabledata.list pages one stream at a time, so a single read was the gate's slowest step
# (300 s for two ticks, job 17282057672; 13.8 s for a whole tick ranged, 2026-10-19, byte-identical).
# It needs nothing beyond bigquery.jobUser — the Storage Read API would need
# bigquery.readsessions.create, which the gate identity does not hold. Always RANGES ranges, never
# sized by rows: optic's 292 MB is only 1,853 fixture rows (one range per 2,000 rows took 85 s).
RANGES = 16
_READERS = ThreadPoolExecutor(max_workers=32, thread_name_prefix="bq-range")

_LATEST_SQL = (
    "SELECT snapshot_id FROM `{project}.{dataset}.crypto_fetch_raw` "
    "WHERE fetch_time >= @since GROUP BY snapshot_id "
    "ORDER BY snapshot_id DESC"
)


def snapshot_instant(snapshot_id: str) -> datetime:
    """``2026-09-30T15:00`` -> the UTC instant it names."""
    return datetime.strptime(snapshot_id, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)


def tick_dir(root: Path, snapshot_id: str) -> Path:
    """``root/2026-09-30/15_00`` — the layout mappers.run and the corpus use."""
    date_part, time_part = snapshot_id.split("T", 1)
    return root / date_part / time_part.replace(":", "_")


def _client(project: str):
    from regression.credentials import bq_client  # lazy: tests stay offline

    return bq_client(project)


def _params(snapshot_id: str):
    from google.cloud import bigquery

    at = snapshot_instant(snapshot_id)
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("snap", "STRING", snapshot_id),
            bigquery.ScalarQueryParameter("lo", "TIMESTAMP", at - SLACK),
            bigquery.ScalarQueryParameter("hi", "TIMESTAMP", at + SLACK),
        ]
    )


def latest_snapshots(project: str, n: int = 1, client=None, every_hours: int = 0) -> list[str]:
    """The ``n`` newest snapshot ids with crypto rows in the last day.

    ``every_hours`` > 0 keeps only snapshots on that hour boundary (``HH:00``, HH a multiple of it),
    so repeated gate runs inside one window pick the same ticks and reuse their cached replays.
    """
    from google.cloud import bigquery

    client = client or _client(project)
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("since", "TIMESTAMP", datetime.now(UTC) - timedelta(days=1)),
        ]
    )
    sql = _LATEST_SQL.format(project=project, dataset=DATASET)
    snaps = [r.snapshot_id for r in client.query(sql, job_config=cfg).result()]
    if every_hours:
        snaps = [s for s in snaps if snapshot_instant(s).minute == 0 and snapshot_instant(s).hour % every_hours == 0]
    return snaps[:n]


def _ranges(total: int) -> list[tuple[int, int]]:
    """``min(RANGES, total)`` (start, count) row ranges covering ``total`` rows, sizes within one row."""
    n = max(1, min(RANGES, total))
    size, extra = divmod(total, n)
    starts = [i * size + min(i, extra) for i in range(n + 1)]
    return [(starts[i], starts[i + 1] - starts[i]) for i in range(n)]


def _fetch(client, sql: str, cfg) -> list:
    """All rows of one query, read back in parallel row ranges when the client can.

    A client without ``list_rows`` (the tests' fake) or a result without a destination table is
    read in one stream; both paths return the same rows (callers sort before writing).
    """
    job = client.query(sql, job_config=cfg)
    rows = job.result()
    dest = getattr(job, "destination", None)
    total = getattr(rows, "total_rows", None)
    if dest is None or not total or not hasattr(client, "list_rows"):
        return list(rows)
    schema = rows.schema

    def read(span: tuple[int, int]) -> list:
        start, count = span
        # page_size is load-bearing: google-cloud-bigquery < 3.46.2 re-sends startIndex with every page
        # token unless it is set, and each follow-on page then restarts at ``start`` — repeated rows, missing
        # rows, the count unchanged (CI's 3.46.1 dropped a UFC fight from the incident tick, pipeline
        # 2963925430).
        return list(
            client.list_rows(dest, selected_fields=schema, start_index=start, max_results=count, page_size=count)
        )

    parts = list(_READERS.map(read, _ranges(total)))
    out = [r for part in parts for r in part]
    if len(out) != total:
        raise RuntimeError(f"ranged read returned {len(out)} rows, the result table has {total}")
    return out


def _write(path: Path, lines: list[str]) -> int:
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w") as f:
        for line in sorted(lines):  # deterministic bytes for a given snapshot
            f.write(line.rstrip("\n") + "\n")
    tmp.rename(path)
    return len(lines)


def _fetch_table(client, sql: str, cfg, table: str) -> list | None:
    """``_fetch``, or None when an optional table does not exist yet."""
    from google.api_core.exceptions import NotFound

    try:
        return _fetch(client, sql, cfg)
    except NotFound:
        if table not in OPTIONAL_TABLES:
            raise
        return None


def _read_tick(client, cfg, project: str, out: Path) -> tuple[dict[str, int], list[str]]:
    """Query every fetch table for one snapshot at once and write its files.

    Returns lines per file and the optional tables that do not exist yet.
    """
    jobs = [(_ROWS_SQL.format(project=project, dataset=DATASET, table=table), table) for table, _ in SOURCES]
    jobs.append((_NOVIG_SQL.format(project=project, dataset=DATASET), "novig_fetch_raw"))
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:  # every table's query + read at once
        results = list(pool.map(lambda job: _fetch_table(client, job[0], cfg, job[1]), jobs))
    counts: dict[str, int] = {}
    missing = [table for (_sql, table), rows in zip(jobs, results, strict=True) if rows is None]
    for (_table, fname), rows in zip(SOURCES, results[:-1], strict=True):
        lines = [r.data for r in rows or []]
        if len(set(lines)) != len(lines):  # SELECT DISTINCT: a repeated line is a broken read, never data
            raise RuntimeError(f"{fname}: {len(lines) - len(set(lines))} repeated lines from a DISTINCT query")
        counts[fname] = _write(out / fname, lines)
    novig: dict[str, list[str]] = {k: [] for k in NOVIG_FILES}
    for r in results[-1] or []:
        if r.kind in novig:
            novig[r.kind].append(r.data)
    for kind, fname in NOVIG_FILES.items():
        counts[fname] = _write(out / fname, novig[kind])
    return counts, missing


def materialize(snapshot_id: str, root: Path, project: str, client=None, log=sys.stderr) -> Path:
    """Write one snapshot's fetch files under ``root``; return the tick dir.

    Idempotent: a tick dir that already carries ``materialized.json`` is
    reused.  Files are written to ``.part`` and renamed, and the marker is
    written last, so an interrupted run never leaves a dir that looks done.
    """
    out = tick_dir(root, snapshot_id)
    marker = out / "materialized.json"
    if marker.is_file():
        print(f"  {snapshot_id}: cached ({out})", file=log)
        return out
    out.mkdir(parents=True, exist_ok=True)
    counts, missing = _read_tick(client or _client(project), _params(snapshot_id), project, out)
    empty = [f for f in REQUIRED if not counts.get(f)]
    if empty:
        raise RuntimeError(
            f"snapshot {snapshot_id} is incomplete in {project} "
            f"({', '.join(empty)} empty) — load_fetch failed or is running"
        )
    marker.write_text(
        json.dumps(
            {
                "snapshot_id": snapshot_id,
                "project": project,
                "rows": counts,
                "not_covered": [*NOT_IN_FETCH_TABLES, *(t.removesuffix("_fetch_raw") for t in missing)],
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"  {snapshot_id}: materialized {sum(counts.values())} lines -> {out}", file=log)
    return out


def digest(tick: Path) -> str:
    """One line naming every file of a tick by line count and sha256 prefix (the run's input, in its log)."""
    import hashlib

    parts = []
    for f in sorted(tick.glob("*.jsonl")):
        data = f.read_bytes()
        parts.append(f"{f.stem}={data.count(b'\n')}:{hashlib.sha256(data).hexdigest()[:12]}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    """CLI: materialize named snapshots, or the newest N."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("snapshots", nargs="*", metavar="SNAPSHOT_ID")
    ap.add_argument(
        "--latest", type=int, nargs="?", const=1, default=0, metavar="N", help="the N newest snapshots (default 1)"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project", default=os.environ.get("MM_REPLAY_PROJECT", "rs-marketmaking"))
    args = ap.parse_args(argv)
    snaps = list(args.snapshots)
    if args.latest:
        snaps += latest_snapshots(args.project, args.latest)
    if not snaps:
        ap.error("give SNAPSHOT_IDs or --latest")
    for snap in dict.fromkeys(snaps):
        print(tick_dir(args.out, snap) if materialize(snap, args.out, args.project) else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
