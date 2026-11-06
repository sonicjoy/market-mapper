"""Kick infra prices_state_merge_us on demand (Release 068 G5)."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta

from google.cloud.bigquery_datatransfer import (  # type: ignore[import-untyped]
    DataTransferServiceClient,
    StartManualTransferRunsRequest,
)
from google.cloud.bigquery_datatransfer_v1.types.transfer import TransferState  # type: ignore[import-untyped]

from BigQuery.alerts import bool_env

logger = logging.getLogger(__name__)

_MERGE_DISPLAY_NAME = "prices_state_merge_us"
_POLL_INTERVAL_SEC = 2
_DEFAULT_WAIT_SEC = 120
_LOCATION_BY_PROJECT = {
    "marketmaking-test": "us-east4",
    "rs-marketmaking": "europe-west2",
}


def merge_trigger_enabled() -> bool:
    """Kill switch; default on so console overrides propagate promptly."""
    return bool_env("MAPPING_CONSOLE_MERGE_TRIGGER_ENABLED", default=True)


def _transfer_location(project: str) -> str:
    explicit = os.getenv("PRICES_STATE_MERGE_TRANSFER_LOCATION", "").strip()
    if explicit:
        return explicit
    return _LOCATION_BY_PROJECT.get(project, "us-east4")


def _resolve_transfer_config_name(
    client: DataTransferServiceClient,
    project: str,
) -> str:
    explicit = os.getenv("PRICES_STATE_MERGE_TRANSFER_CONFIG", "").strip()
    if explicit:
        return explicit
    location = _transfer_location(project)
    parent = client.common_location_path(project, location)
    for config in client.list_transfer_configs(parent=parent):
        if config.display_name == _MERGE_DISPLAY_NAME:
            return config.name
    raise RuntimeError(
        f"transfer config {_MERGE_DISPLAY_NAME!r} not found in {project}/{location}"
    )


def _requested_run_time(*, now: datetime | None = None) -> datetime:
    """Past UTC instant required by StartManualTransferRuns for scheduled queries."""
    return (now or datetime.now(UTC)) - timedelta(minutes=1)


def start_prices_state_merge(
    project: str,
    *,
    wait: bool = True,
    timeout_sec: int = _DEFAULT_WAIT_SEC,
) -> str:
    """Start a manual prices_state_merge_us run; optionally wait for completion."""
    if not merge_trigger_enabled():
        logger.info("prices_state_merge trigger disabled project=%s", project)
        return "disabled"
    client = DataTransferServiceClient()
    config_name = _resolve_transfer_config_name(client, project)
    response = client.start_manual_transfer_runs(
        StartManualTransferRunsRequest(
            parent=config_name,
            requested_run_time=_requested_run_time(),
        )
    )
    runs = list(response.runs)
    if not runs:
        raise RuntimeError(f"StartManualTransferRuns returned no runs for {config_name}")
    run_name = runs[0].name
    logger.info("prices_state_merge manual run started project=%s run=%s", project, run_name)
    if not wait:
        return run_name
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        run = client.get_transfer_run(name=run_name)
        state = TransferState(run.state)
        if state in {
            TransferState.SUCCEEDED,
            TransferState.FAILED,
            TransferState.CANCELLED,
        }:
            if state != TransferState.SUCCEEDED:
                raise RuntimeError(
                    f"prices_state_merge run {state.name}: {run.error_status.message}"
                )
            return run_name
        time.sleep(_POLL_INTERVAL_SEC)
    raise TimeoutError(f"prices_state_merge run did not finish within {timeout_sec}s: {run_name}")
