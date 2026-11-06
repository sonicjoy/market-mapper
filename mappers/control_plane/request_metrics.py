"""Per-request BigQuery job accounting.

The console's latency is dominated by how many BigQuery jobs a request starts,
not by how much data it scans. A context-local counter makes that visible in
the access log so a regression shows up as a job-count jump.

The counter is a mutable cell rather than an int. Starlette runs the endpoint
in a spawned task, and sync endpoints run in an anyio worker thread; both get a
*copy* of the context, so rebinding an int inside would be invisible to the
middleware that reads it afterwards. Copies share the same cell object, so
mutating the cell propagates back.
"""

from __future__ import annotations

from contextvars import ContextVar

# Single-element list used as a shared mutable cell.
_bq_jobs: ContextVar[list[int]] = ContextVar("mapping_cp_bq_jobs")


def reset_bq_jobs() -> None:
    """Start a fresh count for one request, before the endpoint is dispatched."""
    _bq_jobs.set([0])


def record_bq_job() -> None:
    """Count one BigQuery job started on behalf of this request."""
    cell = _bq_jobs.get(None)
    if cell is not None:
        cell[0] += 1


def bq_jobs() -> int:
    """Jobs started so far in this request context."""
    cell = _bq_jobs.get(None)
    return cell[0] if cell is not None else 0
