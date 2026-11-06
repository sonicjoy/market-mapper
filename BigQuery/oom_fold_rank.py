"""Release 068 G2 — fold GREG into opticodds_mapping and rank RFQ winners.

Runs BigQuery/sql/oom_fold_rank.sql on a schedule (~15 min, offset from infra
merge) and on-demand after pipeline/console writes (later slices).

Usage:
    python -m BigQuery.oom_fold_rank
    python -m mappers.control_plane.pipeline_oom_fold_rank
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from google.api_core.exceptions import Aborted, Conflict, GoogleAPICallError
from google.cloud import bigquery

from BigQuery.alerts import AlertPublisher, Severity, bool_env, build_publisher, resolve_project_id
from BigQuery.client import ro_query
from BigQuery.oom_catalog_bus import publish_rank_complete
from BigQuery.optic_crosscheck_blocks import ensure_blocklist

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).resolve().parent / "sql" / "oom_fold_rank.sql"
_SOAK_SQL_PATH = Path(__file__).resolve().parent / "sql" / "oom_fold_rank_soak.sql"
RANK_VERSION = 4  # 4: cross-check blocks ORIGINAL/passthrough, not curated rows
# Release 068 #6 soak thresholds (RFQ-eligible rows only; excludes no_rfq_ids).
DEFAULT_SOAK_UNRANKED_MAX_RATE = 0.005
DEFAULT_SOAK_RANK_LAG_MAX_MIN = 20
# Infra prices_state_merge_us runs every 15 min and can hold oom for several
# minutes; back off long enough to clear a overlapping merge transaction.
MAX_ATTEMPTS = 8
RETRY_SLEEP_SEC = 45

_CONCURRENT_MARKERS = (
    "could not serialize access",
    "concurrent update",
    "transaction is aborted",
    "aborted due to cross-transaction contention",
    "transaction was cancelled",
    "conflicting transaction",
    "aborted",
    "conflict",
)

# Same fixture window as oom_fold_rank.sql (market_mapping + fixtures require
# start_date partition elimination).
_FIXTURE_WINDOW_WHERE = """
  start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
"""


def load_fold_rank_sql(project: str) -> str:
    """Return oom_fold_rank.sql with {project} substituted."""
    return _SQL_PATH.read_text(encoding="utf-8").replace("{project}", project)


def _strip_sql_header_comments(template: str) -> str:
    """Drop leading blank/-- lines so ro_query sees WITH/SELECT first."""
    lines: list[str] = []
    for line in template.splitlines():
        if not lines and (not line.strip() or line.strip().startswith("--")):
            continue
        lines.append(line)
    return "\n".join(lines)


def load_soak_sql(project: str) -> str:
    """Return oom_fold_rank_soak.sql with project + fixture window substituted."""
    raw = _strip_sql_header_comments(_SOAK_SQL_PATH.read_text(encoding="utf-8"))
    return (
        raw.replace("{project}", project)
        .replace("{fixture_window_where}", _FIXTURE_WINDOW_WHERE.strip())
    )


def oom_fold_rank_enabled() -> bool:
    """Kill switch; default on so the CronJob can stamp winners."""
    return bool_env("MAPPING_PIPELINE_OOM_FOLD_RANK", default=True)


def oom_fold_rank_soak_enabled() -> bool:
    """Post-run soak probe; default on for release 068 #6 criteria."""
    return bool_env("MAPPING_PIPELINE_OOM_FOLD_RANK_SOAK", default=True)


def _soak_alert_hourly_only() -> bool:
    """Page non-critical soak regressions once per hour (cron :02 slot)."""
    return bool_env("OOM_FOLD_RANK_SOAK_ALERT_HOURLY_ONLY", default=True)


def _soak_unranked_max_rate() -> float:
    raw = os.getenv(
        "OOM_FOLD_RANK_SOAK_UNRANKED_MAX_RATE",
        str(DEFAULT_SOAK_UNRANKED_MAX_RATE),
    ).strip()
    return float(raw)


def _soak_rank_lag_max_min() -> int:
    raw = os.getenv(
        "OOM_FOLD_RANK_SOAK_RANK_LAG_MAX_MIN",
        str(DEFAULT_SOAK_RANK_LAG_MAX_MIN),
    ).strip()
    return int(raw)


@dataclass(frozen=True)
class SoakReport:
    """Release 068 #6 soak metrics for RFQ-eligible rows in the fixture window."""

    multi_winner_keys: int
    rfq_total: int
    rfq_unranked: int
    rank_lag_p99_min: int | None

    def issues(
        self,
        *,
        unranked_max_rate: float = DEFAULT_SOAK_UNRANKED_MAX_RATE,
        rank_lag_max_min: int = DEFAULT_SOAK_RANK_LAG_MAX_MIN,
    ) -> list[str]:
        """Return human-readable soak violations (empty when healthy)."""
        out: list[str] = []
        if self.multi_winner_keys > 0:
            out.append(f"{self.multi_winner_keys} RFQ keys have >1 winner")
        if self.rfq_total > 0:
            rate = self.rfq_unranked / self.rfq_total
            if rate > unranked_max_rate:
                out.append(
                    f"unranked RFQ-eligible {self.rfq_unranked}/{self.rfq_total} "
                    f"({rate:.2%} > {unranked_max_rate:.2%})"
                )
            ranked = self.rfq_total - self.rfq_unranked
            if ranked > 0:
                if self.rank_lag_p99_min is None:
                    out.append("rank_run_at p99 lag unavailable on ranked rows")
                elif self.rank_lag_p99_min > rank_lag_max_min:
                    out.append(
                        f"rank_run_at p99 lag {self.rank_lag_p99_min}m "
                        f"(>{rank_lag_max_min}m)"
                    )
        return out


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (Aborted, Conflict)):
        return True
    msg = str(exc).casefold()
    return any(marker in msg for marker in _CONCURRENT_MARKERS)


def permission_probe(client: bigquery.Client, project: str) -> None:
    """Fail fast when required tables are not readable."""
    ro_query(
        client,
        f"""
        select 1 as ok
        from `{project}.opticodds_us.opticodds_mapping`
        limit 1
        """,  # nosec B608 — project is GCP_PROJECT env, not user input
    )
    ro_query(
        client,
        f"""
        select 1 as ok
        from `{project}.markets_us.market_mapping`
        where {_FIXTURE_WINDOW_WHERE}
        limit 1
        """,  # nosec B608 — project is GCP_PROJECT env, not user input
    )
    ro_query(
        client,
        f"""
        select 1 as ok
        from `{project}.opticodds_us.opticodds_fixtures`
        where {_FIXTURE_WINDOW_WHERE}
        limit 1
        """,  # nosec B608 — project is GCP_PROJECT env, not user input
    )


def run_fold_rank(
    client: bigquery.Client,
    project: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    retry_sleep_sec: int = RETRY_SLEEP_SEC,
) -> None:
    """Execute the fold+rank script with retry on concurrent-update failures."""
    ensure_blocklist(client)
    sql = load_fold_rank_sql(project)
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "oom fold+rank starting project=%s rank_version=%d attempt=%d/%d",
                project,
                RANK_VERSION,
                attempt,
                max_attempts,
            )
            job = client.query(sql)
            job.result()
            if job.errors:
                raise RuntimeError(f"oom fold+rank failed: {job.errors}")
            logger.info("oom fold+rank completed project=%s", project)
            return
        except GoogleAPICallError as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable(exc):
                raise
            logger.warning(
                "oom fold+rank concurrent update attempt=%d/%d: %s",
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(retry_sleep_sec)
    if last_exc is not None:
        raise last_exc


def soak_probe(client: bigquery.Client, project: str) -> SoakReport:
    """Measure release 068 #6 soak metrics after a successful fold+rank."""
    row = next(iter(ro_query(client, load_soak_sql(project))))
    return SoakReport(
        multi_winner_keys=int(row.multi_winner_keys),
        rfq_total=int(row.rfq_total),
        rfq_unranked=int(row.rfq_unranked),
        rank_lag_p99_min=(
            int(row.rank_lag_p99_min) if row.rank_lag_p99_min is not None else None
        ),
    )


def _publish_alert(
    publisher: AlertPublisher | None,
    severity: Severity,
    text: str,
) -> None:
    """Best-effort Pub/Sub alert; swallow publisher errors."""
    if publisher is None:
        return
    try:
        publisher.publish(severity, text)
    except Exception:
        logger.exception("oom fold+rank alert publish failed")


def _failure_alert_text(project: str, exc: BaseException) -> str:
    return (
        f"oom fold+rank FAILED ({project})\n"
        f"{type(exc).__name__}: {exc}\n"
        "Triage: kubectl -n mapping-console get jobs -l app=oom-fold-rank "
        "--sort-by=.status.startTime | tail\n"
        "kubectl -n mapping-console logs job/<latest-oom-fold-rank-job> --tail=40"
    )


def _soak_alert_text(project: str, report: SoakReport, issues: list[str]) -> str:
    lines = [
        f"oom fold+rank soak check FAILED ({project})",
        *[f"- {issue}" for issue in issues],
        (
            f"metrics: multi_winner_keys={report.multi_winner_keys} "
            f"rfq_total={report.rfq_total} rfq_unranked={report.rfq_unranked} "
            f"rank_lag_p99_min={report.rank_lag_p99_min}"
        ),
        "Release 068 #6 soak criteria",
    ]
    return "\n".join(lines)


def _soak_probe_error_text(project: str, exc: BaseException) -> str:
    return (
        f"oom fold+rank soak probe ERROR ({project}) — fold+rank already succeeded\n"
        f"{type(exc).__name__}: {exc}\n"
        "Triage: kubectl -n mapping-console logs job/<latest-oom-fold-rank-job> --tail=40"
    )


def _should_publish_soak_alert(report: SoakReport) -> bool:
    """Multi-winner always pages; other soak regressions at most once per hour."""
    if report.multi_winner_keys > 0:
        return True
    if not _soak_alert_hourly_only():
        return True
    return datetime.now(UTC).minute == 2


def _run_soak_check(
    client: bigquery.Client,
    project: str,
    publisher: AlertPublisher,
) -> None:
    """Post-run soak metrics; failures do not fail the CronJob."""
    if not oom_fold_rank_soak_enabled():
        return
    try:
        report = soak_probe(client, project)
        issues = report.issues(
            unranked_max_rate=_soak_unranked_max_rate(),
            rank_lag_max_min=_soak_rank_lag_max_min(),
        )
        if not issues:
            return
        logger.warning(
            "oom fold+rank soak unhealthy project=%s issues=%s",
            project,
            issues,
        )
        if _should_publish_soak_alert(report):
            _publish_alert(
                publisher,
                "warning",
                _soak_alert_text(project, report, issues),
            )
        else:
            logger.info(
                "oom fold+rank soak alert suppressed (hourly gate) project=%s",
                project,
            )
    except Exception as exc:
        logger.exception(
            "oom fold+rank soak probe failed after successful fold+rank project=%s",
            project,
        )
        _publish_alert(
            publisher,
            "warning",
            _soak_probe_error_text(project, exc),
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not oom_fold_rank_enabled():
        logger.info("oom fold+rank disabled (MAPPING_PIPELINE_OOM_FOLD_RANK)")
        return 0
    publisher = build_publisher()
    project = ""
    try:
        project = resolve_project_id() or ""
        if not project:
            raise RuntimeError("GCP_PROJECT or PROJECT_ID must be set")
        client = bigquery.Client(project=project)
        permission_probe(client, project)
        run_fold_rank(client, project)
        publish_rank_complete(client, project, rank_version=RANK_VERSION)
        _run_soak_check(client, project, publisher)
        return 0
    except Exception as exc:
        label = project or resolve_project_id() or "unknown"
        logger.exception("oom fold+rank failed project=%s", label)
        _publish_alert(publisher, "warning", _failure_alert_text(label, exc))
        return 1
    finally:
        publisher.close()


if __name__ == "__main__":
    sys.exit(main())
