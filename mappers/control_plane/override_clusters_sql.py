"""BigQuery for Explore -> Override patterns (latest state of every mapping_override key).

Reads the Pub/Sub -> BQ sink ``opticodds_us.mapping_override``: one row per
publish, so the latest row per RFQ key (``book|source market|source selection``)
is the override's current state. ``attributes.source`` separates console overrides
(``mapping-console``) from the synthetic writer (``mm-synthetic``); scripts publish
without a source.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query

LOOKBACK_DAYS = 90
CACHE_TTL_SECONDS = 300.0

LATEST_OVERRIDES_SQL = """
select
  lower(sportsbook) as sportsbook,
  json_value(source_ids, '$.market_id') as source_market_id,
  json_value(source_ids, '$.selection_id') as source_selection_id,
  game_id,
  market_id,
  selection,
  selection_line,
  active,
  json_value(attributes, '$.source') as source,
  json_value(attributes, '$.operator') as operator,
  publish_time
from `{project}.opticodds_us.mapping_override`
where publish_time > timestamp_sub(current_timestamp(), interval {days} day)
qualify row_number() over (
  partition by lower(sportsbook),
    json_value(source_ids, '$.market_id'),
    json_value(source_ids, '$.selection_id')
  order by publish_time desc
) = 1
"""  # nosec B608 - project from env, days is a module constant

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


def _project() -> str:
    """Project the console reads (GCP_PROJECT, else BQ_PROJECT)."""
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def fetch_latest_overrides(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Latest row per override key over ``LOOKBACK_DAYS``, memoised for ``CACHE_TTL_SECONDS``."""
    project = _project()
    now = time.monotonic()
    with _lock:
        hit = _cache.get(project)
        if not refresh and hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    sql = LATEST_OVERRIDES_SQL.format(project=project, days=LOOKBACK_DAYS)
    rows = [dict(row) for row in ro_query(bigquery.Client(project=project), sql)]
    with _lock:
        _cache[project] = (now, rows)
    return rows


def clear_override_cache() -> None:
    """Drop memoised override rows (Refresh, tests)."""
    with _lock:
        _cache.clear()
