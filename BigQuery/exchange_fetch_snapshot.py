"""Snapshot id and fetch_time from a pipeline data directory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

# Slack either side of a snapshot's own fetch_time when reading its rows back.
#
# BigQuery.load_exchange_fetch writes fetch_time = fetch_time_iso(data_dir),
# i.e. exactly the instant encoded in snapshot_id.  Verified against prod on
# 2026-09-08: 0 rows out of 256M across all seven raw_ingestion_us.*_fetch_raw
# tables have a fetch_time that disagrees with their snapshot_id, and none is
# null.  Equality would therefore work today.  One mapper tick of slack
# survives a loader that ever rounds or re-times a row by less than the
# pipeline cadence, and still prunes DATE(fetch_time) to one daily partition
# (two if the tick sits on UTC midnight).
#
# Anchored on the snapshot, never on "now", so a year-old snapshot still
# resolves.  Do not widen this: ±1 day was three partitions for no extra
# correctness the snapshot_id predicate does not already provide.
FETCH_TIME_SLACK = timedelta(minutes=15)


def snapshot_id_from_dir(data_dir: Path) -> str:
    """``data/2026-08-19/10_35`` → ``2026-08-19T10_35``."""
    date_part = data_dir.parent.name
    time_part = data_dir.name.replace("_", ":")
    return f"{date_part}T{time_part}"


def fetch_time_from_dir(data_dir: Path) -> datetime:
    """UTC instant encoded in the directory path."""
    date_part = data_dir.parent.name
    hh, mm = data_dir.name.split("_", 1)
    return datetime.strptime(
        f"{date_part}T{hh}:{mm}:00", "%Y-%m-%dT%H:%M:%S",
    ).replace(tzinfo=UTC)


def fetch_time_iso(data_dir: Path) -> str:
    return fetch_time_from_dir(data_dir).isoformat()


def fetch_time_from_snapshot_id(snapshot_id: str) -> datetime:
    """``2026-08-19T10:35`` → the UTC instant it names."""
    date_part, time_part = snapshot_id.split("T", 1)
    hh, mm = time_part.split(":", 1)
    return datetime.strptime(
        f"{date_part}T{hh}:{mm}:00", "%Y-%m-%dT%H:%M:%S",
    ).replace(tzinfo=UTC)


def fetch_time_window(fetch_time: datetime) -> tuple[datetime, datetime]:
    """Inclusive [lo, hi] fetch_time band to read one snapshot's rows.

    Pair every ``snapshot_id = @snapshot_id`` point-read with this band:
    on its own, snapshot_id prunes nothing, so the read costs a full table
    scan and grows without bound as history accumulates.
    """
    return fetch_time - FETCH_TIME_SLACK, fetch_time + FETCH_TIME_SLACK
