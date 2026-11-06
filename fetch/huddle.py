"""Fetch the Huddle NFL market set from huddle_dedup_state.

Huddle is a pricing supplier. Latest-per-selection lives in
``huddle_us.huddle_dedup_state`` (pre-match and in-play selectionIds).
Join ``event_mapping`` for the Sportradar integer (betradar.event.extId).

Do not read huddle_canonical_mapping — that AI table is not this matcher.

Usage:
    python -m fetch.huddle --out-dir data/2026-09-21/12_00
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any

from BigQuery.client import ro_client, ro_query
from mappers.vocab.football_huddle import NFL_COMPETITION_ID

# Look-back covers in-play kickoffs; look-ahead matches Optic's 7d horizon.
LOOKBACK_HOURS = 18
HORIZON_HOURS = 168

QUERY = """
SELECT
  d.eventId AS event_id,
  d.marketId AS market_id,
  d.selectionId AS selection_id,
  d.marketCode AS market_code,
  d.selectionCode AS selection_code,
  d.competitionName AS competition_name,
  e.competitionId AS competition_id,
  d.line,
  d.team,
  d.milestone,
  d.playerName AS player_name,
  d.period,
  d.half,
  JSON_EXTRACT_SCALAR(PARSE_JSON(JSON_VALUE(e.mappingsPerFeed)),
                      "$.betradar.event.extId") AS betradar_extid,
  FORMAT_TIMESTAMP("%Y-%m-%dT%H:%M:%SZ", e.startDateTime) AS start_date
FROM `huddle_us.huddle_dedup_state` d
JOIN `huddle_us.event_mapping` e USING (eventId)
WHERE e.competitionId = '{competition}'
  AND d.startDateTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} HOUR)
  AND d.startDateTime < TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {horizon} HOUR)
"""


def fetch_selections(
    *,
    lookback_hours: int,
    horizon_hours: int,
) -> tuple[list[dict], int]:
    """Latest NFL selections in the kickoff window."""
    client = ro_client()
    sql = QUERY.format(
        competition=NFL_COMPETITION_ID,
        lookback=lookback_hours,
        horizon=horizon_hours,
    )
    records: list[dict] = []
    events: set[str] = set()
    for row in ro_query(client, sql):
        events.add(row.event_id)
        records.append(_record(row))
    return records, len(events)


def _record(row: Any) -> dict:
    """Flatten one BQ row into mapper JSONL."""
    return {
        "event_id": row.event_id,
        "event_name": getattr(row, "event_name", None),
        "competition_id": row.competition_id,
        "betradar_extid": row.betradar_extid,
        "start_date": row.start_date,
        "market_id": row.market_id,
        "market_code": row.market_code,
        "selection_id": row.selection_id,
        "selection_code": row.selection_code,
        "line": row.line,
        "team": row.team,
        "milestone": row.milestone,
        "player_name": row.player_name,
        "period": row.period,
        "half": row.half,
    }


def print_breakdown(records: list[dict]) -> None:
    """Show top marketCodes on stderr."""
    by_code = Counter(r["market_code"] for r in records)
    print(f"\n  {len(by_code)} distinct marketCodes:", file=sys.stderr)
    for code, n in by_code.most_common(15):
        print(f"    {code:32} {n:6}", file=sys.stderr)


def _write(path: str, records: list[dict]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for rec in records:
            print(json.dumps(rec), file=handle)
    print(f"Wrote {path} ({len(records)} selections)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Huddle NFL selections from huddle_dedup_state.",
    )
    parser.add_argument("--league", nargs="+", help="(accepted, not used)")
    parser.add_argument("--minutes", type=int, default=None)
    parser.add_argument("--hours", type=int, default=None)
    parser.add_argument("--max-items", type=int)
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--out-dir")
    out.add_argument("--out")
    args = parser.parse_args()
    lookback = LOOKBACK_HOURS
    horizon = HORIZON_HOURS
    if args.hours is not None:
        lookback = args.hours
    elif args.minutes is not None:
        lookback = max(1, args.minutes // 60)
    print(
        f"Querying Huddle NFL dedup_state lookback={lookback}h "
        f"horizon={horizon}h...",
        file=sys.stderr,
    )
    records, n_events = fetch_selections(
        lookback_hours=lookback, horizon_hours=horizon,
    )
    _report_or_empty(records, n_events, args)
    if args.max_items:
        records = records[: args.max_items]
    _emit(records, args)


def _report_or_empty(records: list[dict], n_events: int, args: object) -> None:
    if records:
        print(
            f"  {len(records)} selections across {n_events} events",
            file=sys.stderr,
        )
        print_breakdown(records)
        return
    if getattr(args, "out", None):
        print("  WARNING: empty window — nothing written.", file=sys.stderr)
        return
    print("  WARNING: empty window — writing empty file.", file=sys.stderr)


def _emit(records: list[dict], args: object) -> None:
    out_dir = getattr(args, "out_dir", None)
    out_path = getattr(args, "out", None)
    if out_dir:
        _write(os.path.join(out_dir, "huddle_markets.jsonl"), records)
        return
    if out_path:
        if not records and getattr(args, "out", None):
            return
        _write(out_path, records)
        return
    for rec in records:
        print(json.dumps(rec))


if __name__ == "__main__":
    main()
