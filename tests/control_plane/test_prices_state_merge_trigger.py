"""prices_state_merge on-demand trigger (Release 068 G5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from google.cloud.bigquery_datatransfer_v1.types.transfer import TransferState

from mappers.control_plane.prices_state_merge_trigger import (
    _requested_run_time,
    start_prices_state_merge,
)


def test_requested_run_time_is_one_minute_before_now() -> None:
    now = datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC)
    assert _requested_run_time(now=now) == now - timedelta(minutes=1)


def test_start_prices_state_merge_passes_requested_run_time() -> None:
    mock_client = MagicMock()
    config_name = "projects/p/locations/l/transferConfigs/c"
    mock_run = MagicMock(name="projects/p/locations/l/runs/r1", state=TransferState.SUCCEEDED)
    mock_client.start_manual_transfer_runs.return_value = MagicMock(runs=[mock_run])
    fixed = datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC)

    with (
        patch(
            "mappers.control_plane.prices_state_merge_trigger.DataTransferServiceClient",
            return_value=mock_client,
        ),
        patch(
            "mappers.control_plane.prices_state_merge_trigger.merge_trigger_enabled",
            return_value=True,
        ),
        patch(
            "mappers.control_plane.prices_state_merge_trigger._resolve_transfer_config_name",
            return_value=config_name,
        ),
        patch(
            "mappers.control_plane.prices_state_merge_trigger._requested_run_time",
            return_value=fixed,
        ),
    ):
        start_prices_state_merge("marketmaking-test", wait=False)

    request = mock_client.start_manual_transfer_runs.call_args[0][0]
    assert request.parent == config_name
    assert request.requested_run_time == fixed
