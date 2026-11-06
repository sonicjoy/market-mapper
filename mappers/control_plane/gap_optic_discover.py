"""Discover Optic league id when the tip does not yet own the book meta."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query


def discover_optic_league_id(
    cat: dict[str, Any],
    *,
    sides: tuple[str, str],
    day: str,
    project: str | None = None,
    query_fn: Any | None = None,
) -> str | None:
    """Return Optic league.id when exactly one league matches fixture names on ``day``."""
    if not day or len(day) < 10:
        return None
    home, away = sides[0].strip(), sides[1].strip()
    if not home or not away:
        return None
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = f"""
select league.id as optic_league_id, count(*) as n
from `{proj}.opticodds_us.opticodds_fixtures` f
where date(f.start_date) = date(@day)
  and (
    (lower(f.home_team_display) = lower(@home) and lower(f.away_team_display) = lower(@away))
    or (lower(f.home_team_display) = lower(@away) and lower(f.away_team_display) = lower(@home))
  )
  and f.start_date > timestamp_sub(current_timestamp(), interval 21 day)
group by 1
having count(*) >= 1
"""  # nosec B608 — project is env/default; names and day are query params
    params = [
        bigquery.ScalarQueryParameter("day", "STRING", day[:10]),
        bigquery.ScalarQueryParameter("home", "STRING", home),
        bigquery.ScalarQueryParameter("away", "STRING", away),
    ]
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    if query_fn is not None:
        rows = list(query_fn(sql, job_config=job_config))
    else:
        client = bigquery.Client(project=proj)
        rows = list(ro_query(client, sql, job_config=job_config))
    ids = [str(getattr(r, "optic_league_id", "") or r.get("optic_league_id", "")) for r in rows]
    ids = [i for i in ids if i]
    if len(ids) == 1:
        return ids[0]
    return None
