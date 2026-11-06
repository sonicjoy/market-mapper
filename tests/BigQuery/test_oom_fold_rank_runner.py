"""Unit tests for oom_fold_rank runner helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import Aborted, BadRequest, Conflict

from BigQuery.oom_fold_rank import (
    MAX_ATTEMPTS,
    RETRY_SLEEP_SEC,
    SoakReport,
    _is_retryable,
    _run_soak_check,
    _should_publish_soak_alert,
    main,
    oom_fold_rank_enabled,
    oom_fold_rank_soak_enabled,
    permission_probe,
    run_fold_rank,
    soak_probe,
)


def test_oom_fold_rank_enabled_default_on() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert oom_fold_rank_enabled() is True


def test_oom_fold_rank_enabled_respects_kill_switch() -> None:
    with patch.dict(os.environ, {"MAPPING_PIPELINE_OOM_FOLD_RANK": "0"}, clear=True):
        assert oom_fold_rank_enabled() is False


def test_is_retryable_matches_concurrent_update() -> None:
    exc = BadRequest("Could not serialize access to table due to concurrent update")
    assert _is_retryable(exc) is True


def test_is_retryable_matches_aborted_and_conflict() -> None:
    assert _is_retryable(Aborted("transaction was cancelled")) is True
    assert _is_retryable(Conflict("conflicting transaction")) is True


def test_permission_probe_queries_all_required_tables() -> None:
    client = MagicMock()
    with patch("BigQuery.oom_fold_rank.ro_query") as ro_query:
        permission_probe(client, "marketmaking-test")
    assert ro_query.call_count == 3
    joined = " ".join(call.args[1] for call in ro_query.call_args_list)
    assert "opticodds_mapping" in joined
    assert "market_mapping" in joined
    assert "opticodds_fixtures" in joined
    assert joined.count("start_date >=") >= 2


def test_run_fold_rank_retries_then_succeeds() -> None:
    client = MagicMock()
    failing = Conflict("conflicting transaction")
    ok_job = MagicMock(errors=None)
    client.query.side_effect = [failing, ok_job]
    with (
        patch("BigQuery.oom_fold_rank.time.sleep"),
        patch("BigQuery.oom_fold_rank.ensure_blocklist"),
    ):
        run_fold_rank(client, "marketmaking-test", max_attempts=2, retry_sleep_sec=1)
    assert client.query.call_count == 2


def test_run_fold_rank_default_retry_budget_covers_infra_merge() -> None:
    assert MAX_ATTEMPTS >= 8
    assert RETRY_SLEEP_SEC >= 30


def test_main_disabled_returns_zero() -> None:
    with patch.dict(os.environ, {"MAPPING_PIPELINE_OOM_FOLD_RANK": "false"}, clear=True):
        assert main() == 0


def test_main_requires_project_alerts_and_returns_one() -> None:
    with (
        patch.dict(os.environ, {"MAPPING_PIPELINE_OOM_FOLD_RANK": "1"}, clear=True),
        patch("BigQuery.oom_fold_rank.build_publisher") as build_publisher,
    ):
        publisher = MagicMock()
        build_publisher.return_value = publisher
        assert main() == 1
    publisher.publish.assert_called_once()
    assert "GCP_PROJECT" in publisher.publish.call_args.args[1]
    publisher.close.assert_called_once()


def test_oom_fold_rank_soak_enabled_default_on() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert oom_fold_rank_soak_enabled() is True


def test_soak_report_flags_multi_winner_and_unranked() -> None:
    report = SoakReport(
        multi_winner_keys=2,
        rfq_total=1000,
        rfq_unranked=10,
        rank_lag_p99_min=25,
    )
    issues = report.issues(unranked_max_rate=0.005, rank_lag_max_min=20)
    assert any(">1 winner" in issue for issue in issues)
    assert any("unranked RFQ-eligible" in issue for issue in issues)
    assert any("rank_run_at p99 lag" in issue for issue in issues)


def test_soak_report_healthy_when_within_thresholds() -> None:
    report = SoakReport(
        multi_winner_keys=0,
        rfq_total=1000,
        rfq_unranked=4,
        rank_lag_p99_min=5,
    )
    assert report.issues(unranked_max_rate=0.005, rank_lag_max_min=20) == []


def test_soak_report_skips_p99_when_all_rows_unranked() -> None:
    report = SoakReport(
        multi_winner_keys=0,
        rfq_total=100,
        rfq_unranked=100,
        rank_lag_p99_min=None,
    )
    issues = report.issues(unranked_max_rate=0.005, rank_lag_max_min=20)
    assert any("unranked RFQ-eligible" in issue for issue in issues)
    assert not any("p99 lag" in issue for issue in issues)


def test_soak_probe_queries_fixture_window() -> None:
    client = MagicMock()
    row = MagicMock(
        multi_winner_keys=0,
        rfq_total=10,
        rfq_unranked=0,
        rank_lag_p99_min=1,
    )
    with patch("BigQuery.oom_fold_rank.ro_query", return_value=iter([row])) as ro_query:
        report = soak_probe(client, "marketmaking-test")
    assert report.rfq_total == 10
    sql = ro_query.call_args.args[1]
    assert "start_date >=" in sql
    assert "multi_winner_keys" in sql
    assert "rank_lag_p99_min" in sql
    assert "from `{project}.opticodds_us.opticodds_mapping`".replace(
        "{project}", "marketmaking-test"
    ) in sql
    assert "select\n    lower(sportsbook)" in sql
    assert "{project}" not in sql


def test_main_publishes_failure_alert() -> None:
    with (
        patch.dict(
            os.environ,
            {
                "MAPPING_PIPELINE_OOM_FOLD_RANK": "1",
                "GCP_PROJECT": "marketmaking-test",
                "ALERT_PUBSUB_ENABLED": "true",
            },
            clear=True,
        ),
        patch("BigQuery.oom_fold_rank.bigquery.Client"),
        patch("BigQuery.oom_fold_rank.permission_probe", side_effect=RuntimeError("probe boom")),
        patch("BigQuery.oom_fold_rank.build_publisher") as build_publisher,
    ):
        publisher = MagicMock()
        build_publisher.return_value = publisher
        assert main() == 1
    publisher.publish.assert_called_once()
    text = publisher.publish.call_args.args[1]
    assert "oom fold+rank FAILED" in text
    assert "probe boom" in text
    publisher.close.assert_called_once()


def test_main_publishes_soak_alert_when_unhealthy() -> None:
    with (
        patch.dict(
            os.environ,
            {
                "MAPPING_PIPELINE_OOM_FOLD_RANK": "1",
                "GCP_PROJECT": "marketmaking-test",
                "ALERT_PUBSUB_ENABLED": "true",
            },
            clear=True,
        ),
        patch("BigQuery.oom_fold_rank.bigquery.Client"),
        patch("BigQuery.oom_fold_rank.permission_probe"),
        patch("BigQuery.oom_fold_rank.run_fold_rank"),
        patch("BigQuery.oom_fold_rank.publish_rank_complete"),
        patch(
            "BigQuery.oom_fold_rank.soak_probe",
            return_value=SoakReport(
                multi_winner_keys=1,
                rfq_total=100,
                rfq_unranked=0,
                rank_lag_p99_min=1,
            ),
        ),
        patch("BigQuery.oom_fold_rank.build_publisher") as build_publisher,
    ):
        publisher = MagicMock()
        build_publisher.return_value = publisher
        assert main() == 0
    publisher.publish.assert_called_once()
    text = publisher.publish.call_args.args[1]
    assert "soak check FAILED" in text
    assert ">1 winner" in text


def test_should_publish_soak_alert_multi_winner_always() -> None:
    report = SoakReport(
        multi_winner_keys=1,
        rfq_total=10,
        rfq_unranked=0,
        rank_lag_p99_min=1,
    )
    with patch("BigQuery.oom_fold_rank.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(minute=17)
        assert _should_publish_soak_alert(report) is True


def test_should_publish_soak_alert_hourly_gate() -> None:
    report = SoakReport(
        multi_winner_keys=0,
        rfq_total=100,
        rfq_unranked=10,
        rank_lag_p99_min=1,
    )
    with (
        patch.dict(os.environ, {"OOM_FOLD_RANK_SOAK_ALERT_HOURLY_ONLY": "1"}, clear=True),
        patch("BigQuery.oom_fold_rank.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = MagicMock(minute=17)
        assert _should_publish_soak_alert(report) is False
        mock_dt.now.return_value = MagicMock(minute=2)
        assert _should_publish_soak_alert(report) is True


def test_run_soak_check_probe_error_does_not_raise() -> None:
    publisher = MagicMock()
    client = MagicMock()
    with patch(
        "BigQuery.oom_fold_rank.soak_probe",
        side_effect=RuntimeError("soak boom"),
    ):
        _run_soak_check(client, "marketmaking-test", publisher)
    publisher.publish.assert_called_once()
    assert "soak probe ERROR" in publisher.publish.call_args.args[1]


def test_main_soak_probe_error_returns_zero() -> None:
    with (
        patch.dict(
            os.environ,
            {
                "MAPPING_PIPELINE_OOM_FOLD_RANK": "1",
                "GCP_PROJECT": "marketmaking-test",
                "ALERT_PUBSUB_ENABLED": "true",
            },
            clear=True,
        ),
        patch("BigQuery.oom_fold_rank.bigquery.Client"),
        patch("BigQuery.oom_fold_rank.permission_probe"),
        patch("BigQuery.oom_fold_rank.run_fold_rank"),
        patch("BigQuery.oom_fold_rank.publish_rank_complete"),
        patch("BigQuery.oom_fold_rank.soak_probe", side_effect=RuntimeError("soak boom")),
        patch("BigQuery.oom_fold_rank.build_publisher") as build_publisher,
    ):
        publisher = MagicMock()
        build_publisher.return_value = publisher
        assert main() == 0
    assert "soak probe ERROR" in publisher.publish.call_args.args[1]
