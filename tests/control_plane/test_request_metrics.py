"""The BigQuery job counter must survive the hop into the endpoint.

Starlette runs the endpoint in a spawned task, and sync endpoints run in an
anyio worker thread. Both get a *copy* of the context, so a counter that
rebinds an int would leave the middleware logging zero for every request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from mappers.control_plane.request_metrics import bq_jobs, record_bq_job, reset_bq_jobs


def _app(seen: dict[str, int]) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def timing(request: Request, call_next: Callable[[Request], Any]) -> Any:
        reset_bq_jobs()
        response = await call_next(request)
        seen[request.scope["path"]] = bq_jobs()
        return response

    @app.get("/sync")
    def sync_endpoint() -> dict[str, int]:
        for _ in range(3):
            record_bq_job()
        return {"inner": bq_jobs()}

    @app.get("/async")
    async def async_endpoint() -> dict[str, int]:
        for _ in range(5):
            record_bq_job()
        return {"inner": bq_jobs()}

    @app.get("/quiet")
    def quiet_endpoint() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_middleware_sees_jobs_counted_in_a_sync_endpoint():
    seen: dict[str, int] = {}
    client = TestClient(_app(seen))
    assert client.get("/sync").json()["inner"] == 3
    assert seen["/sync"] == 3


def test_middleware_sees_jobs_counted_in_an_async_endpoint():
    seen: dict[str, int] = {}
    client = TestClient(_app(seen))
    assert client.get("/async").json()["inner"] == 5
    assert seen["/async"] == 5


def test_counts_do_not_leak_between_requests():
    seen: dict[str, int] = {}
    client = TestClient(_app(seen))
    client.get("/sync")
    client.get("/quiet")
    assert seen["/quiet"] == 0


def test_recording_outside_a_request_is_a_no_op():
    """Cron jobs share the store and must not need middleware to call it."""
    record_bq_job()
    assert bq_jobs() == 0
