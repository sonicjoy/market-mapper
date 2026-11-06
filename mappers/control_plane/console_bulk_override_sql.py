"""BigQuery reads for bulk override: a Kalshi event's unmapped legs, Optic fixtures, Optic selections.

All read-only. Unmapped legs use the same definition as Explore -> Unmapped
(``console_unmapped.py``): RFQ legs in the last 48h with no Optic fixture /
market / selection, minus any Kalshi ticker+side already in
``markets_us.market_mapping``. Optic selections come from
``opticodds_us.prices_dedup_state`` (current priced state, clustered on
game_id; ~119 MB upper bound per game read, dry-run 2026-09-26).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query

QueryFn = Callable[[str, list[bigquery.ScalarQueryParameter]], list[dict[str, Any]]]

KALSHI_EVENT_LEGS_SQL = """
with legs as (
  select
    json_value(l.platform_mapping, '$.market_ticker') as market_ticker,
    lower(json_value(l.platform_mapping, '$.side')) as side,
    json_value(l.platform_mapping, '$.yes_sub_title') as yes_sub_title,
    l.line as line
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
    and r.platform in ('kalshi', 'kalshi-inplay', 'kalshi-inplay-cashout')
    and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
    and json_value(l.platform_mapping, '$.event_ticker') = @event_ticker
),
mapped as (
  select distinct
    json_value(to_json_string(source_ids), '$.market_id') as market_ticker,
    lower(json_value(to_json_string(source_ids), '$.selection_id')) as side
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Kalshi'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
)
select
  g.market_ticker,
  coalesce(g.side, 'yes') as side,
  any_value(g.yes_sub_title) as yes_sub_title,
  any_value(g.line) as line,
  count(*) as demand
from legs g
left join mapped m
  on m.market_ticker = g.market_ticker and m.side = coalesce(g.side, 'yes')
where g.market_ticker is not null and m.market_ticker is null
group by 1, 2
order by demand desc
limit 200
"""  # nosec B608 - project from env; event ticker is a bound parameter

OPTIC_FIXTURES_SQL = """
select
  game_id,
  any_value(home_team_display) as home,
  any_value(away_team_display) as away,
  any_value(start_date) as start_date,
  any_value(league.id) as league
from `{project}.opticodds_us.opticodds_fixtures`
where start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
  and (@needle = ''
    or strpos(lower(home_team_display), @needle) > 0
    or strpos(lower(away_team_display), @needle) > 0)
  and (@day = '' or format_timestamp('%F', start_date) = @day)
group by game_id
order by start_date
limit 50
"""  # nosec B608 - project from env; needle/day are bound parameters

OPTIC_SELECTIONS_SQL = """
select
  market_id,
  any_value(market) as market,
  selection,
  ifnull(selection_line, '') as selection_line,
  ifnull(points, 0) as points,
  ifnull(selection_points, 0) as selection_points,
  ifnull(grouping_key, 'default') as grouping_key,
  count(distinct sportsbook) as books
from `{project}.opticodds_us.prices_dedup_state`
where game_id = @game_id
group by market_id, selection, selection_line, points, selection_points, grouping_key
order by market_id, selection, points
"""  # nosec B608 - project from env; game_id is a bound parameter


def console_project() -> str:
    """Console BQ project (GCP_PROJECT, else BQ_PROJECT)."""
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def default_query(sql: str, params: list[bigquery.ScalarQueryParameter]) -> list[dict[str, Any]]:
    """Run one read-only query against the console project."""
    project = console_project()
    client = bigquery.Client(project=project)
    job = ro_query(client, sql.format(project=project), job_config=bigquery.QueryJobConfig(query_parameters=params))
    return [dict(row) for row in job]


def _str_param(name: str, value: str) -> bigquery.ScalarQueryParameter:
    """STRING query parameter."""
    return bigquery.ScalarQueryParameter(name, "STRING", value)


def kalshi_event_legs(event_ticker: str, *, query_fn: QueryFn | None = None) -> list[dict[str, Any]]:
    """Unmapped (ticker, side) legs for one Kalshi event, busiest first."""
    fetch = query_fn or default_query
    return fetch(KALSHI_EVENT_LEGS_SQL, [_str_param("event_ticker", event_ticker.strip())])


def search_optic_fixtures(needle: str, day: str = "", *, query_fn: QueryFn | None = None) -> list[dict[str, Any]]:
    """Optic fixtures in the override rank window (4h back .. 14d) by team name and/or UTC day."""
    fetch = query_fn or default_query
    params = [_str_param("needle", needle.strip().lower()), _str_param("day", day.strip())]
    return fetch(OPTIC_FIXTURES_SQL, params)


def optic_selections(game_id: str, *, query_fn: QueryFn | None = None) -> list[dict[str, Any]]:
    """Every Optic selection currently priced for one game, one row per selection."""
    fetch = query_fn or default_query
    return fetch(OPTIC_SELECTIONS_SQL, [_str_param("game_id", game_id.strip())])
