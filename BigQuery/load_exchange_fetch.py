"""Append fetch JSONL snapshots to raw_ingestion_us.*_fetch_raw tables."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery.exchange_fetch_extract import (
    crypto_keys,
    kalshi_keys,
    novig_keys,
    optic_keys,
    polymarket_keys,
    polymarket_usa_keys,
    polymarket_usa_side_ids,
    px_event_keys,
    px_market_keys,
    stx_keys,
    sxbet_keys,
    underdog_keys,
)
from BigQuery.exchange_fetch_snapshot import fetch_time_iso, snapshot_id_from_dir
from BigQuery.exchange_fetch_tables import LOAD_SCHEMAS, TABLES


def _append_row(buf: io.BytesIO, row: dict) -> None:
    buf.write(json.dumps(row, default=str).encode("utf-8"))
    buf.write(b"\n")


def _wrap_optic(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    league_id, game_id = optic_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "league_id": league_id,
        "game_id": game_id,
        "data": line,
    })


def _wrap_kalshi(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    _sport, event_ticker = kalshi_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        # Kept for the table schema; Kalshi rows are no longer keyed by
        # series ticker (the snapshot index reads each line's sport).
        "series_prefix": None,
        "event_ticker": event_ticker,
        "data": line,
    })


def _wrap_poly(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    slug_prefix, condition_id = polymarket_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "slug_prefix": slug_prefix,
        "condition_id": condition_id,
        "data": line,
    })


def _wrap_poly_usa(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    """One row per market side — ``market_side_id`` is the table's unique key."""
    league, event, symbol = polymarket_usa_keys(line)
    for side_id in polymarket_usa_side_ids(line) or [None]:
        _append_row(buf, {
            "snapshot_id": snap,
            "fetch_time": fts,
            "inner_league": league,
            "event_ticker": event,
            "market_id": symbol,
            "market_side_id": side_id,
            "data": line,
        })


def _wrap_crypto(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    league = crypto_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "league": league,
        "data": line,
    })


def _wrap_novig(
    buf: io.BytesIO, line: str, snap: str, fts: str, *, kind: str,
) -> None:
    league = novig_keys(line, kind)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "kind": kind,
        "league": league,
        "data": line,
    })


def _wrap_px_event(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    tournament_id, event_id = px_event_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "tournament_id": tournament_id,
        "event_id": event_id,
        "data": line,
    })


def _wrap_px_market(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    tournament_id, market_id = px_market_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "tournament_id": tournament_id,
        "market_id": market_id,
        "data": line,
    })


def _wrap_sxbet(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    league_id, event_id, market_hash = sxbet_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "league_id": league_id,
        "event_id": event_id,
        "market_hash": market_hash,
        "data": line,
    })


def _wrap_underdog(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    series, event, ticker = underdog_keys(line)
    _append_row(buf, {
        "snapshot_id": snap,
        "fetch_time": fts,
        "series_ticker": series,
        "event_ticker": event,
        "ticker": ticker,
        "data": line,
    })


def _wrap_stx(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    event, market = stx_keys(line)
    _append_row(buf, {"snapshot_id": snap, "fetch_time": fts, "event_id": event, "market_id": market, "data": line})


def _wrap_stx_players(buf: io.BytesIO, line: str, snap: str, fts: str) -> None:
    _append_row(buf, {"snapshot_id": snap, "fetch_time": fts, "event_id": stx_keys(line)[0], "data": line})


#: Tables this loader must never create: Terraform owns them, and an
#: auto-created copy is unpartitioned and unclustered (mm-infrastructure
#: exchange_fetch_snapshots.tf header: ~$276/day in 2026-08).  A missing one is
#: a skipped load.
_CREATE_NEVER = frozenset({"sxbet", "underdog", "stx", "stx_players"})
#: Tables whose absence is a skip, not a failure (not created everywhere yet).
_SKIP_IF_MISSING = frozenset({"polymarket_usa", "sxbet", "underdog", "stx", "stx_players"})


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line:
                out.append(line)
    return out


_FIXED_SPECS: list[tuple[str, str, object]] = [
    ("optic", "optic_fixtures_odds.jsonl", _wrap_optic),
    ("kalshi", "kalshi_markets.jsonl", _wrap_kalshi),
    ("polymarket", "polymarket_markets.jsonl", _wrap_poly),
    ("polymarket_usa", "polymarket_usa_markets.jsonl", _wrap_poly_usa),
    ("crypto", "crypto_com_markets.jsonl", _wrap_crypto),
    ("sxbet", "sxbet_markets.jsonl", _wrap_sxbet),
    ("underdog", "underdog_markets.jsonl", _wrap_underdog),
    ("stx", "stx_markets.jsonl", _wrap_stx),
    ("stx_players", "stx_event_players.jsonl", _wrap_stx_players),
]


def _build_buffers_fixed(
    data_dir: Path, snap: str, fts: str,
) -> dict[str, tuple[io.BytesIO, int]]:
    """Build per-table NDJSON buffers and row counts."""
    out: dict[str, tuple[io.BytesIO, int]] = {}
    for key, fname, wrap in _FIXED_SPECS:
        buf = io.BytesIO()
        count = 0
        for line in _read_lines(data_dir / fname):
            wrap(buf, line, snap, fts)  # type: ignore[operator]
            count += 1
        if count:
            out[key] = (buf, count)

    novig_buf = io.BytesIO()
    novig_n = 0
    for kind, fname in (("events", "novig_events.jsonl"), ("markets", "novig_markets.jsonl")):
        for line in _read_lines(data_dir / fname):
            _wrap_novig(novig_buf, line, snap, fts, kind=kind)
            novig_n += 1
    if novig_n:
        out["novig"] = (novig_buf, novig_n)

    px_e_buf = io.BytesIO()
    px_e_n = 0
    for line in _read_lines(data_dir / "prophetx_events.jsonl"):
        _wrap_px_event(px_e_buf, line, snap, fts)
        px_e_n += 1
    if px_e_n:
        out["px_events"] = (px_e_buf, px_e_n)

    px_m_buf = io.BytesIO()
    px_m_n = 0
    for line in _read_lines(data_dir / "prophetx_markets.jsonl"):
        _wrap_px_market(px_m_buf, line, snap, fts)
        px_m_n += 1
    if px_m_n:
        out["px_markets"] = (px_m_buf, px_m_n)

    return out


def _load_buffer(
    client: bigquery.Client, key: str, buf: io.BytesIO, count: int,
) -> None:
    table = TABLES[key]
    print(f"  {table}: {count} rows")
    buf.seek(0)
    job_config = bigquery.LoadJobConfig(
        schema=LOAD_SCHEMAS[key],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    if key in _CREATE_NEVER:
        job_config.create_disposition = bigquery.CreateDisposition.CREATE_NEVER
    try:
        job = client.load_table_from_file(buf, table, job_config=job_config)
        job.result()
    except NotFound:
        if key not in _SKIP_IF_MISSING:
            raise
        print(f"  {table}: skipped (table not created yet)", file=sys.stderr)
        return
    if job.errors:
        raise RuntimeError(f"{table} load errors: {job.errors}")


def _load_buffer_job(
    client: bigquery.Client, key: str, buf: io.BytesIO, count: int,
) -> tuple[str, Exception | None]:
    try:
        _load_buffer(client, key, buf, count)
        return key, None
    except Exception as exc:
        return key, exc


def load(data_dir: Path) -> None:
    snap = snapshot_id_from_dir(data_dir)
    fts = fetch_time_iso(data_dir)
    print(f"Loading exchange fetch snapshot {snap}...")
    buffers = _build_buffers_fixed(data_dir, snap, fts)
    if not buffers:
        print("  no fetch files to load")
        return
    client = bigquery.Client(project=os.environ["GCP_PROJECT"])
    workers = len(buffers)  # one load job each, all at once: the step sits on the tick's serial path
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(_load_buffer_job, client, key, buf, count)
            for key, (buf, count) in buffers.items()
        ]
        for fut in as_completed(futs):
            key, err = fut.result()
            if err is not None:
                print(
                    f"  WARN: {TABLES[key]} load failed (non-fatal): {err}",
                    file=sys.stderr,
                )
    print("  done")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load fetch JSONL into raw_ingestion_us exchange_fetch_raw tables",
    )
    parser.add_argument("data_dir", type=Path, help="data/YYYY-MM-DD/HH_MM")
    args = parser.parse_args()
    load(args.data_dir)


if __name__ == "__main__":
    main()
