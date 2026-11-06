"""Scrape every Polymarket token's final resolution price and upsert to BigQuery.

This is the primary deliverable: for each CLOB ``clob_token_id`` whose market has
settled, record the actual ``resolved_price`` (0..1). It is INDEPENDENT of combos —
we scrape all markets, keyed by token. Combo-leg (position_id) resolution is then a
cheap VIEW joining the position<->token bridge onto this table (see
reporting_us.polymarket_position_resolutions in mm-infrastructure).

Resolutions are NOT binary: a normal settle is [1, 0], but a void / suspended /
cancelled market settles [0.5, 0.5]. We store the actual ``resolved_price`` as the
source of truth; ``resolution_type`` is WIN/LOSS/VOID_SPLIT by tolerance.

Source = the CLOB /markets endpoint (fetch/polymarket_clob.py): cursor-paginated
(no offset cap, unlike Gamma), token-native (each token carries a resolved price +
winner flag). We keep only ``closed`` markets whose ``end_date`` is within the window
(``--since``, default the last ``DEFAULT_WINDOW_DAYS``) and whose price vector is
decisively settled — a closed-but-ambiguous market is skipped and retried, never frozen
wrong.

The default window is rolling, not a fixed date: rows are held in memory until the one
MERGE, and a fixed 2026-06-01 start made the nightly run re-upsert every settled token
since June (5.9M rows, ~65k more a day). Its peak RSS grew from 5.5 GiB (09-25) to
7.4 GiB (10-13); on 2026-10-15 it and a mapper tick held most of the 16 GiB prod mapper VM
(93% used) when the box stalled and dropped off the network for ~3.5 h. Rows older
than the window stay in the table (MERGE upserts, never deletes); pass ``--since`` for a
deliberate backfill.

Schema is authoritative in Terraform (mm-infrastructure/modules/exchanges/
polymarket/); the inline schema here is kept in lockstep.

Usage:
    .venv/bin/python -m BigQuery.load_polymarket_token_resolutions
    .venv/bin/python -m BigQuery.load_polymarket_token_resolutions --since 2026-06-01T00:00:00Z  # backfill
    .venv/bin/python -m BigQuery.load_polymarket_token_resolutions --max-pages 5 --dry-run
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from google.cloud import bigquery

from BigQuery.polymarket_bq_util import bq_client, ensure_table, qualify, stage_and_merge
from fetch import polymarket_clob as clob

TABLE = "raw_ingestion_us.polymarket_token_resolutions"
STAGE = "raw_ingestion_us.polymarket_token_resolutions_stage"
KEY_COL = "clob_token_id"
PARTITION_FIELD = "resolved_at"
CLUSTERING = ["clob_token_id", "condition_id"]

# Nightly run re-sweeps settlements whose end_date falls in the last N days only.
DEFAULT_WINDOW_DAYS = 30


def default_since(now: datetime, days: int = DEFAULT_WINDOW_DAYS) -> str:
    """ISO start of the rolling window: ``now - days``, UTC, ``Z`` suffix."""
    return (now.astimezone(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# Settlement tolerances (see load_polymarket_leg_resolutions history): a win reads as
# ~0.9999989 not exactly 1.0, so WIN/LOSS use a loose band; a market counts as
# decisively settled only as a crisp binary (one ~1, rest ~0) or a clean void (all
# ~0.5) summing to ~1 — else it is closed-but-ambiguous and skipped.
WIN_TOL = 0.01
VOID_TOL = 0.02
SUM_TOL = 0.02

SCHEMA = [
    bigquery.SchemaField(
        "clob_token_id", "STRING", "REQUIRED", description="Standalone CLOB token id (decimal string); MERGE key"
    ),
    bigquery.SchemaField("condition_id", "STRING", "NULLABLE", description="Market condition_id (0x+64hex)"),
    bigquery.SchemaField("outcome_index", "INTEGER", "NULLABLE", description="Index of this outcome within the market"),
    bigquery.SchemaField("outcome_label", "STRING", "NULLABLE", description="Outcome label"),
    bigquery.SchemaField(
        "resolved_price",
        "FLOAT",
        "NULLABLE",
        description="SOURCE OF TRUTH: settled price of this token, 0..1 (0.5 = void/split)",
    ),
    bigquery.SchemaField(
        "resolution_type", "STRING", "NULLABLE", description="WIN (~1.0) | LOSS (~0.0) | VOID_SPLIT (in between)"
    ),
    bigquery.SchemaField(
        "won", "BOOLEAN", "NULLABLE", description="Convenience only: resolved_price ~= 1.0. Settle off resolved_price."
    ),
    bigquery.SchemaField(
        "winning_outcome_index",
        "INTEGER",
        "NULLABLE",
        description="Index of the ~1.0 outcome; NULL when split/void or ambiguous",
    ),
    bigquery.SchemaField(
        "all_outcome_prices", "STRING", "NULLABLE", description="Full settled price vector (JSON array) for audit"
    ),
    bigquery.SchemaField(
        "resolved_at", "TIMESTAMP", "NULLABLE", description="Market end / resolution time (partition key)"
    ),
    bigquery.SchemaField("resolution_source", "STRING", "NULLABLE", description="e.g. 'clob'"),
    bigquery.SchemaField("last_updated", "TIMESTAMP", "NULLABLE", description="When this loader last wrote the row"),
]


def _to_float(v) -> float | None:
    """Parse a price to float, or None if unparseable."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _classify(price: float) -> str:
    """WIN / LOSS / VOID_SPLIT for a single settled token price."""
    if price >= 1.0 - WIN_TOL:
        return "WIN"
    if price <= WIN_TOL:
        return "LOSS"
    return "VOID_SPLIT"


def is_decisively_settled(prices: list[float]) -> bool:
    """True only for a finished market: crisp binary (one ~1, rest ~0) or clean void."""
    if not prices or abs(sum(prices) - 1.0) > SUM_TOL:
        return False
    binary = (
        all(p >= 1.0 - WIN_TOL or p <= WIN_TOL for p in prices) and sum(1 for p in prices if p >= 1.0 - WIN_TOL) == 1
    )
    void = all(abs(p - 0.5) <= VOID_TOL for p in prices)
    return binary or void


def build_rows(markets, since_iso: str, now_iso: str) -> list[dict]:
    """One row per token of every decisively-settled market with end_date >= since.

    ``markets`` is an iterable of normalized CLOB markets. Skips open / out-of-window /
    ambiguous markets. Dedupes on clob_token_id (last write wins).
    """
    by_token: dict[str, dict] = {}
    seen_markets = 0
    settled = 0
    for m in markets:
        seen_markets += 1
        if not m["closed"]:
            continue
        # Skip markets we can't place in the window: a missing end_date can't be
        # confirmed in-range, and would also land in the NULL partition.
        end = m["end_date_iso"]
        if not end or end < since_iso:
            continue
        toks = m["tokens"]
        parsed = [_to_float(t["price"]) for t in toks]
        if not toks or any(p is None for p in parsed):
            continue
        prices: list[float] = [p for p in parsed if p is not None]
        if not is_decisively_settled(prices):
            continue
        settled += 1
        winners = [i for i, p in enumerate(prices) if p >= 1.0 - WIN_TOL]
        win_idx = winners[0] if len(winners) == 1 else None
        all_prices_json = json.dumps(prices)
        for i, t in enumerate(toks):
            price = prices[i]
            by_token[t["token_id"]] = {
                "clob_token_id": t["token_id"],
                "condition_id": m["condition_id"] or None,
                "outcome_index": i,
                "outcome_label": t["outcome"],
                "resolved_price": price,
                "resolution_type": _classify(price),
                "won": price >= 1.0 - WIN_TOL,
                "winning_outcome_index": win_idx,
                "all_outcome_prices": all_prices_json,
                "resolved_at": end,
                "resolution_source": "clob",
                "last_updated": now_iso,
            }
    print(f"  scanned {seen_markets} markets, {settled} decisively settled in window -> {len(by_token)} token rows")
    return list(by_token.values())


def load(since: str | None = None, max_pages: int | None = None, start_offset: int = 0, dry_run: bool = False) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    since = since or default_since(now)
    print(f"Scraping CLOB markets (settled since {since}, start_offset={start_offset})...", file=sys.stderr)
    markets = (
        clob.iter_markets(start_offset=start_offset, max_pages=max_pages)
        if max_pages
        else clob.iter_markets(start_offset=start_offset)
    )
    rows = build_rows(markets, since, now_iso)
    if not rows:
        print("No settled tokens in window.")
        return

    if dry_run:
        print("DRY RUN — sample rows:")
        for r in rows[:8]:
            print(f"  {r}")
        print(f"(total {len(rows)} rows; not written)")
        return

    client = bq_client()
    target = qualify(client, TABLE)
    stage = qualify(client, STAGE)
    ensure_table(client, target, SCHEMA, PARTITION_FIELD, CLUSTERING)
    print(f"Upserting {len(rows)} rows into {target} (via {stage})...")
    n = stage_and_merge(client, target, stage, SCHEMA, rows, KEY_COL)
    print(f"  staged {n} rows, MERGE complete.")


def main():
    p = argparse.ArgumentParser(description="Scrape Polymarket token final resolution prices into BigQuery.")
    p.add_argument(
        "--since",
        default=None,
        help=f"ISO timestamp: keep only markets whose end_date >= this (default: now - {DEFAULT_WINDOW_DAYS} days). "
        "Pass an old date only for a deliberate backfill - every row is held in memory.",
    )
    p.add_argument("--max-pages", type=int, default=None, help="Cap CLOB pages (smoke test).")
    p.add_argument(
        "--start-offset",
        type=int,
        default=0,
        help="Skip the first N markets (they are oldest-first). Steady-state runs seek near "
        "the tail so they don't re-page all ~1M+ markets each time.",
    )
    p.add_argument("--dry-run", action="store_true", help="Scrape + build rows, print a sample, write nothing.")
    args = p.parse_args()
    load(since=args.since, max_pages=args.max_pages, start_offset=args.start_offset, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
