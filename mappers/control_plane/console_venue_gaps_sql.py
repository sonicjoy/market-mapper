"""BigQuery for Explore → Venue gaps (crypto.com catalogue vs market_mapping).

The catalogue CTE mirrors ``fetch.crypto_com_underlying.UNDERLYING_CATALOGUE_QUERY``
(same market types and stale-event cut; a shorter publish window, see
``CATALOG_WINDOW_DAYS``) so the tab counts
exactly what the mapper would read. ``mapped`` is an exact symbol hit in
``markets_us.market_mapping`` — verified 2026-09-25: exact matches 27.5k of
47.6k live symbols; the ``.YYYYMMDD``-stripped fallback matches none.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from fetch.crypto_com_underlying import (
    CATALOGUE_EVENT_STALE_HOURS,
    EVENT_DATE_TS,
)
from mappers.control_plane.bq_ttl_cache import clear_ttl_cache, ttl_cached
from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_mf_cte

VenueGapQueryFn = Callable[[str, dict[str, Any]], list[dict[str, Any]]]

DEMAND_HOURS = 48
# The catalogue moves on crypto.com's listing cadence and the mapper's 15-min
# tick; one ~17 GB scan per window serves every rollup and fixture expand.
CATALOG_TTL_SECONDS = 900.0
DEMAND_TTL_SECONDS = 300.0
_NAMESPACE = "venue_gaps"
# The mapper reads 21 days, but crypto.com republishes every live symbol
# (~755 rows each over 21d). Measured 2026-09-26: of 50,637 live symbols,
# 99.7% were republished in the last 24h and 99.97% in the last 7d, and the
# 21-day selection-level read billed 45.6 GB. 7 days keeps all but ~14.
CATALOG_WINDOW_DAYS = 7

_CATALOG_HEAD = f"""
with cat as (
  select
    symbol,
    meta_league as meta_league,
    meta_sports_grouping as sport_grouping,
    {EVENT_DATE_TS} as event_at,
    meta_predict_market_type as market_group,
    meta_predict_contract_type as contract_type,
    meta_predict_period_type as period_type,
    meta_predict_market_id as market_id,
    meta_name as fixture_name,
    regexp_replace(coalesce(meta_event_name, ''), r'\\s+to win$', '') as outcome,
    meta_participant as participant,
    coalesce(
      regexp_extract(symbol, r'^(NX\\.F\\.OPT\\.[A-Z0-9]+-[0-9]+-[0-9]{{{{6}}}})'),
      concat(coalesce(meta_league, ''), '|', coalesce(meta_name, symbol))
    ) as fixture_key
  from `{{project}}.processed_upstream_us.crypto_underlying_securities`
  where meta_predict_market_type in (
      'Game Line', 'Fight Line', 'Player Prop', 'Team Prop', 'Game Prop', 'Fight Prop')
    and publish_time > timestamp_sub(current_timestamp(), interval {CATALOG_WINDOW_DAYS} day)
    and ({EVENT_DATE_TS} is null
      or {EVENT_DATE_TS} > timestamp_sub(
           current_timestamp(), interval {CATALOGUE_EVENT_STALE_HOURS} hour))
  qualify row_number() over (partition by symbol order by publish_time desc) = 1
),
mapped as (
  select distinct json_value(to_json_string(source_ids), '$.symbol') as symbol
  from `{{project}}.markets_us.market_mapping`
  where lower(sportsbook) = 'crypto.com'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
"""  # nosec B608 — interpolands are module constants, not caller input

_CATALOG_SELECT = """
select
  c.symbol, c.meta_league, c.sport_grouping, c.event_at, c.market_group,
  c.contract_type, c.period_type, c.market_id, c.fixture_name, c.outcome,
  c.participant, c.fixture_key, m.symbol is not null as is_mapped
from cat c
left join mapped m using (symbol)
"""

# Selection-level catalogue (~47k rows); rollup and fixture drill-down are
# computed from it in Python so an expand never re-scans BigQuery.
CATALOG_SQL = _CATALOG_HEAD + "x as (select 1)" + _CATALOG_SELECT  # nosec B608 — module constants only

# RFQ legs that failed mapping per symbol (rfq_latest; clustered + partition-bounded).
_DEMAND_CTE = crypto_rfq_mf_cte(hours=DEMAND_HOURS).strip().rstrip(",")
_DEMAND_SELECT = " select symbol, count(*) as demand from crypto_mf group by symbol"
DEMAND_SQL = "with " + _DEMAND_CTE + _DEMAND_SELECT  # nosec B608 — module constants only


def _bq_project() -> str:
    """Project the console reads (GCP_PROJECT, else BQ_PROJECT)."""
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def _run(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute one read-only query with STRING parameters."""
    project = _bq_project()
    client = bigquery.Client(project=project)
    job = ro_query(
        client,
        sql.format(project=project),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(name, "STRING", str(value)) for name, value in params.items()
            ]
        ),
    )
    return [dict(row) for row in job]


def default_venue_gap_query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one venue-gap query, memoised (catalogue 15 min, demand 5 min)."""
    ttl = CATALOG_TTL_SECONDS if sql == CATALOG_SQL else DEMAND_TTL_SECONDS
    key = (sql, repr(sorted(params.items())))
    return ttl_cached(_NAMESPACE, key, lambda: _run(sql, params), ttl=ttl)


def clear_venue_gap_cache() -> None:
    """Drop memoised catalogue results (Refresh button, tests)."""
    clear_ttl_cache(_NAMESPACE)


def run_venue_gap_query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute one read-only query uncached (callers that keep their own memo)."""
    return _run(sql, params)
