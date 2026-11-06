"""In-process async jobs for console mapping_override publish (G5)."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from google.cloud import bigquery

from BigQuery.oom_fold_rank import run_fold_rank
from mappers.control_plane.console_oom_catalog import assess_materialisation, lookup_rfq_key
from mappers.control_plane.console_override_lane import lane_job_outcome, lane_venue, lookup_lane_key
from mappers.control_plane.console_override_sink import wait_for_override_sink
from mappers.control_plane.prices_state_merge_trigger import start_prices_state_merge

logger = logging.getLogger(__name__)

JobStatus = Literal[
    "accepted",
    "running",
    "materialised",
    "accepted_not_materialised",
    "failed",
]

_POLL_SEC = 3
_DEFAULT_MATERIALISE_TIMEOUT_SEC = 55
_JOB_TTL_SEC = 3600

_lock = threading.Lock()
_jobs: dict[str, OverrideJob] = {}


@dataclass
class OverrideJob:
    job_id: str
    status: JobStatus
    message: str
    active: bool
    sportsbook: str
    source_market_id: str
    source_selection_id: str
    steps: dict[str, Any] = field(default_factory=dict)
    lookup: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def _project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def _materialise_timeout_sec() -> int:
    raw = os.getenv("MAPPING_CONSOLE_OVERRIDE_MATERIALISE_TIMEOUT_SEC", "").strip()
    if not raw:
        return _DEFAULT_MATERIALISE_TIMEOUT_SEC
    return max(5, int(raw))


def _purge_stale_jobs() -> None:
    cutoff = time.time() - _JOB_TTL_SEC
    stale = [job_id for job_id, job in _jobs.items() if job.updated_at < cutoff]
    for job_id in stale:
        _jobs.pop(job_id, None)


def create_job(
    *,
    active: bool,
    sportsbook: str,
    source_market_id: str,
    source_selection_id: str,
) -> OverrideJob:
    with _lock:
        _purge_stale_jobs()
        job = OverrideJob(
            job_id=uuid.uuid4().hex,
            status="accepted",
            message="override publish accepted",
            active=active,
            sportsbook=sportsbook,
            source_market_id=source_market_id,
            source_selection_id=source_selection_id,
        )
        _jobs[job.job_id] = job
        return job


def get_job(job_id: str) -> OverrideJob | None:
    with _lock:
        return _jobs.get(job_id)


def _update_job(job: OverrideJob, **patch: Any) -> None:
    with _lock:
        for key, value in patch.items():
            setattr(job, key, value)
        job.updated_at = time.time()


def job_to_dict(job: OverrideJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "message": job.message,
        "active": job.active,
        "sportsbook": job.sportsbook,
        "source_market_id": job.source_market_id,
        "source_selection_id": job.source_selection_id,
        "steps": job.steps,
        "lookup": job.lookup,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _run_sink_step(
    job: OverrideJob,
    job_id: str,
    client: bigquery.Client,
    project: str,
    message: dict[str, Any],
    steps: dict[str, Any],
) -> bool:
    try:
        wait_for_override_sink(client, project, message)
        steps["sink"] = "ready"
        return True
    except Exception as exc:
        logger.warning("override sink wait failed job=%s: %s", job_id, exc)
        steps["sink_error"] = str(exc)
        _update_job(
            job,
            status="failed",
            message=f"override sink failed: {exc}",
            steps=steps,
        )
        return False


def _run_merge_step(
    job: OverrideJob,
    job_id: str,
    project: str,
    steps: dict[str, Any],
) -> bool:
    try:
        merge_run = start_prices_state_merge(project, wait=True)
        steps["merge_run"] = merge_run
    except Exception as exc:
        logger.warning("prices_state_merge trigger failed job=%s: %s", job_id, exc)
        steps["merge_error"] = str(exc)
        _update_job(
            job,
            status="accepted_not_materialised",
            message=f"accepted, not materialised: merge failed: {exc}",
            steps=steps,
        )
        return False
    if merge_run == "disabled":
        _update_job(
            job,
            status="accepted_not_materialised",
            message="accepted, not materialised: merge trigger disabled",
            steps=steps,
        )
        return False
    return True


def _run_rank_step(
    job: OverrideJob,
    job_id: str,
    client: bigquery.Client,
    project: str,
    steps: dict[str, Any],
) -> bool:
    try:
        run_fold_rank(client, project)
        steps["rank"] = "completed"
        return True
    except Exception as exc:
        logger.warning("on-demand fold+rank failed job=%s: %s", job_id, exc)
        steps["rank_error"] = str(exc)
        _update_job(
            job,
            status="accepted_not_materialised",
            message=f"accepted, not materialised: fold+rank failed: {exc}",
            steps=steps,
        )
        return False


def _poll_materialisation(
    job: OverrideJob,
    client: bigquery.Client,
    project: str,
) -> tuple[dict[str, Any], str | None]:
    deadline = time.monotonic() + _materialise_timeout_sec()
    lookup = lookup_rfq_key(
        client,
        sportsbook=job.sportsbook,
        source_market_id=job.source_market_id,
        source_selection_id=job.source_selection_id,
        project=project,
    )
    not_materialised = assess_materialisation(
        candidates=lookup["candidates"],
        expected_source_market_id=job.source_market_id,
        expected_source_selection_id=job.source_selection_id,
        active=job.active,
    )
    while not_materialised and time.monotonic() < deadline:
        time.sleep(_POLL_SEC)
        lookup = lookup_rfq_key(
            client,
            sportsbook=job.sportsbook,
            source_market_id=job.source_market_id,
            source_selection_id=job.source_selection_id,
            project=project,
        )
        not_materialised = assess_materialisation(
            candidates=lookup["candidates"],
            expected_source_market_id=job.source_market_id,
            expected_source_selection_id=job.source_selection_id,
            active=job.active,
        )
    return lookup, not_materialised


def _finish_materialisation(
    job: OverrideJob,
    steps: dict[str, Any],
    lookup: dict[str, Any],
    not_materialised: str | None,
) -> None:
    if not_materialised:
        _update_job(
            job,
            status="accepted_not_materialised",
            message=f"accepted, not materialised: {not_materialised}",
            steps=steps,
            lookup=lookup,
        )
        return
    verb = "materialised" if job.active else "deactivated"
    _update_job(
        job,
        status="materialised",
        message=f"override {verb} in opticodds_mapping",
        steps=steps,
        lookup=lookup,
    )


def _finish_lane_job(
    job: OverrideJob,
    client: bigquery.Client,
    project: str,
    steps: dict[str, Any],
) -> None:
    """Lane venues materialise at the next mapping pipeline run, not in this job."""
    lookup = lookup_lane_key(
        client,
        sportsbook=job.sportsbook,
        source_market_id=job.source_market_id,
        source_selection_id=job.source_selection_id,
        project=project,
    )
    status, message = lane_job_outcome(job.active)
    steps["lane"] = "market_mapping (next pipeline run)"
    _update_job(job, status=status, message=message, steps=steps, lookup=lookup)


def run_override_job(
    job_id: str,
    *,
    project: str,
    message: dict[str, Any],
    operator: str,
    reason: str,
) -> None:
    """Background: publish already done; sink → merge → rank → poll read-back."""
    job = get_job(job_id)
    if job is None:
        return
    _update_job(job, status="running", message="propagating override")
    logger.info(
        "override job start job=%s operator=%s reason=%s",
        job_id,
        operator,
        reason[:80],
    )
    client = bigquery.Client(project=project)
    steps: dict[str, Any] = dict(job.steps)
    try:
        if not _run_sink_step(job, job_id, client, project, message, steps):
            return
        if lane_venue(job.sportsbook):
            _finish_lane_job(job, client, project, steps)
            return
        if not _run_merge_step(job, job_id, project, steps):
            return
        if not _run_rank_step(job, job_id, client, project, steps):
            return
        lookup, not_materialised = _poll_materialisation(job, client, project)
        _finish_materialisation(job, steps, lookup, not_materialised)
    except Exception as exc:
        logger.exception("override job failed job=%s", job_id)
        _update_job(
            job,
            status="failed",
            message=str(exc),
            steps=steps,
        )


def start_override_job(
    *,
    message: dict[str, Any],
    operator: str,
    reason: str,
    active: bool,
    sportsbook: str,
    source_market_id: str,
    source_selection_id: str,
    publish_message_id: str,
) -> OverrideJob:
    """Create job record and spawn background propagation."""
    job = create_job(
        active=active,
        sportsbook=sportsbook,
        source_market_id=source_market_id,
        source_selection_id=source_selection_id,
    )
    job.steps["publish_message_id"] = publish_message_id
    project = _project()
    thread = threading.Thread(
        target=run_override_job,
        kwargs={
            "job_id": job.job_id,
            "project": project,
            "message": message,
            "operator": operator,
            "reason": reason,
        },
        name=f"override-job-{job.job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return job


# ---- batch propagation (bulk override, mmmapper#21) ------------------------------------------
# One merge and one fold+rank serve every override in a batch: N single jobs
# would run N merges and N full fold+ranks against the same tables. Each pair
# keeps its own OverrideJob (so the single-job poll endpoint still works) and
# is read back against one shared materialise deadline.


def _batch_pending(jobs: list[OverrideJob], client: bigquery.Client, project: str) -> list[OverrideJob]:
    """Look each job up once; finish the materialised ones, return the rest."""
    pending: list[OverrideJob] = []
    for job in jobs:
        lookup = lookup_rfq_key(
            client,
            sportsbook=job.sportsbook,
            source_market_id=job.source_market_id,
            source_selection_id=job.source_selection_id,
            project=project,
        )
        reason = assess_materialisation(
            candidates=lookup["candidates"],
            expected_source_market_id=job.source_market_id,
            expected_source_selection_id=job.source_selection_id,
            active=job.active,
        )
        if reason:
            job.lookup = lookup
            job.message = reason
            pending.append(job)
        else:
            _finish_materialisation(job, dict(job.steps), lookup, None)
    return pending


def _batch_read_back(jobs: list[OverrideJob], client: bigquery.Client, project: str) -> None:
    """Poll until every job materialises or the shared deadline passes."""
    deadline = time.monotonic() + _materialise_timeout_sec()
    pending = _batch_pending(jobs, client, project)
    while pending and time.monotonic() < deadline:
        time.sleep(_POLL_SEC)
        pending = _batch_pending(pending, client, project)
    for job in pending:
        _finish_materialisation(job, dict(job.steps), job.lookup or {}, job.message)


def _batch_propagate(entries: list[tuple[OverrideJob, dict[str, Any]]], project: str) -> None:
    """Sink each message, then merge + rank once, then read every job back."""
    client = bigquery.Client(project=project)
    live = [job for job, message in entries if _run_sink_step(job, job.job_id, client, project, message, job.steps)]
    if not live:
        return
    lead = live[0]
    shared: dict[str, Any] = {}
    ok = _run_merge_step(lead, lead.job_id, project, shared) and _run_rank_step(
        lead, lead.job_id, client, project, shared
    )
    for job in live:
        job.steps.update(shared)
    if not ok:
        for job in live[1:]:
            _update_job(job, status=lead.status, message=lead.message, steps=job.steps)
        return
    _batch_read_back(live, client, project)


def run_override_batch(entries: list[tuple[str, dict[str, Any]]], *, project: str) -> None:
    """Background: publish already done for every (job_id, message); propagate them together."""
    jobs = [(get_job(job_id), message) for job_id, message in entries]
    live = [(job, message) for job, message in jobs if job is not None]
    for job, _ in live:
        _update_job(job, status="running", message="propagating override (batch)")
    try:
        _batch_propagate(live, project)
    except Exception as exc:
        logger.exception("override batch failed")
        for job, _ in live:
            if job.status == "running":
                _update_job(job, status="failed", message=str(exc))


def start_override_batch(entries: list[tuple[str, dict[str, Any]]]) -> None:
    """Spawn one background propagation thread for a published batch."""
    if not entries:
        return
    thread = threading.Thread(
        target=run_override_batch,
        args=(entries,),
        kwargs={"project": _project()},
        name=f"override-batch-{entries[0][0][:8]}",
        daemon=True,
    )
    thread.start()
