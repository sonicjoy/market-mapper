"""Shared opticodds_mapping winner query builder (Release 068 G4/G5).

Keeps the SQL template in sync with MMutils.handlers.platform_mapping_loader.
"""

from __future__ import annotations

import re
from pathlib import Path

from google.cloud import bigquery

_WINNER_SQL_PATH = Path(__file__).resolve().parent / "sql" / "oom_winner_query.sql"
_LOOKUP_SQL_PATH = Path(__file__).resolve().parent / "sql" / "oom_rfq_key_lookup.sql"
_SAFE_BQ_TOKEN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _strip_sql_header_comments(template: str) -> str:
    """Drop leading blank/-- lines so ro_query sees WITH/SELECT first."""
    lines: list[str] = []
    for line in template.splitlines():
        if not lines and (not line.strip() or line.strip().startswith("--")):
            continue
        lines.append(line)
    return "\n".join(lines)


def build_winner_query(project_id: str, sportsbook_lower: str) -> str:
    """Return the shared winner query with project and sportsbook substituted."""
    if not _SAFE_BQ_TOKEN.match(project_id):
        raise ValueError(f"invalid project_id for winner query: {project_id!r}")
    sportsbook = sportsbook_lower.lower().strip()
    if not sportsbook or re.search(r"['\"\\;{}]", sportsbook):
        raise ValueError(f"invalid sportsbook for winner query: {sportsbook_lower!r}")
    raw = _strip_sql_header_comments(_WINNER_SQL_PATH.read_text(encoding="utf-8"))
    return raw.format(project=project_id, sportsbook_lower=sportsbook)


def build_rfq_key_lookup_sql(
    project_id: str,
    *,
    min_last_updated_days: int | None = None,
) -> str:
    """Return point-lookup SQL for one RFQ key (parameterized)."""
    if not _SAFE_BQ_TOKEN.match(project_id):
        raise ValueError(f"invalid project_id for lookup query: {project_id!r}")
    raw = _strip_sql_header_comments(_LOOKUP_SQL_PATH.read_text(encoding="utf-8"))
    recency_filter = ""
    if min_last_updated_days is not None:
        if min_last_updated_days < 1:
            raise ValueError(f"invalid min_last_updated_days: {min_last_updated_days}")
        recency_filter = (
            "    and (o.last_updated is null\n"
            "      or o.last_updated >= timestamp_sub(current_timestamp(), "
            f"interval {min_last_updated_days} day))\n"
        )
    return raw.format(project=project_id, recency_filter=recency_filter)


def rfq_key_lookup_job_config(
    *,
    sportsbook_lower: str,
    src_market_id: str,
    src_selection_id: str,
) -> bigquery.QueryJobConfig:
    """BigQuery parameters for :func:`build_rfq_key_lookup_sql`."""
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sportsbook_lower", "STRING", sportsbook_lower.lower()),
            bigquery.ScalarQueryParameter("src_market_id", "STRING", src_market_id or ""),
            bigquery.ScalarQueryParameter("src_selection_id", "STRING", src_selection_id or ""),
        ]
    )
