"""Integration tests for the stage → MERGE load flow.

Runs against the real markets_us tables. Verifies that MERGE correctly
handles inserts, idempotent reloads, updates to non-key values,
preservation of untouched rows, and reschedule cleanup.

Usage:
    .venv/bin/python -m BigQuery.destructive_test_merge
"""

import io
import json
import sys
from datetime import UTC, date, datetime, timedelta

from google.cloud import bigquery

from BigQuery.client import ro_client, sandbox_query
from BigQuery.load_mappings import (
    KEY_COLUMNS,
    STAGE_TABLE,
    TABLE,
    _build_merge_sql,
    _clean_reschedules,
    flatten_rows,
)

# Test data — two slices of different sizes from the same file.
# LIMIT_A < LIMIT_B so that B contains new keys not in A.
FILE = "data/2026-03-19/13_01/mappings.jsonl"
LIMIT_A = 10
LIMIT_B = 20


def _read_rows(path, limit):
    """Read and flatten mapping rows from a JSONL file."""
    now_ts = datetime.now(UTC).isoformat()
    rows = []
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("optic_odds") is None:
                continue
            for row in flatten_rows(rec, now_ts):
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def _stage_rows(client, schema, rows):
    """Bulk-load rows into the staging table (WRITE_TRUNCATE)."""
    buf = io.BytesIO()
    for row in rows:
        buf.write(json.dumps(row).encode("utf-8"))
        buf.write(b"\n")
    buf.seek(0)

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_file(buf, STAGE_TABLE, job_config=job_config)
    job.result()
    if job.errors:
        raise RuntimeError(f"Stage load errors: {job.errors}")


def _merge(client):
    """Run the MERGE from stage into main table."""
    stage_dates = sorted(
        row.d.isoformat()
        for row in client.query(
            f"SELECT DISTINCT DATE(start_date) AS d FROM {STAGE_TABLE}"
        ).result()
    )
    date_in = ", ".join(f"'{d}'" for d in stage_dates)
    sandbox_query(client, _build_merge_sql(date_in))


def _count(client, table):
    """Return the row count of a table.

    The main table has a required partition filter; use a broad range
    that covers all realistic dates.
    """
    where = "WHERE DATE(start_date) >= '2000-01-01'" if table == TABLE else ""
    result = client.query(f"SELECT COUNT(*) AS n FROM {table} {where}").result()
    return next(iter(result)).n


def _duplicate_key_count(client):
    """Return the number of duplicate-key groups in market_mapping."""
    key_cols = ", ".join(KEY_COLUMNS)
    sql = f"""
        SELECT COUNT(*) AS n FROM (
            SELECT {key_cols}, COUNT(*) AS c
            FROM {TABLE}
            WHERE DATE(start_date) >= '2000-01-01'
            GROUP BY {key_cols}
            HAVING c > 1
        )
    """
    result = client.query(sql).result()
    return next(iter(result)).n


def _truncate(client):
    """Delete all rows from both tables."""
    sandbox_query(client, f"DELETE FROM {TABLE} WHERE DATE(start_date) >= '2000-01-01'")
    sandbox_query(client, f"DELETE FROM {STAGE_TABLE} WHERE TRUE")


def _assert(condition, msg):
    if not condition:
        print(f"  FAIL: {msg}")
        sys.exit(1)
    print(f"  PASS: {msg}")


def run():
    client = ro_client()

    if client.project == "rs-marketmaking":
        sys.exit(
            "FATAL: refusing to run destructive tests against production "
            "(rs-marketmaking). Set GCP_PROJECT=marketmaking-test in .env."
        )

    schema = client.get_table(STAGE_TABLE).schema

    # -- Step 1: Clean slate --
    print("Step 1: Clean slate")
    _truncate(client)
    _assert(_count(client, TABLE) == 0, "market_mapping is empty")
    _assert(_count(client, STAGE_TABLE) == 0, "stage is empty")

    # -- Step 2: Initial load --
    print("Step 2: Initial load from file A")
    rows_a = _read_rows(FILE, LIMIT_A)
    _stage_rows(client, schema, rows_a)
    _merge(client)
    count_after_initial = _count(client, TABLE)
    _assert(count_after_initial == len(rows_a),
            f"row count = {count_after_initial} (expected {len(rows_a)})")
    _assert(_duplicate_key_count(client) == 0, "no duplicate keys")

    # -- Step 3: Idempotent reload --
    print("Step 3: Idempotent reload (same data)")
    _stage_rows(client, schema, rows_a)
    _merge(client)
    count_after_reload = _count(client, TABLE)
    _assert(count_after_reload == count_after_initial,
            f"row count unchanged = {count_after_reload}")
    _assert(_duplicate_key_count(client) == 0, "no duplicate keys")

    # -- Step 4: Update non-key values --
    print("Step 4: Update non-key values via stage")
    # Modify fixture_id on a staged row, then MERGE. The target row
    # should be updated (same key, new value).
    modified_rows = [dict(r) for r in rows_a]
    original_fixture_id = modified_rows[0]["fixture_id"]
    modified_rows[0]["fixture_id"] = "TEST_UPDATED_FIXTURE"
    _stage_rows(client, schema, modified_rows)
    _merge(client)
    count_after_update = _count(client, TABLE)
    _assert(count_after_update == count_after_initial,
            f"row count unchanged = {count_after_update}")

    # Verify the updated value is in the target.
    # Build a WHERE clause from the first row's key to find it.
    row0 = modified_rows[0]
    where_parts = []
    for col in KEY_COLUMNS:
        val = row0.get(col)
        if val is None:
            where_parts.append(f"{col} IS NULL")
        elif isinstance(val, (int, float)):
            where_parts.append(f"{col} = {val}")
        else:
            escaped = str(val).replace("'", "\\'")
            where_parts.append(f"{col} = '{escaped}'")

    check_sql = f"SELECT fixture_id FROM {TABLE} WHERE {' AND '.join(where_parts)}"
    result = client.query(check_sql).result()
    found_fixture = next(iter(result)).fixture_id
    _assert(found_fixture == "TEST_UPDATED_FIXTURE",
            f"fixture_id updated to {found_fixture}")

    # Restore original value for subsequent tests.
    modified_rows[0]["fixture_id"] = original_fixture_id
    _stage_rows(client, schema, modified_rows)
    _merge(client)

    # -- Step 5: New rows (larger slice of same file) --
    print("Step 5: Load new rows (larger slice)")
    rows_b = _read_rows(FILE, LIMIT_B)

    # Count how many keys in B are genuinely new (not in A).
    def _row_key(r):
        return tuple(r.get(c) for c in KEY_COLUMNS)
    keys_a = {_row_key(r) for r in rows_a}
    keys_b = {_row_key(r) for r in rows_b}
    new_keys = keys_b - keys_a
    overlap_keys = keys_b & keys_a

    _stage_rows(client, schema, rows_b)
    _merge(client)
    count_after_new = _count(client, TABLE)
    expected = count_after_initial + len(new_keys)
    _assert(count_after_new == expected,
            f"row count = {count_after_new} (expected {expected}: "
            f"{count_after_initial} original + {len(new_keys)} new, "
            f"{len(overlap_keys)} overlapping)")
    _assert(_duplicate_key_count(client) == 0, "no duplicate keys")

    # -- Step 6: Untouched rows preserved --
    print("Step 6: Untouched rows preserved")
    # Rows from A that were NOT in B's batch should still be in the target.
    preserved_keys = keys_a - keys_b
    if preserved_keys:
        # Check one of them exists.
        sample_key = next(iter(preserved_keys))
        sample_row = next(r for r in rows_a if _row_key(r) == sample_key)
        where_parts = []
        for col in KEY_COLUMNS:
            val = sample_row.get(col)
            if val is None:
                where_parts.append(f"{col} IS NULL")
            elif isinstance(val, (int, float)):
                where_parts.append(f"{col} = {val}")
            else:
                escaped = str(val).replace("'", "\\'")
                where_parts.append(f"{col} = '{escaped}'")
        check_sql = f"SELECT COUNT(*) AS n FROM {TABLE} WHERE {' AND '.join(where_parts)}"
        result = client.query(check_sql).result()
        n = next(iter(result)).n
        _assert(n == 1, f"preserved row found ({len(preserved_keys)} keys only in A)")
    else:
        print("  SKIP: all A keys overlap with B (no preserved-only rows to check)")

    # -- Step 7: Final duplicate key check --
    print("Step 7: Final duplicate key check")
    _assert(_duplicate_key_count(client) == 0, "no duplicate keys")

    # -- Step 8: Reschedule detection --
    print("Step 8: Reschedule detection")
    # Simulate a game rescheduled to a different date.  _clean_reschedules
    # should detect the stale old-date rows and delete them, so the MERGE
    # doesn't create duplicates keyed by different start_dates.

    # Start clean with rows_a in the main table.
    _truncate(client)
    _stage_rows(client, schema, rows_a)
    _merge(client)
    count_baseline = _count(client, TABLE)

    # Pick a game and shift its start_date forward by 1 day.
    target_game = rows_a[0]["game_id"]
    original_ts = rows_a[0]["start_date"]
    dt = datetime.fromisoformat(original_ts)
    shifted_ts = (dt + timedelta(days=1)).isoformat()

    rescheduled = []
    shifted_count = 0
    for r in rows_a:
        r = dict(r)
        if r["game_id"] == target_game:
            r["start_date"] = shifted_ts
            shifted_count += 1
        rescheduled.append(r)
    print(f"  Shifted {shifted_count} rows for {target_game}: "
          f"{original_ts} → {shifted_ts}")

    # Stage the rescheduled batch and run reschedule cleanup.
    _stage_rows(client, schema, rescheduled)
    stage_dates = sorted({r["start_date"][:10] for r in rescheduled})
    cutoff = (date.fromisoformat(stage_dates[0]) - timedelta(days=60)).isoformat()
    _clean_reschedules(client, cutoff)

    # Old-date rows should be gone.
    old_date = original_ts[:10]
    old_sql = (
        f"SELECT COUNT(*) AS n FROM {TABLE} "
        f"WHERE DATE(start_date) = '{old_date}' "
        f"AND game_id = '{target_game}'"
    )
    old_n = next(iter(client.query(old_sql).result())).n
    _assert(old_n == 0,
            f"stale rows deleted for {target_game} at {old_date}")

    # Merge, then verify new-date rows present and no duplicates.
    _merge(client)
    new_date = shifted_ts[:10]
    new_sql = (
        f"SELECT COUNT(*) AS n FROM {TABLE} "
        f"WHERE DATE(start_date) = '{new_date}' "
        f"AND game_id = '{target_game}'"
    )
    new_n = next(iter(client.query(new_sql).result())).n
    _assert(new_n == shifted_count,
            f"{new_n} rows at new date {new_date} (expected {shifted_count})")

    count_after = _count(client, TABLE)
    _assert(count_after == count_baseline,
            f"total rows unchanged ({count_after})")
    _assert(_duplicate_key_count(client) == 0,
            "no duplicate keys after reschedule")

    # -- Step 9: Clean up --
    print("Step 9: Clean up")
    _truncate(client)
    _assert(_count(client, TABLE) == 0, "market_mapping is empty")

    print("\nAll tests passed.")


if __name__ == "__main__":
    run()
