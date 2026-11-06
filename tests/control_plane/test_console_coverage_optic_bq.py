"""Tests for Coverage Optic BigQuery helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mappers.control_plane.console_coverage_optic_bq import (
    _LIST_SQL,
    _ONE_SQL,
    query_one_optic_coverage_fixture,
)


def test_list_sql_filters_phase_and_sorts_by_start() -> None:
    assert "@phase" in _LIST_SQL
    assert "lower(status) = 'live'" in _LIST_SQL
    assert "lower(status) in ('unplayed', 'delayed')" in _LIST_SQL
    assert "start_date < current_timestamp()" in _LIST_SQL
    assert "start_date >= current_timestamp()" in _LIST_SQL
    assert "status is null" in _LIST_SQL
    assert "order by start_date" in _LIST_SQL
    assert "coalesce(nullif(id, ''), game_id)" in _LIST_SQL
    assert "limit @limit offset @offset" in _LIST_SQL


def test_one_fixture_sql_requires_start_date_partition() -> None:
    assert "start_date > timestamp_sub" in _ONE_SQL
    assert "@back_hours" in _ONE_SQL
    assert "@fwd_hours" in _ONE_SQL
    assert "lower(status) not in ('completed', 'cancelled', 'canceled')" in _ONE_SQL


@patch("mappers.control_plane.console_coverage_optic_bq.bigquery.Client")
@patch("mappers.control_plane.console_coverage_optic_bq.ro_query")
def test_query_list_passes_phase(ro_query: MagicMock, client_cls: MagicMock) -> None:
    from mappers.control_plane.console_coverage_optic_bq import query_optic_coverage_fixtures

    client_cls.return_value = MagicMock()
    ro_query.return_value = iter([])

    query_optic_coverage_fixtures(
        optic_ids=["atp"],
        q=None,
        limit=10,
        offset=0,
        fwd_hours=96,
        phase="pre",
    )

    job_config = ro_query.call_args.kwargs["job_config"]
    phase = next(p for p in job_config.query_parameters if p.name == "phase")
    assert phase.value == "pre"


@patch("mappers.control_plane.console_coverage_optic_bq.bigquery.Client")
@patch("mappers.control_plane.console_coverage_optic_bq.ro_query")
def test_query_one_passes_partition_window(ro_query: MagicMock, client_cls: MagicMock) -> None:
    client_cls.return_value = MagicMock()
    ro_query.return_value = iter([])

    query_one_optic_coverage_fixture("fx-1", fwd_hours=120, back_hours=48)

    job_config = ro_query.call_args.kwargs["job_config"]
    params = {p.name: p.value for p in job_config.query_parameters}
    assert params["fid"] == "fx-1"
    assert params["fwd_hours"] == 120
    assert params["back_hours"] == 48
