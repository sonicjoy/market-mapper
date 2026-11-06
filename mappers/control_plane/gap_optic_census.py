"""Live Optic market_id census from BigQuery.

``/fixtures/active`` (what ``cached_optic_fixtures`` fetches) carries no odds,
so a fixture payload alone cannot say which markets Optic is quoting.
``opticodds_us.prices_dedup_state`` is the deduplicated current pricing state,
so its distinct ``market_id`` values for a league's upcoming fixtures are the
live census the market-rule kernel is allowed to bind against.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query

logger = logging.getLogger(__name__)

CensusFn = Callable[[list[str], float], set[str]]

_BACK_HOURS = 6
# One Why / Venue-gaps node asks for the same league once per sampled leg; the
# census moves on the scale of fixtures being listed, not seconds.
CENSUS_TTL_SECONDS = 300.0
# Empty (no fixtures, or a failed query) is remembered briefly so a burst of legs
# does not re-query, without hiding fresh evidence for long.
CENSUS_EMPTY_TTL_SECONDS = 60.0

_census_cache: dict[tuple[tuple[str, ...], int], tuple[float, frozenset[str]]] = {}
_census_lock = threading.Lock()

_CENSUS_SQL = """
with fixtures as (
  select distinct game_id
  from `{project}.opticodds_us.opticodds_fixtures`
  where league.id in unnest(@optic_ids)
    and start_date > timestamp_sub(current_timestamp(), interval @back_hours hour)
    and start_date < timestamp_add(current_timestamp(), interval @fwd_hours hour)
)
select distinct p.market_id as market_id
from `{project}.opticodds_us.prices_dedup_state` p
inner join fixtures f using (game_id)
where p.market_id is not null and p.market_id != ''
"""


def fetch_optic_market_ids(
    optic_ids: list[str],
    *,
    horizon_hours: float = 96.0,
    project: str | None = None,
    query_fn: Callable[[str, list[str], int], Any] | None = None,
) -> set[str]:
    """Distinct Optic ``market_id`` values priced for these leagues' fixtures."""
    ids = [oid.strip() for oid in optic_ids if oid and oid.strip()]
    if not ids:
        return set()
    fwd = max(int(horizon_hours), 1)
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = _CENSUS_SQL.format(project=proj)
    try:
        rows = list(
            query_fn(sql, ids, fwd)
            if query_fn is not None
            else _query(proj, sql, ids, fwd)
        )
    except Exception as exc:  # noqa: BLE001 — census is optional evidence
        logger.warning("optic market census failed for %s: %s", ids, str(exc)[:160])
        return set()
    out = {str(getattr(row, "market_id", "") or "").strip() for row in rows}
    return {mid for mid in out if mid}


def _query(project: str, sql: str, optic_ids: list[str], fwd_hours: int) -> Any:
    """Run the census with bound parameters."""
    job = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("optic_ids", "STRING", optic_ids),
            bigquery.ScalarQueryParameter("back_hours", "INT64", _BACK_HOURS),
            bigquery.ScalarQueryParameter("fwd_hours", "INT64", fwd_hours),
        ],
    )
    return ro_query(bigquery.Client(project=project), sql, job_config=job)


def cached_optic_market_ids(optic_ids: list[str], *, horizon_hours: float = 96.0) -> set[str]:
    """:func:`fetch_optic_market_ids` memoised per (leagues, horizon) for ``CENSUS_TTL_SECONDS``.

    Empty results (no fixtures, or a failed query) live ``CENSUS_EMPTY_TTL_SECONDS``.
    """
    key = (tuple(sorted(oid.strip() for oid in optic_ids if oid and oid.strip())), max(int(horizon_hours), 1))
    now = time.monotonic()
    with _census_lock:
        hit = _census_cache.get(key)
        if hit is not None and now - hit[0] < (CENSUS_TTL_SECONDS if hit[1] else CENSUS_EMPTY_TTL_SECONDS):
            return set(hit[1])
    out = fetch_optic_market_ids(list(key[0]), horizon_hours=horizon_hours)
    with _census_lock:
        _census_cache[key] = (now, frozenset(out))
    return out


def clear_census_cache() -> None:
    """Drop memoised census results (tests)."""
    with _census_lock:
        _census_cache.clear()
