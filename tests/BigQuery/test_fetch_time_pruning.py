"""The *_fetch_raw point-reads must carry a fetch_time partition predicate.

`WHERE snapshot_id = @snapshot_id` alone prunes nothing: the tables are
append-only, so a bare point-read scans every daily partition.  Measured
on rs-marketmaking 2026-09-08, these reads billed 44.5 TiB/24h.  The fix
is a fetch_time band of ± one mapper tick around the snapshot's own
instant, which excludes nothing today and prunes DATE(fetch_time) to one
partition (two if the tick sits on UTC midnight).

These tests assert against the REAL google.cloud.bigquery parameter and
job-config classes, not stand-ins: a double that accepted any parameter
name or type would let a broken binding ship green.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery.exchange_fetch_snapshot import (
    FETCH_TIME_SLACK,
    fetch_time_from_dir,
    fetch_time_from_snapshot_id,
    fetch_time_window,
    snapshot_id_from_dir,
)
from BigQuery.exchange_fetch_tables import LOAD_SCHEMAS, TABLES
from BigQuery.reconcile_fetch_snapshot import _bq_lines
from mappers.snapshot_index import _HYDRATE_SQL, SnapshotIndex

_PARAM_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")

_SNAPSHOT_ID = "2026-08-19T10:35"
_FETCH_TIME = datetime(2026, 8, 19, 10, 35, tzinfo=UTC)


def _scalar_params(
    job_config: bigquery.QueryJobConfig,
) -> dict[str, bigquery.ScalarQueryParameter]:
    """Bound parameters by name, asserting each is a real scalar parameter."""
    by_name: dict[str, bigquery.ScalarQueryParameter] = {}
    for param in job_config.query_parameters:
        assert isinstance(param, bigquery.ScalarQueryParameter), param
        assert param.name is not None
        by_name[param.name] = param
    return by_name


def _assert_binding_is_complete(sql: str, job_config: bigquery.QueryJobConfig) -> None:
    """Every @name in the SQL is bound, and nothing is bound that isn't used."""
    assert _PARAM_RE.findall(sql), f"no query parameters in {sql!r}"
    assert set(_PARAM_RE.findall(sql)) == set(_scalar_params(job_config))


def _assert_band_brackets_snapshot(job_config: bigquery.QueryJobConfig) -> None:
    by_name = _scalar_params(job_config)
    assert by_name["snapshot_id"].type_ == "STRING"
    assert by_name["snapshot_id"].value == _SNAPSHOT_ID
    assert by_name["fetch_time_lo"].type_ == "TIMESTAMP"
    assert by_name["fetch_time_hi"].type_ == "TIMESTAMP"
    lo = by_name["fetch_time_lo"].value
    hi = by_name["fetch_time_hi"].value
    assert isinstance(lo, datetime)
    assert isinstance(hi, datetime)
    assert lo <= _FETCH_TIME <= hi


# --- the window itself --------------------------------------------------


def test_fetch_time_from_snapshot_id_round_trips_the_dir():
    data_dir = Path("data/2026-08-19/10_35")
    assert snapshot_id_from_dir(data_dir) == _SNAPSHOT_ID
    assert fetch_time_from_snapshot_id(_SNAPSHOT_ID) == fetch_time_from_dir(data_dir)
    assert fetch_time_from_dir(data_dir) == _FETCH_TIME


def test_fetch_time_window_is_symmetric_and_inclusive():
    lo, hi = fetch_time_window(_FETCH_TIME)
    assert lo == _FETCH_TIME - FETCH_TIME_SLACK
    assert hi == _FETCH_TIME + FETCH_TIME_SLACK
    assert lo <= _FETCH_TIME <= hi


def test_fetch_time_window_is_anchored_not_relative():
    """Correct against months of history: the band follows the snapshot.

    There is no partition expiry on these tables, so a "last N days" style
    predicate would silently stop finding old snapshots.  A year-old
    snapshot must still resolve to a band around itself.
    """
    old = _FETCH_TIME - timedelta(days=400)
    lo, hi = fetch_time_window(old)
    assert lo <= old <= hi
    assert hi < _FETCH_TIME - timedelta(days=398)


def test_fetch_time_slack_is_one_mapper_tick():
    """±15 min: one partition, two if the tick sits on UTC midnight."""
    assert timedelta(minutes=15) == FETCH_TIME_SLACK
    lo, hi = fetch_time_window(_FETCH_TIME)
    assert hi - lo == timedelta(minutes=30)


def test_every_fetch_raw_table_has_the_fetch_time_column():
    """The predicate is only valid because every loaded schema writes it."""
    for key, table in TABLES.items():
        names = {field.name for field in LOAD_SCHEMAS[key]}
        assert "fetch_time" in names, table
        assert "snapshot_id" in names, table


# --- SnapshotIndex.hydrate ----------------------------------------------


def test_every_hydrate_query_filters_on_fetch_time_and_snapshot():
    for key, template in _HYDRATE_SQL.items():
        sql = template.format(table=TABLES[key])
        assert "fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi" in sql, key
        assert "snapshot_id = @snapshot_id" in sql, key


def test_hydrate_poly_usa_missing_table_keeps_other_sources():
    client = MagicMock()
    poly_usa_table = TABLES["polymarket_usa"]

    def _query(sql, job_config=None):
        job = MagicMock()
        job.result.return_value = []
        if poly_usa_table in sql:
            job.result.side_effect = NotFound("not found: table polymarket_usa_fetch_raw")
        return job

    client.query.side_effect = _query
    with patch("mappers.snapshot_index.bigquery.Client", return_value=client):
        idx = SnapshotIndex.hydrate(_SNAPSHOT_ID, "marketmaking-test")
    assert idx.polymarket_usa_markets == []
    assert client.query.call_count == len(_HYDRATE_SQL)


def test_hydrate_binds_the_band_on_every_source():
    client = MagicMock()
    client.query.return_value.result.return_value = []
    with patch("mappers.snapshot_index.bigquery.Client", return_value=client):
        SnapshotIndex.hydrate(_SNAPSHOT_ID, "marketmaking-test")

    assert client.query.call_count == len(_HYDRATE_SQL)
    for call in client.query.call_args_list:
        sql = call.args[0]
        job_config = call.kwargs["job_config"]
        assert isinstance(job_config, bigquery.QueryJobConfig)
        _assert_binding_is_complete(sql, job_config)
        _assert_band_brackets_snapshot(job_config)


# --- reconcile_fetch_snapshot -------------------------------------------


def test_reconcile_read_binds_the_band():
    client = MagicMock()
    client.query.return_value.result.return_value = []
    window = fetch_time_window(_FETCH_TIME)

    assert _bq_lines(client, "novig", _SNAPSHOT_ID, window) == []

    sql = client.query.call_args.args[0]
    job_config = client.query.call_args.kwargs["job_config"]
    assert "fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi" in sql
    assert f"`{TABLES['novig']}`" in sql
    _assert_binding_is_complete(sql, job_config)
    _assert_band_brackets_snapshot(job_config)
