"""Wait for mapping_override Pub/Sub → BQ sink before kicking merge."""

from __future__ import annotations

import json
import logging
import time

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.console_override_publish import CONSOLE_OVERRIDE_SOURCE
from synthetic.writers import _source_ids_equal

logger = logging.getLogger(__name__)

_POLL_SEC = 0.5
_DEFAULT_TIMEOUT_SEC = 30


def _expected_source_ids(message: dict) -> str:
    source_ids = message.get("source_ids") or "{}"
    if isinstance(source_ids, dict):
        return json.dumps(source_ids)
    return str(source_ids)


def _sink_job_config(message: dict) -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", message["game_id"]),
            bigquery.ScalarQueryParameter("market_id", "STRING", message["market_id"]),
            bigquery.ScalarQueryParameter("sportsbook", "STRING", message["sportsbook"]),
            bigquery.ScalarQueryParameter("selection", "STRING", message["selection"]),
            bigquery.ScalarQueryParameter(
                "selection_line", "STRING", message.get("selection_line") or ""
            ),
            bigquery.ScalarQueryParameter("points", "FLOAT64", float(message.get("points") or 0)),
            bigquery.ScalarQueryParameter(
                "selection_points", "FLOAT64", float(message.get("selection_points") or 0)
            ),
            bigquery.ScalarQueryParameter(
                "grouping_key", "STRING", message.get("grouping_key") or "default"
            ),
            bigquery.ScalarQueryParameter("source", "STRING", CONSOLE_OVERRIDE_SOURCE),
        ]
    )


def wait_for_override_sink(
    client: bigquery.Client,
    project: str,
    message: dict,
    *,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
) -> None:
    """Block until mapping_override reflects the published message (or timeout)."""
    expected_active = bool(message.get("active", True))
    expected_source_ids = _expected_source_ids(message)
    sql = f"""
        select
          active,
          to_json_string(source_ids) as source_ids_json
        from `{project}.opticodds_us.mapping_override`
        where game_id = @game_id
          and market_id = @market_id
          and lower(sportsbook) = lower(@sportsbook)
          and selection = @selection
          and ifnull(selection_line, '') = @selection_line
          and ifnull(points, 0) = @points
          and ifnull(selection_points, 0) = @selection_points
          and grouping_key = @grouping_key
          and json_value(attributes, '$.source') = @source
        order by publish_time desc
        limit 1
    """  # nosec B608 — project from env
    job_config = _sink_job_config(message)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        rows = list(ro_query(client, sql, job_config=job_config))
        if rows:
            row = rows[0]
            if (
                bool(row.active) == expected_active
                and _source_ids_equal(expected_source_ids, row.source_ids_json)
            ):
                return
        time.sleep(_POLL_SEC)
    raise TimeoutError(
        f"mapping_override sink did not reflect publish within {timeout_sec}s "
        f"for game_id={message.get('game_id')}"
    )
