"""Reap Polymarket (USA) rows left on a game their ticker moved off.

A US ticker is one venue instrument and settles on exactly one game, but
``game_id`` / ``start_date`` are MERGE keys: when a run binds the ticker
to a different Optic fixture, MERGE inserts the new row and the old one
stays.  None of the reschedule passes sees it — pass 3 joins on
``source_ids.selection_id`` and US rows carry only ``market_id``.

2026-09-25 prod: the venue moved BAL@NYY 09-26 into a 09-25 doubleheader.
The ``*-mlb-bal-nyy-2026-09-26-*`` tickers were first written onto game 2
(``2026092545C7270D``, 23:25Z) and later onto the venue's game
(``202609257ED540B0``, 20:05Z); 112 prop rows stayed on game 2 next to
the correct ones, and the maker priced 198 confirmed RFQs off game 2
between 03:25Z and 13:07Z.

Scoped to the ONE book and the ONE ticker: the old game is usually a
real, live game (here: game 2), so its other books' rows are untouched —
unlike the reschedule passes, which delete a whole stale game.  The
evidence is positive (the ticker was just staged on another game), so
live fixtures are not exempt.
"""

from __future__ import annotations

from typing import Any

from BigQuery.client import sandbox_query

_USA = "'Polymarket (USA)'"
_TICKER = "STRING({alias}.source_ids.market_id)"


def moved_usa_ticker_where(table: str, stage: str, cutoff: str) -> str:
    """WHERE body matching US rows whose ticker is staged on another game only."""
    t_id, s_id = _TICKER.format(alias="t"), _TICKER.format(alias="s")
    return f"""
            t.start_date >= TIMESTAMP('{cutoff}')
            AND t.sportsbook = {_USA}
            AND EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = {_USA}
                    AND {s_id} = {t_id}
                    AND s.game_id != t.game_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM {stage} s
                WHERE s.sportsbook = {_USA}
                    AND {s_id} = {t_id}
                    AND s.game_id = t.game_id
            )"""  # nosec B608 — table/stage are module constants, cutoff is a pipeline-computed ISO date


def moved_usa_ticker_detect_sql(table: str, stage: str, cutoff: str) -> str:
    """SELECT the rows the delete would remove, per (ticker, old game)."""
    return f"""
        SELECT {_TICKER.format(alias="t")} AS ticker, t.game_id,
            t.start_date, COUNT(*) AS n
        FROM {table} t
        WHERE {moved_usa_ticker_where(table, stage, cutoff)}
        GROUP BY ticker, t.game_id, t.start_date
        ORDER BY n DESC
    """  # nosec B608 — table/stage are module constants, cutoff is a pipeline-computed ISO date


def moved_usa_ticker_delete_sql(table: str, stage: str, cutoff: str) -> str:
    """DELETE US rows whose ticker this stage binds to a different game."""
    return f"""
        DELETE FROM {table} t
        WHERE {moved_usa_ticker_where(table, stage, cutoff)}
    """  # nosec B608 — table/stage are module constants, cutoff is a pipeline-computed ISO date


def clean_moved_usa_tickers(client: Any, table: str, stage: str, cutoff: str) -> int:
    """Delete US rows stranded on a game their ticker moved off; return count."""
    rows = list(client.query(
        moved_usa_ticker_detect_sql(table, stage, cutoff)).result())
    if not rows:
        print("  No moved Polymarket (USA) tickers.")
        return 0
    total = sum(int(r.n) for r in rows)
    for r in rows[:20]:
        print(f"  Moved US ticker: {r.ticker} left on {r.game_id} "
              f"{r.start_date} ({r.n} rows)")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
    sandbox_query(client, moved_usa_ticker_delete_sql(table, stage, cutoff))
    print(f"  Deleted {total} stranded Polymarket (USA) rows "
          f"({len(rows)} ticker/game pairs).")
    return total
