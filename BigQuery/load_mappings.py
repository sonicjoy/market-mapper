"""Load mapping rows from a JSONL file into markets_us.market_mapping.

Reads the table schema from BigQuery (single source of truth), transforms
the nested mapping format into flat rows, bulk-loads into a staging table,
then MERGEs into the main table.

Optic-unplayed fixtures upsert (WHEN MATCHED UPDATE). Fixtures Optic
marks is_live insert unmatched keys only — a live board must not
refresh or delete pre-match rows. Catalogue, orientation, and
reschedule DELETEs skip those Optic-live game_ids. In-play is Optic
status, not start_date.

Each mappings.jsonl record can produce rows for Kalshi, Prophet X, and/or
prediction markets (Polymarket, Novig, Polymarket (USA)) when identifiers
are present.  Records with optic_odds but no sportsbook identifiers are
skipped.  Records with crypto_com but no optic_odds are skipped —
crypto.com rows load only when an Optic odd supplies market_id.

Usage:
    .venv/bin/python -m BigQuery.load_mappings data/2026-03-12/06_40/mappings.jsonl
    .venv/bin/python -m BigQuery.load_mappings --limit 100 FILE
"""

import argparse
import collections
import io
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from google.cloud import bigquery

from BigQuery.client import ro_client, sandbox_query
from BigQuery.mapping_run_audit import append_run_lifecycle, read_mapping_run_meta
from BigQuery.override_lane import stage_override_lane, supersede_override_rows
from BigQuery.stale_book_rows import clean_stale_book_rows, same_key_sql
from BigQuery.usa_ticker_moves import clean_moved_usa_tickers
from mappers.exchanges.optic import OPTIC_MAPPED_SPORTSBOOKS
from mappers.fight_props import augment_selection
from mappers.market_types import MarketType
from mappers.sport import sport_for_league

TABLE = "markets_us.market_mapping"
# Staging table is per-pipeline, NOT shared. Two concurrent loads that
# WRITE_TRUNCATE the same stage clobber each other's batch and can both
# take the MERGE INSERT path for the same key (BigQuery enforces no unique
# constraint), producing exact duplicate rows in TABLE — the 2026-08-14
# Polymarket cs2/lol dup-key FATAL. The main pipeline keeps the default; the
# BQ-optic pipeline sets MAPPING_STAGE_TABLE to its own stage. TABLE stays
# shared on purpose (both write disjoint league rows into it via key-scoped
# MERGE). See BigQuery/docs/staging-isolation.md.
STAGE_TABLE = os.getenv("MAPPING_STAGE_TABLE", "markets_us.market_mapping_stage")

# MERGE key: the fields that uniquely identify a mapping row.
# Crypto FIX Symbol is NOT a table column — it lives in
# source_ids.symbol and is joined via JSON_VALUE (see
# SOURCE_SYMBOL_SQL / collapse_crypto_satellites) so twin live symbols
# for one canonical bet each keep a row without a Terraform column.
# Nullable columns use IS NOT DISTINCT FROM for NULL-safe matching.
KEY_COLUMNS = ["sport", "league", "start_date", "home", "away",
               "market_type", "entity", "line", "side", "group_key",
               "sportsbook"]
NULLABLE_KEYS = {"entity", "line", "group_key"}

# Non-key columns updated on MERGE match.
VALUE_COLUMNS = ["game_id", "fixture_id", "market_id", "selection",
                 "selection_line", "points", "grouping_key", "source_ids",
                 "last_updated"]

# Milestone 1 provenance — included in MERGE only when present in BQ schema
# (after mm-infrastructure Terraform apply).
PROVENANCE_COLUMNS = [
    "rule_set_id", "mapping_run_id", "mapper_git_commit",
    "mapping_logic_version", "market_rule_id", "entity_alias_ids",
    "fixture_rule_id", "mapping_audit_event_id",
    "fixture_match_method", "market_match_method", "verify_tier",
    "mapped_at",
]

ALL_COLUMNS = KEY_COLUMNS + VALUE_COLUMNS

# Crypto identity expression (NULL for non-crypto rows). Used in the
# crypto-scoped stale-symbol cleanup.
SOURCE_SYMBOL_SQL = "JSON_VALUE({alias}.source_ids, '$.symbol')"

# Keep a crypto symbol from shortly before kickoff through this many hours
# after start. Optic is_live alone misses the last prematch tick (Zverev
# moneyline deleted ~6 minutes before a 13:30 start).
INPLAY_SYMBOL_HOLD_HOURS = 4
INPLAY_SYMBOL_PRESTART_MINUTES = 30


def _quoted_ids(ids: set[str]) -> str:
    """Comma-separated SQL string literals, quotes doubled."""
    return ", ".join("'" + i.replace("'", "''") + "'" for i in sorted(ids))


def _not_optic_live(alias: str, live_game_ids: set[str]) -> str:
    """SQL predicate: this row is not from an Optic-live fixture in the batch.

    Empty live set → TRUE (whole batch upserts). In-play is Optic
    is_live via staged game_id, not start_date vs clock.
    """
    if not live_game_ids:
        return "TRUE"
    prefix = f"{alias}." if alias else ""
    return f"{prefix}game_id NOT IN ({_quoted_ids(live_game_ids)})"


def _outside_inplay_symbol_hold(alias: str) -> str:
    """SQL: start_date is outside the in-play crypto-symbol keep window.

    The window is ``INPLAY_SYMBOL_PRESTART_MINUTES`` before kickoff through
    ``INPLAY_SYMBOL_HOLD_HOURS`` after start. Rows inside it are not stale
    even when Optic has not set is_live.
    """
    prefix = f"{alias}." if alias else ""
    start = f"{prefix}start_date"
    return (
        f"{start} NOT BETWEEN "
        f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {INPLAY_SYMBOL_HOLD_HOURS} HOUR) "
        f"AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), "
        f"INTERVAL {INPLAY_SYMBOL_PRESTART_MINUTES} MINUTE)"
    )


def _optic_live_game_ids(records: list[dict]) -> set[str]:
    """Optic game_ids whose mapping records are Optic is_live."""
    live: set[str] = set()
    for rec in records:
        if not rec.get("optic_is_live"):
            continue
        gid = (rec.get("optic_odds") or {}).get("game_id")
        if gid:
            live.add(gid)
    return live


def _source_identity_sql(alias: str = "") -> str:
    """Source-identity extension of the MERGE key.

    Kept in lockstep between the MERGE ON clause and the duplicate-key guard so
    they cannot disagree. Two producers legitimately map two source rows to one
    canonical bet:
      * crypto.com — twin FIX Symbols (source_ids.symbol) for one bet each keep
        a row (RFQ joins on symbol);
      * Kalshi — a match is listed as two complementary side-tickers that
        resolve to the SAME canonical side (ticker A "yes" and ticker B "no"
        both mean "A wins", e.g. ITF doubles). Both rows are needed for the
        in-play (ticker, selection_id) lookup, so fall back to the Kalshi
        ticker+selection when there is no crypto symbol.
      * DKEX — the same shape as Kalshi and for the same reason: the venue
        lists both moneyline tickers for a game (one per team) and a
        bare/"OU" pair for one player prop, and the RFQ responder resolves
        a leg BY TICKER.  Without this, the second ticker would share the
        first's MERGE key and silently overwrite it -- measured 2026-09-15,
        that was one of the two moneyline tickers on every matched event.
      * STX -- the same shape: YES home_winner and NO away_winner are one
        canonical bet (the home team), and the maker looks a leg up by
        (market_id, selection_id).
    NULL for every other sportsbook, so their identity is unchanged.
    """
    p = f"{alias}." if alias else ""
    symbol = f"JSON_VALUE({p}source_ids, '$.symbol')"
    ticker_side = (
        f"CONCAT(JSON_VALUE({p}source_ids, '$.market_id'), '|', "
        f"JSON_VALUE({p}source_ids, '$.selection_id'))"
    )
    kalshi = f"IF({p}sportsbook = 'Kalshi', {ticker_side}, NULL)"
    dkex = f"IF({p}sportsbook = 'DKEX', {ticker_side}, NULL)"
    underdog = f"IF({p}sportsbook = 'Underdog', {ticker_side}, NULL)"
    stx = f"IF({p}sportsbook = 'STX', {ticker_side}, NULL)"
    return f"COALESCE({symbol}, {kalshi}, {dkex}, {underdog}, {stx})"


class RescheduleCleanup:
    """Result of analyzing staged rows for rescheduled games.

    Pure data — no BQ dependency.  Built from detection query results,
    consumed by _clean_reschedules() and testable in isolation.
    """
    __slots__ = ("delete_sql", "total", "game_count", "report")

    def __init__(self, stale_rows):
        """Build cleanup plan from detection query results.

        Each element of stale_rows must have .old_game_id,
        .old_start_date, .new_start_date, and .stale_rows attributes.
        Optionally .new_game_id for cross-date reschedules.
        """
        if not stale_rows:
            self.delete_sql = None
            self.total = 0
            self.game_count = 0
            self.report = []
            return

        self.report = []
        self.total = 0
        for row in stale_rows:
            old_gid = row.old_game_id
            new_gid = getattr(row, "new_game_id", None)
            gid_info = (f"  game_id changed: {old_gid} -> {new_gid}"
                        if new_gid and new_gid != old_gid else "")
            self.report.append(
                f"  Reschedule: {old_gid}  "
                f"{row.old_start_date} -> {row.new_start_date}  "
                f"({row.stale_rows} stale rows)"
                + gid_info
            )
            self.total += row.stale_rows

        old_times = list({(row.old_game_id, row.old_start_date)
                          for row in stale_rows})
        self.game_count = len({row.old_game_id for row in stale_rows})

        # Build WHERE clause: (game_id, start_date) IN (...)
        # The explicit DATE(start_date) IN (...) filter satisfies BQ's
        # required partition filter; the tuple IN does the real work.
        pairs = ", ".join(
            f"('{gid}', TIMESTAMP('{ts.isoformat()}'))"
            for gid, ts in old_times
        )
        unique_dates = sorted({ts.date().isoformat() for _, ts in old_times})
        date_filter = ", ".join(f"'{d}'" for d in unique_dates)
        self.delete_sql = f"""
        DELETE FROM {TABLE}
        WHERE DATE(start_date) IN ({date_filter})
            AND (game_id, start_date) IN ({pairs})
    """


# -- Reschedule detection --
#
# Problem: start_date is part of the MERGE key.  When a game is
# rescheduled between fetches, the new start_date doesn't match
# the existing row, so MERGE inserts a duplicate instead of updating.
#
# A simpler fix would be to make the downstream consumers (the
# mapping_loader.py query in MMkalshi and the Grafana coverage
# dashboard) resilient to these duplicates — e.g. DISTINCT, or
# ROW_NUMBER() to pick one row per ticker.  Picking by latest
# start_date would work only if reschedules always push forward;
# a game moved earlier would keep the stale later time.  Our
# pre-delete approach avoids this: the incoming batch is the
# current truth regardless of direction.  We went with this more
# complex approach because the downstream consumer code is in
# production for March Madness and changing it during the freeze
# is out of scope.
#
# We detect and delete stale rows before the MERGE, using three passes:
#
# Pass 1 — join on game_id.  Catches reschedules where the game_id
# stayed the same but start_date changed.  This is the common case:
# scanning 953 games across 55 fetches, 27 had time shifts and all
# kept their game_id (verified 2026-03-16).  Covers both Kalshi and
# PX rows.
#
# Pass 2 — join on Kalshi market_ticker + selection_id.  Catches
# cross-date reschedules where Optic changed the game_id (the date
# suffix in game_id shifts, e.g. 18107-33911-2026-02-14 →
# 18107-33911-2026-02-25) but Kalshi kept the same ticker.  We
# believe Kalshi tickers are stable across reschedules based on
# observed behaviour (see docs/kalshi-missing-game-tickers.md),
# though Kalshi doesn't explicitly guarantee this.  The delete
# targets (old_game_id, old_start_date), which removes all
# sportsbook rows for that stale game — so PX rows sharing the
# same old game_id are cleaned up too.
#
# Pass 3 — join on the Polymarket clob token.  Same shape as pass 2 for
# a book that has no Kalshi ticker; see the _DETECT_BY_POLY_TOKEN comment
# for the esports rename that made this a live defect rather than a
# theoretical one.
#
# Known gap: a PX-only game (no Kalshi and no Polymarket markets) that is
# rescheduled across a date boundary, causing its game_id to change.
# Pass 1 misses it (different game_id), passes 2 and 3 can't help (no
# stable exchange id to match on).  We haven't observed this combination
# yet — games with PX data almost always have Kalshi data too — but it
# could produce a stale duplicate if it occurs.  The post-merge
# _assert_no_duplicate_keys check would not catch it either, since
# the rows have different MERGE keys.  A future fix could join on
# PX event_id if it proves stable, but we haven't verified that.
#
# Partial-fetch risk: the delete targets (game_id, old_start_date)
# across ALL sportsbooks.  If one exchange's fetch failed (e.g. PX
# succeeded but Kalshi didn't), and a game was rescheduled, the
# delete removes Kalshi rows at the old time but the MERGE only
# re-inserts PX rows.  Kalshi data for that game is lost.  This
# only affects rescheduled games during a partial-fetch failure —
# the MERGE inserts unmatched keys and updates pre-game matches,
# and leaves unmatched existing rows in place.
# untouched.  The pipeline continues on partial fetches (Optic
# required, PX/Kalshi optional), so this risk is live but narrow:
# it requires a reschedule and a fetch failure in the same hour.
# The next successful full fetch (typically 1 hour later) restores
# the missing rows.  A future fix could scope the DELETE to only
# the sportsbooks present in the staged data.

# Both queries filter t.start_date to 60 days before the earliest staged
# date.  The table is partitioned on start_date; without this bound the
# join scans every partition.  60 days is generous — NBA/NCAAB games are
# never rescheduled by more than a few weeks.

# Partition-safe reschedule detection queries.
#
# The main table is partitioned on start_date with a required partition
# filter.  BQ won't accept a subquery as a partition bound, so we
# compute the cutoff date in Python and inject it as a literal via
# str.format ({cutoff}).

_DETECT_BY_GAME_ID = f"""
    SELECT
        t.game_id AS old_game_id,
        t.start_date AS old_start_date,
        s.start_date AS new_start_date,
        COUNT(*) AS stale_rows
    FROM {TABLE} t
    JOIN (
        SELECT DISTINCT game_id, start_date
        FROM {STAGE_TABLE}
    ) s ON t.game_id = s.game_id
    WHERE t.start_date >= TIMESTAMP('{{cutoff}}')
        AND t.start_date != s.start_date
        AND {{live_pred}}
    GROUP BY t.game_id, t.start_date, s.start_date
    ORDER BY t.game_id
"""

_DETECT_BY_KALSHI_TICKER = f"""
    SELECT
        t.game_id AS old_game_id,
        s.game_id AS new_game_id,
        t.start_date AS old_start_date,
        s.start_date AS new_start_date,
        COUNT(*) AS stale_rows
    FROM {TABLE} t
    JOIN {STAGE_TABLE} s
        ON STRING(t.source_ids.market_id) = STRING(s.source_ids.market_id)
        AND STRING(t.source_ids.selection_id) = STRING(s.source_ids.selection_id)
    WHERE t.start_date >= TIMESTAMP('{{cutoff}}')
        AND t.sportsbook = 'Kalshi'
        AND s.sportsbook = 'Kalshi'
        AND (t.start_date != s.start_date OR t.game_id != s.game_id)
        AND {{live_pred}}
    GROUP BY t.game_id, s.game_id, t.start_date, s.start_date
    ORDER BY t.game_id
"""

# Pass 3 — join on the Polymarket clob token (source_ids.selection_id).
# Catches the case passes 1 and 2 both miss: optic RE-ISSUES a fixture
# under a new id, so game_id changes and there is no Kalshi ticker to
# join on.  An esports roster rename does this — optic minted a second
# team record for one org ("Sangal", abbreviation SNG, alongside
# "ex-Sangal ALTERS", abbreviation empty so team_bootstrap coined ESA3)
# and published a fixture for each.  home/away and game_id are MERGE
# keys, so the tick that switched to the new record inserted a fresh row
# and orphaned the old one: 2026-08-20 left one clob token on both
# GOL3 v SNG @17:00 and GOL3 v ESA3 @17:10, and the 08-23 EAC Extra tie
# carried EACE v SNG alongside EACE v ESA3 for three days before its
# start (verified in prod 2026-08-21).  Pass 1 cannot see it (game_id
# differs), pass 2 cannot (esports has no Kalshi book), and
# _clean_stale_orientations is scoped to (game_id, start_date) so it
# never matches either.  Only _clean_stale_started reaped these, 24h
# AFTER the start — i.e. never while the rows could still be quoted.
#
# A clob token is one outcome of one Polymarket market and can settle on
# exactly one match, so a staged token disagreeing with an existing row's
# fixture makes that row stale by construction.  Polymarket only: a US
# row's selection_id is its venue side ("yes" / "no"), shared by every US
# row, so joining on it would reap across unrelated games; moved US
# symbols are cleaned by usa_ticker_moves on market_id instead.
# sportsbook is a clustering field, so the scan stays bounded.
_DETECT_BY_POLY_TOKEN = f"""
    SELECT
        t.game_id AS old_game_id,
        s.game_id AS new_game_id,
        t.start_date AS old_start_date,
        s.start_date AS new_start_date,
        COUNT(*) AS stale_rows
    FROM {TABLE} t
    JOIN {STAGE_TABLE} s
        ON STRING(t.source_ids.selection_id) = STRING(s.source_ids.selection_id)
        AND t.sportsbook = s.sportsbook
    WHERE t.start_date >= TIMESTAMP('{{cutoff}}')
        AND t.sportsbook = 'Polymarket'
        AND (t.start_date != s.start_date OR t.game_id != s.game_id)
        AND {{live_pred}}
    GROUP BY t.game_id, s.game_id, t.start_date, s.start_date
    ORDER BY t.game_id
"""


def _clean_reschedules(client, cutoff, live_game_ids: set[str] | None = None):
    """Delete stale rows from games whose start_date or game_id changed.

    cutoff: ISO date string, 60 days before the earliest staged date.
    Used as a partition bound so BQ can eliminate old partitions.

    Optic-live fixtures in this batch are excluded: a live tick that
    carries a drifted start_date must not delete pre-match rows.

    Two detection passes:
    1. Join on game_id — catches time shifts where game_id is stable
       (covers both Kalshi and PX rows).
    2. Join on Kalshi market_ticker + side — catches cross-date
       reschedules where Optic changed the game_id but Kalshi kept
       the same ticker.  The delete targets (old_game_id, old_start_date),
       which removes all sportsbook rows for that stale game.
    3. Join on the Polymarket clob token — catches a fixture re-issued
       under a new optic id (an esports roster rename mints a new team,
       hence a new game_id) where there is no Kalshi ticker to join on.
    """
    live_pred = _not_optic_live("s", live_game_ids or set())
    all_stale = []

    # Pass 1: game_id match
    stale = list(client.query(
        _DETECT_BY_GAME_ID.format(
            cutoff=cutoff, live_pred=live_pred,
        )).result())
    all_stale.extend(stale)

    # Pass 2: Kalshi ticker match (may find rows pass 1 missed)
    # Deduplicate: skip any (old_game_id, old_start_date) already found.
    already_found = {(r.old_game_id, r.old_start_date) for r in all_stale}
    kalshi_stale = list(client.query(
        _DETECT_BY_KALSHI_TICKER.format(
            cutoff=cutoff, live_pred=live_pred,
        )).result())
    for row in kalshi_stale:
        if (row.old_game_id, row.old_start_date) not in already_found:
            all_stale.append(row)
            already_found.add((row.old_game_id, row.old_start_date))

    # Pass 3: Polymarket clob-token match (fixture re-issued under a new
    # optic id, so passes 1 and 2 both miss it).
    poly_stale = list(client.query(
        _DETECT_BY_POLY_TOKEN.format(
            cutoff=cutoff, live_pred=live_pred,
        )).result())
    for row in poly_stale:
        if (row.old_game_id, row.old_start_date) not in already_found:
            all_stale.append(row)
            already_found.add((row.old_game_id, row.old_start_date))

    cleanup = RescheduleCleanup(all_stale)

    if not cleanup.delete_sql:
        print("  No reschedules detected.")
        return

    for line in cleanup.report:
        print(line)
    sandbox_query(client, cleanup.delete_sql)
    print(f"  Deleted {cleanup.total} stale rows from "
          f"{cleanup.game_count} rescheduled games.")


def _stale_started_delete_sql(cutoff: str, leagues: list[str]) -> str | None:
    """Build DELETE for mappings whose fixture started >24h ago.

    Returns None when leagues is empty.  Partition filter uses cutoff
    as the lower bound and CURRENT_DATE() as the upper bound so BQ
    can eliminate old partitions; the real predicate is start_date
    older than 24 hours.
    """
    if not leagues:
        return None
    league_in = ", ".join(f"'{lg}'" for lg in sorted(set(leagues)))
    return f"""
        DELETE FROM {TABLE}
        WHERE DATE(start_date) >= DATE('{cutoff}')
            AND DATE(start_date) <= CURRENT_DATE()
            AND start_date < TIMESTAMP_SUB(
                CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            AND league IN ({league_in})
    """


def _clean_stale_started(client, cutoff, leagues):
    """Delete rows for fixtures that started more than 24 hours ago.

    Safety net for delayed/resumed games: stale GREG mappings whose
    Optic fixture start_time is in the past can only produce
    FIXTURE_STARTED poison in a Greg-first RFQ resolver.  Downstream
    mapping_loader already filters to future start_dates, so nothing
    legitimate is lost.
    """
    delete_sql = _stale_started_delete_sql(cutoff, leagues)
    if delete_sql is None:
        print("  No leagues staged; skipping stale-started cleanup.")
        return

    league_in = ", ".join(f"'{lg}'" for lg in sorted(set(leagues)))
    detect_sql = f"""
        SELECT game_id, start_date, COUNT(*) AS n
        FROM {TABLE}
        WHERE DATE(start_date) >= DATE('{cutoff}')
            AND DATE(start_date) <= CURRENT_DATE()
            AND start_date < TIMESTAMP_SUB(
                CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            AND league IN ({league_in})
        GROUP BY game_id, start_date
        ORDER BY start_date
    """
    rows = list(client.query(detect_sql).result())
    if not rows:
        print("  No stale started-fixture rows.")
        return

    total = sum(int(r.n) for r in rows)
    for r in rows:
        print(f"  Stale started: {r.game_id}  {r.start_date}  ({r.n} rows)")
    sandbox_query(client, delete_sql)
    print(f"  Deleted {total} stale started-fixture rows from "
          f"{len(rows)} games.")


def _stale_crypto_symbol_delete_sql(
    date_in: str, live_game_ids: set[str] | None = None,
) -> str:
    """DELETE crypto.com rows whose FIX Symbol is absent from stage.

    Symbol identity is JSON_VALUE(source_ids, '$.symbol') — same as the
    MERGE key extension. Scoped to (game_id, start_date) pairs that have
    at least one staged crypto.com row — partial fetches that stage no
    crypto for a fixture leave that fixture's crypto rows untouched.
    Optic-live fixtures are excluded so a thinner in-play catalogue cannot
    delete symbols written before tip-off. Fixtures inside the in-play
    hold (30 minutes before start through 4 hours after) are excluded too.
    Partition filter uses staged dates so BQ can eliminate untouched
    partitions.
    """
    t_sym = SOURCE_SYMBOL_SQL.format(alias="t")
    s_sym = SOURCE_SYMBOL_SQL.format(alias="s")
    return f"""
        DELETE FROM {TABLE} t
        WHERE DATE(t.start_date) IN ({date_in})
            AND {_not_optic_live("t", live_game_ids or set())}
            AND {_outside_inplay_symbol_hold("t")}
            AND t.sportsbook = 'crypto.com'
            AND EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.sportsbook = 'crypto.com'
                    AND s.game_id = t.game_id
                    AND s.start_date = t.start_date
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.sportsbook = 'crypto.com'
                    AND s.game_id = t.game_id
                    AND s.start_date = t.start_date
                    AND {s_sym} IS NOT DISTINCT FROM {t_sym}
            )
    """


def _stale_crypto_symbol_detect_sql(
    date_in: str, live_game_ids: set[str] | None = None,
) -> str:
    """SELECT delisted crypto symbols for Optic-unplayed staged fixtures."""
    ids = live_game_ids or set()
    t_sym = SOURCE_SYMBOL_SQL.format(alias="t")
    s_sym = SOURCE_SYMBOL_SQL.format(alias="s")
    return f"""
        SELECT t.game_id, t.start_date, {t_sym} AS source_symbol, COUNT(*) AS n
        FROM {TABLE} t
        WHERE DATE(t.start_date) IN ({date_in})
            AND {_not_optic_live("t", ids)}
            AND {_outside_inplay_symbol_hold("t")}
            AND t.sportsbook = 'crypto.com'
            AND EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.sportsbook = 'crypto.com'
                    AND s.game_id = t.game_id
                    AND s.start_date = t.start_date
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.sportsbook = 'crypto.com'
                    AND s.game_id = t.game_id
                    AND s.start_date = t.start_date
                    AND {s_sym} IS NOT DISTINCT FROM {t_sym}
            )
        GROUP BY t.game_id, t.start_date, source_symbol
        ORDER BY t.start_date, t.game_id
    """


def _clean_stale_crypto_symbols(
    client, date_in: str, live_game_ids: set[str] | None = None,
) -> None:
    """Drop delisted crypto symbols for Optic-unplayed fixtures in this stage.

    MERGE is a pure upsert, so symbols that leave the catalogue would
    otherwise linger. Incoming batch is truth for each staged unplayed
    crypto fixture. Optic-live fixtures are insert-only — a thinner
    in-play catalogue must not delete symbols written before go-live.
    The same skip covers the 4-hour in-play hold around start_date.
    """
    ids = live_game_ids or set()
    rows = list(client.query(
        _stale_crypto_symbol_detect_sql(date_in, ids),
    ).result())
    if not rows:
        print("  No stale crypto symbols.")
        return
    total = sum(int(r.n) for r in rows)
    for r in rows[:20]:
        print(
            f"  Stale crypto symbol: {r.game_id}  {r.start_date}  "
            f"{r.source_symbol}  ({r.n} rows)"
        )
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
    sandbox_query(client, _stale_crypto_symbol_delete_sql(date_in, ids))
    print(f"  Deleted {total} stale crypto.com rows "
          f"({len(rows)} symbols).")


def _stale_orientation_delete_sql(
    date_in: str, live_game_ids: set[str] | None = None,
) -> str:
    """DELETE rows whose (home, away) disagrees with the staged fixture.

    home/away/side are MERGE keys, so a fixture whose canonical team or
    player codes change keeps its pre-change rows forever: the same
    fixture ends up with two orientations, and a code can mean one player
    in the old rows and another in the new.  Tennis hit this when the
    bootstrap reassigned ITF codes between runs (MMA|IVA2 alongside
    MMA2|IVA2 for one match).  The staged batch is truth for any
    Optic-unplayed fixture it refreshes — Optic-live fixtures are
    insert-only.

    Scoped to (game_id, start_date) pairs present in stage, so a fixture
    this batch didn't fetch is left untouched.
    """
    return f"""
        DELETE FROM {TABLE} t
        WHERE DATE(t.start_date) IN ({date_in})
            AND {_not_optic_live("t", live_game_ids or set())}
            AND EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.game_id = t.game_id
                    AND s.start_date = t.start_date
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.game_id = t.game_id
                    AND s.start_date = t.start_date
                    AND s.home = t.home
                    AND s.away = t.away
            )
    """


def _clean_stale_orientations(
    client, date_in: str, live_game_ids: set[str] | None = None,
) -> None:
    """Drop rows left behind by a home/away code change."""
    ids = live_game_ids or set()
    detect_sql = f"""
        SELECT t.game_id, t.start_date, t.league, t.home, t.away,
               COUNT(*) AS n
        FROM {TABLE} t
        WHERE DATE(t.start_date) IN ({date_in})
            AND {_not_optic_live("t", ids)}
            AND EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.game_id = t.game_id
                    AND s.start_date = t.start_date
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {STAGE_TABLE} s
                WHERE s.game_id = t.game_id
                    AND s.start_date = t.start_date
                    AND s.home = t.home
                    AND s.away = t.away
            )
        GROUP BY t.game_id, t.start_date, t.league, t.home, t.away
        ORDER BY t.start_date, t.game_id
    """
    rows = list(client.query(detect_sql).result())
    if not rows:
        print("  No stale orientations.")
        return
    total = sum(int(r.n) for r in rows)
    for r in rows[:20]:
        print(
            f"  Stale orientation: {r.game_id}  {r.start_date}  "
            f"{r.league}  {r.home}|{r.away}  ({r.n} rows)"
        )
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
    sandbox_query(client, _stale_orientation_delete_sql(date_in, ids))
    print(f"  Deleted {total} stale-orientation rows "
          f"({len(rows)} fixtures).")


def _assert_no_duplicate_keys(client, table, where_clause=""):
    """Abort if the table has any duplicate key groups."""
    # Extend KEY_COLUMNS with the source identity (crypto symbol, else the
    # Kalshi ticker+selection) so twin source rows for one canonical bet are
    # distinct groups — same identity as MERGE ON.
    key_cols = ", ".join([*KEY_COLUMNS, _source_identity_sql()])
    sql = f"""
        SELECT {key_cols}, COUNT(*) AS c
        FROM {table}
        {where_clause}
        GROUP BY {key_cols}
        HAVING c > 1
        LIMIT 5
    """
    result = list(client.query(sql).result())
    if result:
        print(f"FATAL: {len(result)}+ duplicate key groups in {table}:")
        for row in result:
            print(f"  {dict(row)}")
        sys.exit(1)


def _build_merge_sql(date_in, value_columns=None, live_game_ids=None):
    """Build the MERGE statement for upserting from stage into main table.

    date_in: SQL literal list of staged dates, e.g. "'2026-03-18', '2026-03-19'".

    The target table is partitioned on start_date with a required partition
    filter.  A join condition alone doesn't satisfy BQ's partition
    elimination, so we inject the staged dates as literals in the ON clause.
    (IN subqueries are not allowed in join predicates.)

    Optic-live game_ids insert unmatched keys only. Unplayed fixtures
    still upsert so a later pre-match tick can refresh.
    """
    value_columns = list(value_columns or VALUE_COLUMNS)
    all_columns = KEY_COLUMNS + value_columns
    on_clauses = []
    for col in KEY_COLUMNS:
        if col in NULLABLE_KEYS:
            on_clauses.append(f"t.{col} IS NOT DISTINCT FROM s.{col}")
        else:
            on_clauses.append(f"t.{col} = s.{col}")
    # Source identity (crypto symbol, else Kalshi ticker+selection) — NULL for
    # other sportsbooks.
    on_clauses.append(
        f"{_source_identity_sql('t')} IS NOT DISTINCT FROM "
        f"{_source_identity_sql('s')}"
    )

    update_sets = ", ".join(f"{col} = s.{col}" for col in value_columns)
    insert_cols = ", ".join(all_columns)
    insert_vals = ", ".join(f"s.{col}" for col in all_columns)

    partition_filter = f"DATE(t.start_date) IN ({date_in})"
    ids = live_game_ids or set()
    if ids:
        matched = (
            f"WHEN MATCHED AND {_not_optic_live('s', ids)} "
            f"THEN UPDATE SET {update_sets}"
        )
    else:
        matched = f"WHEN MATCHED THEN UPDATE SET {update_sets}"

    return f"""
MERGE INTO {TABLE} AS t
USING {STAGE_TABLE} AS s
ON {partition_filter} AND {' AND '.join(on_clauses)}
{matched}
WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
"""


def _optic_base(k: dict, o: dict, now_ts: str) -> dict:
    """Shared staging columns from the canonical key and optic_odds block."""
    selection = o["selection"]
    # method_of_victory: fold the canonical method (already parsed into the
    # group_key key column during build_rows) into the selection VALUE column,
    # so the two fighter contracts that differ only by Optic `name`
    # ("Fighter - Decision" vs "Fighter - KO/TKO/DQ") get distinct selections.
    # This keeps the trading-leg selection byte-identical to the price
    # service's live fair-price selection (both use augment_selection). Only
    # the VALUE column changes — entity/side/line and the group_key KEY column
    # (hence row_key / the MERGE key) are untouched.
    if k["market_type"] == MarketType.METHOD_OF_VICTORY.value and k.get("grouping_key"):
        selection = augment_selection(selection, k["grouping_key"])
    return {
        "sport": k.get("sport") or sport_for_league(k["league"]),
        "league": k["league"],
        "start_date": k["start_date"],
        "home": k["home"],
        "away": k["away"],
        "market_type": k["market_type"],
        "entity": k.get("entity"),
        "line": k.get("line"),
        "side": k["side"],
        "group_key": k.get("grouping_key"),
        "game_id": o["game_id"],
        "fixture_id": o["fixture_id"],
        "market_id": o["market_id"],
        "selection": selection,
        "selection_line": o.get("selection_line"),
        "points": o.get("points"),
        "grouping_key": o["grouping_key"],
        "last_updated": now_ts,
    }


def _crypto_source_ids(cc: dict) -> dict:
    """FIX vocab for crypto.com source_ids; PM.NPO market_id when decoded."""
    source_ids = {
        "security_id": cc["security_id"],
        "symbol": cc["symbol"],
    }
    optic_market_id = cc.get("market_id")
    if isinstance(optic_market_id, str) and "PM.NPO" in optic_market_id:
        source_ids["market_id"] = optic_market_id
    return source_ids


def _line_agrees_with_optic(key: dict, optic: dict) -> bool:
    """False when both key.line and optic.points are set and disagree.

    Optic serializes missing points as 0.0; treat that as absent when the
    mapping key also has no line (moneyline / 3-way).
    """
    key_line = key.get("line")
    points = optic.get("points")
    if key_line is None:
        return True
    if points is None:
        return True
    # Optic JSON uses 0.0 for null points — only compare when key has a line
    # and points look like a real threshold (or exact 0.0 game total).
    if points == 0.0 and key_line != 0.0:
        return True
    return float(key_line) == float(points)


def _crypto_agrees_with_optic(cc: dict, optic_src: dict) -> bool:
    """False when both carry Optic PM.NPO market_id and they differ.

    Mapper is authoritative for Kalshi/PX (stale/sibling keep-ours leaves
    Optic source_ids disagreeing on purpose).  Crypto PM.NPO equality is
    safe to re-check here: both sides are Optic-shaped ids.
    """
    src = optic_src.get("crypto.com")
    if not isinstance(src, dict):
        return True
    optic_mid = src.get("market_id")
    our_mid = cc.get("market_id")
    if not (isinstance(optic_mid, str) and "PM.NPO" in optic_mid):
        return True
    if not (isinstance(our_mid, str) and "PM.NPO" in our_mid):
        return True
    return optic_mid == our_mid


def _provenance_fields(rec: dict) -> dict:
    """Extract market_mapping provenance columns from a mapping record."""
    prov = rec.get("provenance") or {}
    return {
        k: prov[k]
        for k in PROVENANCE_COLUMNS
        if k in prov and prov[k] is not None
    }


def _emit_crypto_com(base, cc, optic_src, o, prov, line_ok):
    """Yield the crypto.com staging row, or nothing when gated out."""
    if not line_ok or cc is None:
        return
    if not _crypto_agrees_with_optic(cc, optic_src):
        print(
            f"  load: skip crypto.com on {o.get('fixture_id')} — "
            f"market_id ≠ optic crypto.com source_ids "
            f"(missing > wrong)",
            file=sys.stderr,
        )
        return
    yield {
        **base,
        "sportsbook": "crypto.com",
        "source_ids": _crypto_source_ids(cc),
        **prov,
    }


def note_crypto_dropped(rec, counter) -> None:
    """Count a crypto.com row the mapper built but that has no Optic market."""
    if rec.get("crypto_com"):
        counter[(rec.get("key") or {}).get("league") or "?"] += 1


def flatten_rows(rec, now_ts):
    """Yield one row per exchange (sportsbook) from a nested mapping record.

    Kalshi, Prophet X, crypto.com, and Runshop rows come from pipeline match
    present.  Novig and Polymarket rows come from EITHER the matcher's
    constructed ids (rec["polymarket"] / rec["novig"], for contracts optic
    itself never mapped) OR the matching optic_odds.source_ids passthrough —
    never both, so a record never double-emits a row for either book.  A
    single record can yield multiple rows.  crypto.com is emitted only
    from rec["crypto_com"] (Optic-decoded or FIX fallback) — never from
    OPTIC_MAPPED_SPORTSBOOKS.  crypto_satellite records emit crypto.com
    only; parent already owns Optic passthrough books.  No optic_odds →
    no rows (including crypto.com): without an Optic market_id there is
    nothing to join.

    Load-time gates (missing > wrong), layered on mapper verify:
      * key.line ≠ optic points → skip constructed exchange stamps only;
        still emit Optic source_ids passthrough (Novig / Poly USA / …).
      * crypto.com PM.NPO market_id ≠ optic crypto.com source → skip crypto.
    Kalshi/PX are not re-checked against optic source_ids here: the mapper
    intentionally keeps our id when Optic cites a stale/sibling reference.
    """
    k = rec["key"]
    o = rec.get("optic_odds")
    cc = rec.get("crypto_com")

    if o is None:
        return

    line_ok = _line_agrees_with_optic(k, o)
    if not line_ok:
        print(
            f"  load: key.line {k.get('line')!r} ≠ optic points "
            f"{o.get('points')!r} on {o.get('fixture_id')} — skipping "
            f"constructed exchange stamps, keeping Optic passthrough "
            f"(missing > wrong)",
            file=sys.stderr,
        )

    base = _optic_base(k, o, now_ts)
    prov = _provenance_fields(rec)
    optic_src = o.get("source_ids") or {}

    # Satellite exists only to carry a second FIX symbol. Re-emitting
    # Optic passthrough books (Polymarket/Novig/…) duplicates the parent.
    if rec.get("crypto_satellite"):
        yield from _emit_crypto_com(base, cc, optic_src, o, prov, line_ok)
        return

    if rec.get("dkex_satellite"):
        # A second DKEX ticker for a bet the parent row already emits.
        # Emit DKEX alone, before any other book: re-emitting the parent's
        # Optic passthrough books would collide with it on the same MERGE
        # key, exactly as for a crypto satellite above.
        dk_sat = rec.get("dkex")
        if line_ok and dk_sat is not None:
            yield {**base, "sportsbook": "DKEX",
                   "source_ids": {"market_id": dk_sat["market_ticker"],
                                  "selection_id": dk_sat["side"]}, **prov}
        return

    if rec.get("underdog_satellite"):
        ud_sat = rec.get("underdog")
        if line_ok and ud_sat is not None:
            yield {**base, "sportsbook": "Underdog",
                   "source_ids": {"market_id": ud_sat["market_id"],
                                  "selection_id": ud_sat["selection_id"]}, **prov}
        return

    if rec.get("stx_satellite"):
        stx_sat = rec.get("stx")
        if line_ok and stx_sat is not None:
            yield {**base, "sportsbook": "STX", "source_ids": dict(stx_sat), **prov}
        return

    if rec.get("polymarket_usa_satellite"):
        # A US symbol priced off another bet's Optic odd, keyed as its own
        # bet: emit Polymarket (USA) alone, never the odd's other books.
        pusa_sat = rec.get("polymarket_usa")
        if line_ok and pusa_sat is not None and pusa_sat.get("market_id"):
            yield {**base, "sportsbook": "Polymarket (USA)",
                   "source_ids": _usa_source_ids(pusa_sat["market_id"], pusa_sat),
                   **prov}
        return

    if rec.get("kalshi_complement"):
        if line_ok and rec.get("kalshi"):
            kal = rec["kalshi"]
            yield {**base, "sportsbook": "Kalshi",
                   "source_ids": {"market_id": kal["market_ticker"],
                                   "selection_id": kal["side"]}, **prov}
        return

    if line_ok and rec.get("kalshi"):
        kal = rec["kalshi"]
        yield {**base, "sportsbook": "Kalshi",
               "source_ids": {"market_id": kal["market_ticker"],
                               "selection_id": kal["side"]}, **prov}

    if line_ok and rec.get("prophet_x"):
        px = rec["prophet_x"]
        yield {**base, "sportsbook": "Prophet X",
               "source_ids": {"event_id": str(px["event_id"]),
                               "selection_id": px["line_id"]}, **prov}

    yield from _emit_crypto_com(base, cc, optic_src, o, prov, line_ok)

    if line_ok:
        rs = rec.get("runshop")
        if rs is not None:
            yield {**base, "sportsbook": "Runshop",
                   "source_ids": {
                       "fixture_id": str(rs["tx_odds_fixture_id"]),
                       "market_id": str(rs["market_id"]),
                   }, **prov}

        hd = rec.get("huddle")
        if hd is not None:
            yield {**base, "sportsbook": "Huddle",
                   "source_ids": {
                       "selection_id": str(hd["selection_id"]),
                       "event_id": str(hd["event_id"]),
                       "market_id": str(hd["market_id"]),
                   }, **prov}

    pm = rec.get("polymarket")
    if line_ok and pm is not None and "Polymarket" not in optic_src:
        # Constructed Polymarket row: the matcher (mappers/exchanges/
        # polymarket.py) mapped this token, but optic's own source_ids
        # never carried a "Polymarket" entry for it (optic-unmapped).
        # Gated so we never double-emit against the passthrough loop
        # below when optic DOES already have a "Polymarket" source_id —
        # both would share the same sportsbook MERGE key.
        yield {**base, "sportsbook": "Polymarket",
               "source_ids": {"selection_id": pm["clob_token_id"]}, **prov}

    pusa = rec.get("polymarket_usa")
    if (line_ok and pusa is not None and pusa.get("market_id")
            and "Polymarket (USA)" not in optic_src):
        yield {**base, "sportsbook": "Polymarket (USA)",
               "source_ids": _usa_source_ids(pusa["market_id"], pusa), **prov}

    nv = rec.get("novig")
    if line_ok and nv is not None and "Novig" not in optic_src:
        # Constructed Novig row: our matcher (mappers/exchanges/novig.py)
        # mapped this outcome off the Novig API, but optic's own source_ids
        # never carried a "Novig" entry for it.  Gated exactly like the
        # Polymarket case above so we never double-emit against the
        # passthrough loop below — both would share the same MERGE key.
        # The id triple is byte-identical in shape to optic's own Novig
        # source_ids, so downstream joins cannot tell the paths apart.
        yield {**base, "sportsbook": "Novig",
               "source_ids": {"event_id": nv["event_id"],
                              "market_id": nv["market_id"],
                              "selection_id": nv["outcome_id"]}, **prov}

    dk = rec.get("dkex")
    if line_ok and dk is not None:
        # DKEX is not an OpticOdds book -- Optic's source_ids never carry
        # one -- so unlike Novig/Polymarket there is no passthrough to
        # gate against.  The id pair is Kalshi-shaped on purpose: one
        # symbol is one binary market and the side is what picks the leg,
        # which is exactly what the responder joins on.
        yield {**base, "sportsbook": "DKEX",
               "source_ids": {"market_id": dk["market_ticker"],
                              "selection_id": dk["side"]}, **prov}

    ud = rec.get("underdog")
    if line_ok and ud is not None:
        yield {**base, "sportsbook": "Underdog",
               "source_ids": {"market_id": ud["market_id"],
                              "selection_id": ud["selection_id"]}, **prov}

    stx = rec.get("stx")
    if line_ok and stx is not None:
        # STX is not an OpticOdds book. source_ids = {market_id, selection_id yes|no, event_id, tie_pays_half};
        # tie_pays_half is a JSON bool and always present: the maker refuses a leg that is true or missing.
        yield {**base, "sportsbook": "STX", "source_ids": dict(stx), **prov}

    sx = rec.get("sxbet")
    if line_ok and sx is not None and "SX Bet" not in optic_src:
        # Constructed SX Bet row: our matcher (mappers/exchanges/sxbet_pass.py)
        # mapped this (hash, side) off SX's own catalogue, and optic's
        # source_ids carry no "SX Bet" entry for this odd.  Gated exactly
        # like Novig so the passthrough loop below never double-emits on the
        # same MERGE key.  The id triple is Optic's own SX shape
        # (selection_id "<hash>|one|two", the suffix the MAKER's outcome).
        yield {**base, "sportsbook": "SX Bet",
               "source_ids": {"event_id": sx["event_id"],
                              "market_id": sx["market_id"],
                              "selection_id": sx["selection_id"]}, **prov}

    for sportsbook in OPTIC_MAPPED_SPORTSBOOKS:
        src = optic_src.get(sportsbook)
        if src and sportsbook == "Polymarket (USA)" and isinstance(src, dict):
            src = _usa_source_ids(src.get("market_id"), pusa, base=src)
        if src:
            yield {**base, "sportsbook": sportsbook, "source_ids": src, **prov}


def _usa_source_ids(market_id, pusa: dict | None, base: dict | None = None) -> dict:
    """Polymarket US source_ids: the symbol plus the typed venue side.

    ``selection_id`` ("yes" / "no") is the side the mapper read off the
    gateway's typed fields, Kalshi's (ticker, selection_id) convention; the
    maker takes it as given. It is attached only when the mapper derived it
    for this same symbol, so an Optic passthrough the bind never reproduced
    keeps no side rather than a borrowed one.
    """
    out = dict(base or {})
    out["market_id"] = market_id
    side = (pusa or {}).get("selection_id")
    ours = (pusa or {}).get("market_id")
    if side and (ours is None or ours == market_id):
        out["selection_id"] = side
    return out


def collapse_crypto_satellites(rows: list[dict]) -> tuple[list[dict], int]:
    """Keep one crypto.com row per (merge key + symbol): the freshest listing.

    attach_crypto_row (mappers/pipeline.py) emits a separate row per live
    crypto symbol for the same canonical bet ("satellites"). Two cases:

    1. **True re-lists** — crypto.com re-issues the same FIX Symbol under
       a newer SecurityID. Identity includes ``source_ids.symbol``, so
       these still collide and must collapse to max security_id (same
       winner rule as crypto_com.dedupe_superseded). Observed need:
       MLB doubleheader re-lists PIT@CLE / TB@BOS, 2026-07-17/18 —
       without collapse, 21 loads aborted on duplicate keys.

    2. **Distinct live symbols for one canonical bet** — e.g. MLB
       ``To Get A Hit`` Yes and ``Total Hits Milestones`` Over 0.5 share
       (market_type, entity, line, side) but RFQ on different symbols.
       Before symbol was part of the key, collapse dropped the older
       SecurityID twin and ~18k RFQ legs / 5h could never resolve
       (prod alert 2026-07-30). Distinct symbols now survive as separate
       rows; RFQ joins ``source_ids.symbol`` verbatim.

    Missing security_id never raises — keep the incumbent and continue.
    Only crypto.com rows collapse; a duplicate key on any other
    sportsbook still trips the pre-merge assertion.

    Returns (rows, n_collapsed); input order is preserved, winners
    replace the loser in place.
    """
    out: list[dict] = []
    first_pos: dict[tuple, int] = {}
    collapsed = 0
    for row in rows:
        if row["sportsbook"] != "crypto.com":
            out.append(row)
            continue
        k = _row_merge_key(row)
        i = first_pos.get(k)
        if i is None:
            first_pos[k] = len(out)
            out.append(row)
            continue
        collapsed += 1
        if _crypto_row_preferred(row, out[i]):
            out[i] = row
    return out, collapsed


#: Books whose MERGE identity is ``market_id|selection_id`` — keep in step with
#: the IF(...) branches of _source_identity_sql.
_TICKER_KEYED_BOOKS = frozenset({"Kalshi", "DKEX", "Underdog", "STX"})


def _row_merge_key(row: dict) -> tuple:
    """Full merge identity: KEY_COLUMNS + source identity. Mirrors
    _source_identity_sql — crypto symbol, else the ticker+selection of the
    ticker-keyed books (Kalshi, DKEX, Underdog). Must list the same books as
    the SQL, or twin tickers collide here and the whole load aborts."""
    src = row.get("source_ids") or {}
    identity = src.get("symbol")
    if identity is None and row.get("sportsbook") in _TICKER_KEYED_BOOKS:
        market_id = src.get("market_id")
        selection_id = src.get("selection_id")
        if market_id is not None and selection_id is not None:
            identity = f"{market_id}|{selection_id}"
    return tuple(row.get(f) for f in KEY_COLUMNS) + (identity,)


def _crypto_row_preferred(candidate: dict, incumbent: dict) -> bool:
    """Prefer the row with the newer security_id when both have one."""
    cand = (candidate.get("source_ids") or {}).get("security_id")
    inc = (incumbent.get("source_ids") or {}).get("security_id")
    if cand is None:
        return False
    if inc is None:
        return True
    return cand > inc


def load(path, limit=None):
    run_meta = read_mapping_run_meta(path)
    run_id = run_meta.get("mapping_run_id")
    if run_id:
        append_run_lifecycle(str(run_id), phase="started")

    # -- Connect and read schema from the staging table --
    print("Connecting to BigQuery...")
    client = ro_client()

    print(f"Reading schema from {STAGE_TABLE}...")
    table = client.get_table(STAGE_TABLE)
    schema = table.schema
    column_names = {field.name for field in schema}
    print(f"  {len(schema)} columns: {', '.join(f.name for f in schema)}")
    # Provenance columns land after Terraform M1; MERGE only those present.
    merge_value_columns = [
        c for c in VALUE_COLUMNS + PROVENANCE_COLUMNS if c in column_names
    ]
    missing_core = [c for c in VALUE_COLUMNS if c not in column_names]
    if missing_core:
        sys.exit(
            f"Staging schema missing required value columns: {missing_core}"
        )
    provenance_present = [c for c in PROVENANCE_COLUMNS if c in column_names]
    if provenance_present:
        print(f"  provenance columns in MERGE: {', '.join(provenance_present)}")
    else:
        print("  provenance columns not in schema yet (pre-M1 Terraform)")

    # -- Timestamp for last_updated --
    now_ts = datetime.now(UTC).isoformat()

    # -- Read and transform rows --
    # Skip records with no Optic match and no crypto.com row.  Skip
    # records with no loadable sportsbook.  One input record can yield
    # multiple BQ rows.
    print(f"Reading {path}...")
    rows = []
    skipped_no_optic = 0
    crypto_dropped_no_optic: collections.Counter = collections.Counter()
    skipped_no_exchange = 0
    total = 0
    hit_limit = False
    live_game_ids: set[str] = set()
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            total += 1
            rec = json.loads(line)
            live_game_ids |= _optic_live_game_ids([rec])
            if rec.get("optic_odds") is None:
                skipped_no_optic += 1
                note_crypto_dropped(rec, crypto_dropped_no_optic)
                continue

            emitted = False
            for row in flatten_rows(rec, now_ts):
                # Sanity check: every key in the row must be a column in the table.
                extra = set(row.keys()) - column_names
                if extra:
                    sys.exit(
                        f"Row {line_num}: unexpected fields {extra} not in table schema. "
                        f"Table has: {column_names}"
                    )

                rows.append(row)
                emitted = True
                if limit and len(rows) >= limit:
                    hit_limit = True
                    break

            if not emitted:
                skipped_no_exchange += 1
            if hit_limit:
                break

    print(
        f"  {total} lines read, {skipped_no_optic} skipped (no optic), "
        f"{skipped_no_exchange} skipped (no exchange), {len(rows)} to load"
        + (f", {len(live_game_ids)} Optic-live game_ids (insert-only)"
           if live_game_ids else "")
    )
    if crypto_dropped_no_optic:
        # Built by the mapper but no Optic market to join: never loaded.
        print(
            f"  crypto.com built but dropped (no optic market): "
            f"{sum(crypto_dropped_no_optic.values())} "
            f"{dict(crypto_dropped_no_optic.most_common())}"
        )
    rows, n_satellites = collapse_crypto_satellites(rows)
    if n_satellites:
        print(
            f"  collapsed {n_satellites} crypto satellite rows "
            f"(same key+symbol, multiple SecurityIDs; kept max security_id)"
        )
    rows, override_lane = stage_override_lane(client, rows, column_names)
    if not rows:
        sys.exit("No rows to load.")

    # -- Write transformed rows to JSONL buffer --
    print("Writing JSONL buffer...")
    buf = io.BytesIO()
    for row in rows:
        buf.write(json.dumps(row).encode("utf-8"))
        buf.write(b"\n")
    buf.seek(0)
    buf_size = buf.getbuffer().nbytes
    print(f"  {buf_size:,} bytes")

    # -- Stage: bulk-load into the staging table (WRITE_TRUNCATE) --
    print(f"Loading into {STAGE_TABLE} (WRITE_TRUNCATE)...")

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_file(buf, STAGE_TABLE, job_config=job_config)

    # Wait for the job and check for errors.
    job.result()
    if job.errors:
        print("ERRORS:")
        for err in job.errors:
            print(f"  {err}")
        sys.exit(1)

    print(f"  Staged {job.output_rows} rows")

    # -- Pre-merge: assert no duplicate keys in staging --
    # The pipeline's dict-based merge guarantees unique keys in the
    # input, but we check both in-memory (fast, free, better context)
    # and in BQ (confirms what was actually loaded matches).
    print("Checking for duplicate keys...")
    seen_keys: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        k = _row_merge_key(row)
        if k in seen_keys:
            sys.exit(
                f"Duplicate key in row {i} (first seen at row {seen_keys[k]}): "
                f"{dict(zip([*KEY_COLUMNS, 'source_symbol'], k, strict=False))}"
            )
        seen_keys[k] = i
    _assert_no_duplicate_keys(client, STAGE_TABLE)

    # -- Staged dates & partition helpers --
    # Fetched once and reused by reschedule cleanup, MERGE, and
    # post-merge duplicate check.  All three need date literals so BQ
    # can do partition elimination (IN subqueries aren't allowed in
    # join predicates).
    stage_dates = sorted(
        row.d.isoformat()
        for row in client.query(
            f"SELECT DISTINCT DATE(start_date) AS d FROM {STAGE_TABLE}"
        ).result()
    )
    date_in = ", ".join(f"'{d}'" for d in stage_dates)
    cutoff = (date.fromisoformat(stage_dates[0]) - timedelta(days=60)).isoformat()

    # If a game's start_date changed since the last load, delete the
    # old-time rows so the MERGE doesn't create duplicates.
    print("Checking for rescheduled games...")
    _clean_reschedules(client, cutoff, live_game_ids)

    # Pass 3: drop mappings whose fixture started >24h ago (poison for
    # Greg-first RFQ).  Scope to leagues present in this stage batch.
    stage_leagues = sorted(
        row.league
        for row in client.query(
            f"SELECT DISTINCT league FROM {STAGE_TABLE}"
        ).result()
    )
    print("Checking for stale started-fixture rows...")
    _clean_stale_started(client, cutoff, stage_leagues)

    # Drop crypto.com rows whose FIX Symbol left the live catalogue for
    # fixtures this stage is refreshing (MERGE alone would leave them).
    print("Checking for stale crypto symbols...")
    _clean_stale_crypto_symbols(client, date_in, live_game_ids)
    print("Checking for moved Polymarket (USA) tickers...")
    clean_moved_usa_tickers(client, TABLE, STAGE_TABLE, cutoff)
    print("Checking for relabeled Kalshi and dropped Polymarket rows...")
    clean_stale_book_rows(
        client, TABLE, STAGE_TABLE, date_in,
        same_key=same_key_sql(KEY_COLUMNS, NULLABLE_KEYS),
        polymarket_guard=(
            f"{_not_optic_live('t', live_game_ids)} "
            f"AND {_outside_inplay_symbol_hold('t')}"
        ),
    )

    # Drop rows whose home/away no longer matches the staged fixture —
    # a canonical code change would otherwise leave the fixture with two
    # orientations, since home/away/side are MERGE keys.
    print("Checking for stale orientations...")
    _clean_stale_orientations(client, date_in, live_game_ids)

    supersede_override_rows(
        client, override_lane, table=TABLE, stage_table=STAGE_TABLE,
        cutoff=cutoff, run_dml=sandbox_query,
    )

    # -- MERGE: upsert from staging into main table --
    merge_sql = _build_merge_sql(
        date_in, value_columns=merge_value_columns,
        live_game_ids=live_game_ids,
    )
    print(f"Merging {STAGE_TABLE} -> {TABLE}...")
    sandbox_query(client, merge_sql)

    # -- Post-merge: assert no duplicate keys in target --
    # Belt-and-suspenders: catches anything the pre-merge couldn't
    # anticipate (e.g. a bug in the MERGE ON clause).
    # start_date is part of the key, so duplicates can only exist within
    # the same partition.  Restrict to partitions the MERGE touched.
    print("Checking target table for duplicate keys...")
    _assert_no_duplicate_keys(
        client, TABLE,
        where_clause=f"WHERE DATE(start_date) IN ({date_in})",
    )

    blocks_path = Path(path).parent / "optic_crosscheck_blocks.jsonl"
    try:
        from BigQuery.optic_crosscheck_blocks import load_blocks_file

        n_blocks = load_blocks_file(blocks_path)
        if n_blocks:
            print(f"Merged {n_blocks} optic passthrough blocklist row(s)")
    except Exception as exc:  # noqa: BLE001 — blocklist is optional pre-Terraform
        print(f"  optic crosscheck blocklist skipped: {exc}", file=sys.stderr)

    print("Done.")
    if run_id:
        append_run_lifecycle(
            str(run_id),
            phase="completed",
            payload={"rows_loaded": len(rows)},
        )


def main():
    parser = argparse.ArgumentParser(description="Load mappings into BigQuery sandbox")
    parser.add_argument("file", help="Path to mappings JSONL file")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to load")
    args = parser.parse_args()
    load(args.file, limit=args.limit)


if __name__ == "__main__":
    main()
