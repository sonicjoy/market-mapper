"""Coverage fixture list from opticodds_fixtures (not live Optic HTTP)."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.console_fixture_phase import normalize_fixture_phase

_BACK_HOURS = 36

_LIST_SQL = """
select
  coalesce(nullif(id, ''), game_id) as fixture_id,
  game_id,
  start_date,
  status,
  home_team_display as home,
  away_team_display as away,
  league.id as optic_league_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.id') as home_id,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.id') as away_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.abbreviation') as home_abbr,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.abbreviation') as away_abbr,
  count(*) over() as total
from `{project}.opticodds_us.opticodds_fixtures`
where league.id in unnest(@optic_ids)
  and start_date > timestamp_sub(current_timestamp(), interval @back_hours hour)
  and start_date < timestamp_add(current_timestamp(), interval @fwd_hours hour)
  and (
    status is null
    or lower(status) not in ('completed', 'cancelled', 'canceled')
  )
  and (
    (@phase = 'live' and (
      lower(status) = 'live'
      or (
        coalesce(nullif(lower(status), ''), '') = ''
        and start_date < current_timestamp()
      )
    ))
    or (@phase = 'pre' and (
      lower(status) in ('unplayed', 'delayed')
      or (
        coalesce(nullif(lower(status), ''), '') = ''
        and (start_date >= current_timestamp() or start_date is null)
      )
    ))
  )
  and (
    @q = ''
    or strpos(
      lower(concat(ifnull(home_team_display, ''), ' ', ifnull(away_team_display, ''))),
      @q
    ) > 0
  )
order by start_date, coalesce(nullif(id, ''), game_id)
limit @limit offset @offset
"""

_ONE_SQL = """
select
  coalesce(nullif(id, ''), game_id) as fixture_id,
  game_id,
  start_date,
  status,
  home_team_display as home,
  away_team_display as away,
  league.id as optic_league_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.id') as home_id,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.id') as away_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.abbreviation') as home_abbr,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.abbreviation') as away_abbr
from `{project}.opticodds_us.opticodds_fixtures`
where (id = @fid or game_id = @fid)
  and start_date > timestamp_sub(current_timestamp(), interval @back_hours hour)
  and start_date < timestamp_add(current_timestamp(), interval @fwd_hours hour)
  and (
    status is null
    or lower(status) not in ('completed', 'cancelled', 'canceled')
  )
limit 1
"""


def _bq_project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def query_optic_coverage_fixtures(
    *,
    optic_ids: list[str],
    q: str | None,
    limit: int,
    offset: int,
    fwd_hours: int,
    phase: str = "live",
    back_hours: int = _BACK_HOURS,
) -> tuple[list[dict[str, Any]], int]:
    """One page of non-complete Optic fixtures from BigQuery (live or pre tab)."""
    ids = [oid for oid in optic_ids if oid]
    if not ids:
        return [], 0
    project = _bq_project()
    client = bigquery.Client(project=project)
    job = ro_query(
        client,
        _LIST_SQL.format(project=project),  # nosec B608 — project is env-derived
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("optic_ids", "STRING", ids),
                bigquery.ScalarQueryParameter("q", "STRING", (q or "").strip().lower()),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
                bigquery.ScalarQueryParameter("offset", "INT64", offset),
                bigquery.ScalarQueryParameter("fwd_hours", "INT64", fwd_hours),
                bigquery.ScalarQueryParameter("back_hours", "INT64", back_hours),
                bigquery.ScalarQueryParameter("phase", "STRING", normalize_fixture_phase(phase)),
            ]
        ),
    )
    rows = [dict(row) for row in job]
    total = int(rows[0]["total"]) if rows else 0
    for row in rows:
        row.pop("total", None)
    return rows, total


def query_one_optic_coverage_fixture(
    fixture_id: str,
    *,
    fwd_hours: int = 96,
    back_hours: int = _BACK_HOURS,
) -> dict[str, Any] | None:
    """Single fixture from BigQuery by Optic id or game_id."""
    fid = fixture_id.strip()
    if not fid:
        return None
    project = _bq_project()
    client = bigquery.Client(project=project)
    job = ro_query(
        client,
        _ONE_SQL.format(project=project),  # nosec B608 — project is env-derived
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("fid", "STRING", fid),
                bigquery.ScalarQueryParameter("fwd_hours", "INT64", fwd_hours),
                bigquery.ScalarQueryParameter("back_hours", "INT64", back_hours),
            ]
        ),
    )
    hit = next(iter(job), None)
    return dict(hit) if hit is not None else None
