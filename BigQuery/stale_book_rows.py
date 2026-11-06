"""Reap Kalshi and Polymarket rows a re-map moved or stopped emitting.

MERGE is a pure upsert keyed on the canonical bet, so a row the mapper no
longer produces under the same key stays forever (until the 24h
started-fixture reap):

* Kalshi: ``line`` is a MERGE key.  When the half-point convention was fixed
  (NHL 2026-27: CAR2 is "wins by over 1.5", not 2.5) the corrected row
  inserts next to the wrong one and the same ticker|side resolves to two
  lines.  Positive evidence — the ticker|side is staged under another key —
  so this runs for Optic-live fixtures too, like the US ticker-move reap.
* Polymarket: the passthrough identity check can strip Optic's token from a
  row entirely.  Mirrors the crypto stale-symbol reap: only fixtures that
  staged at least one Polymarket row, never Optic-live, never inside the
  in-play hold, so a thinner in-play or partial fetch cannot wipe a board.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from BigQuery.client import sandbox_query

_TICKER_SIDE = (
    "CONCAT(JSON_VALUE({a}.source_ids, '$.market_id'), '|', "
    "JSON_VALUE({a}.source_ids, '$.selection_id'))"
)


def same_key_sql(key_columns: Sequence[str], nullable: frozenset[str] | set[str]) -> str:
    """SQL: stage row ``s`` has the same MERGE key as target row ``t``."""
    parts = [
        f"s.{c} IS NOT DISTINCT FROM t.{c}" if c in nullable else f"s.{c} = t.{c}"
        for c in key_columns
    ]
    return " AND ".join(parts)


def relabeled_ticker_where(stage: str, date_in: str, same_key: str, book: str) -> str:
    """``book`` rows whose market_id|selection_id this stage carries only under another key."""
    t_id, s_id = _TICKER_SIDE.format(a="t"), _TICKER_SIDE.format(a="s")
    return f"""
            DATE(t.start_date) IN ({date_in})
            AND t.sportsbook = '{book}'
            AND EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = '{book}' AND {s_id} = {t_id}
            )
            AND NOT EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = '{book}' AND {s_id} = {t_id} AND {same_key}
            )"""  # nosec B608 — stage is a module constant, book is a literal, date_in is pipeline-built ISO dates


def relabeled_kalshi_where(stage: str, date_in: str, same_key: str) -> str:
    """Kalshi rows whose ticker|side this stage carries only under another key."""
    return relabeled_ticker_where(stage, date_in, same_key, "Kalshi")


def dropped_polymarket_where(
    stage: str, date_in: str, same_key: str, guard: str,
) -> str:
    """Polymarket rows on a staged fixture whose key this stage no longer emits."""
    return f"""
            DATE(t.start_date) IN ({date_in})
            AND {guard}
            AND t.sportsbook = 'Polymarket'
            AND EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = 'Polymarket'
                    AND s.game_id = t.game_id AND s.start_date = t.start_date
            )
            AND NOT EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = 'Polymarket' AND {same_key}
            )"""  # nosec B608 — stage is a module constant, guard/date_in are pipeline-built SQL


def _detect_sql(table: str, where: str) -> str:
    return f"""
        SELECT t.league, t.game_id, t.market_type, COUNT(*) AS n
        FROM {table} t
        WHERE {where}
        GROUP BY t.league, t.game_id, t.market_type
        ORDER BY n DESC
    """  # nosec B608 — table is a module constant, where is built above


def _reap(client: Any, table: str, where: str, label: str) -> int:
    rows = list(client.query(_detect_sql(table, where)).result())
    if not rows:
        print(f"  No stale {label} rows.")
        return 0
    total = sum(int(r.n) for r in rows)
    for r in rows[:20]:
        print(f"  Stale {label}: {r.league} {r.game_id} {r.market_type} ({r.n} rows)")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
    sandbox_query(client, f"DELETE FROM {table} t WHERE {where}")  # nosec B608 — see _detect_sql
    print(f"  Deleted {total} stale {label} rows.")
    return total


def clean_stale_book_rows(
    client: Any,
    table: str,
    stage: str,
    date_in: str,
    *,
    same_key: str,
    polymarket_guard: str,
) -> int:
    """Delete relabeled Kalshi / STX and dropped Polymarket rows; return the count.

    STX: a market whose specifier or fixture changed re-keys (line / team are MERGE keys), and the same
    market_id|selection_id must never resolve to two rows for the maker's lookup.
    """
    kalshi = _reap(
        client, table, relabeled_kalshi_where(stage, date_in, same_key),
        "relabeled Kalshi",
    )
    poly = _reap(
        client, table,
        dropped_polymarket_where(stage, date_in, same_key, polymarket_guard),
        "Polymarket",
    )
    stx = _reap(
        client, table, relabeled_ticker_where(stage, date_in, same_key, "STX"),
        "relabeled STX",
    )
    return kalshi + poly + stx
