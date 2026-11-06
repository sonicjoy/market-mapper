"""League registry: DEFAULT_LEAGUES overlaid by markets_us.goalscorer_leagues.

The table is append-only; the latest row per league_id wins and ``active =
false`` removes a league (defaults included). Rows are added from Slack by
posting an Optic league slug in the channel.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import requests
from google.cloud import bigquery

from BigQuery.client import is_missing_bq_table, ro_query, sandbox_query
from goalscorer import codes
from goalscorer.config import DEFAULT_LEAGUES, KALSHI_API, LEAGUES_TABLE, League
from goalscorer.timeutil import utcnow

logger = logging.getLogger(__name__)

_P = bigquery.ScalarQueryParameter
# Discovery window for a new league slug: recent + upcoming fixtures.
_LOOKBACK = timedelta(days=30)
_LOOKAHEAD = timedelta(days=60)


def _discovery_params(league_id: str) -> bigquery.QueryJobConfig:
    """Query params for a league slug over the discovery window."""
    now = utcnow()
    return bigquery.QueryJobConfig(
        query_parameters=[
            _P("since", "TIMESTAMP", now - _LOOKBACK),
            _P("until", "TIMESTAMP", now + _LOOKAHEAD),
            _P("league_id", "STRING", league_id),
        ]
    )


class LeagueRegistry:
    """Reads and appends league rows; also discovers a league's Kalshi series."""

    def __init__(self, client: bigquery.Client, project: str, *, dry_run: bool = False) -> None:
        self.client = client
        self.project = project
        self.dry_run = dry_run

    def active(self) -> dict[str, League]:
        """league_id → League for every league the job should map."""
        leagues = {lg.league_id: lg for lg in DEFAULT_LEAGUES}
        sql = f"""
            select league_id, goal_prefix, display_name, sport, active from (
              select *, row_number() over (partition by league_id order by added_at desc) as rn
              from `{self.project}.{LEAGUES_TABLE}`
            ) where rn = 1
        """  # nosec B608 — project from env
        try:
            rows = list(ro_query(self.client, sql))
        except Exception as exc:
            if not is_missing_bq_table(exc, LEAGUES_TABLE):
                raise
            logger.warning("%s missing — using built-in leagues only", LEAGUES_TABLE)
            return leagues
        for r in rows:
            if r.active:
                leagues[r.league_id] = League(r.league_id, r.goal_prefix, r.display_name, r.sport or "soccer")
            else:
                leagues.pop(r.league_id, None)
        return leagues

    def add(self, league: League, added_by: str, *, active: bool = True) -> None:
        """Append a league row (the newest row per league_id wins)."""
        if self.dry_run:
            logger.info("dry-run: would add league %s", league)
            return
        sql = f"""
            insert into `{self.project}.{LEAGUES_TABLE}`
              (league_id, goal_prefix, display_name, sport, active, added_by, added_at)
            values (@league_id, @goal_prefix, @display_name, @sport, @active, @added_by, current_timestamp())
        """  # nosec B608
        params = [
            _P("league_id", "STRING", league.league_id),
            _P("goal_prefix", "STRING", league.goal_prefix),
            _P("display_name", "STRING", league.display_name),
            _P("sport", "STRING", league.sport),
            _P("active", "BOOL", active),
            _P("added_by", "STRING", added_by),
        ]
        sandbox_query(self.client, sql, job_config=bigquery.QueryJobConfig(query_parameters=params))

    def optic_league(self, league_id: str) -> tuple[str, str] | None:
        """(display name, sport) for a slug with recent or upcoming Optic fixtures."""
        sql = f"""
            select any_value(f.league.name) as name, any_value(f.sport.id) as sport
            from `{self.project}.opticodds_us.opticodds_fixtures` f
            where f.start_date >= @since and f.start_date < @until and f.league.id = @league_id
            having count(*) > 0
        """  # nosec B608
        rows = list(ro_query(self.client, sql, job_config=_discovery_params(league_id)))
        return (rows[0].name or league_id, rows[0].sport or "soccer") if rows else None

    def derived_goal_prefix(self, league_id: str) -> str | None:
        """KX…GOAL series implied by the league's Kalshi moneyline mappings (KX…GAME)."""
        sql = f"""
            with games as (
              select distinct f.game_id
              from `{self.project}.opticodds_us.opticodds_fixtures` f
              where f.start_date >= @since and f.start_date < @until and f.league.id = @league_id
            )
            select split(json_value(m.source_ids, '$.market_id'), '-')[safe_offset(0)] as series,
                   count(*) as n
            from `{self.project}.opticodds_us.opticodds_mapping` m
            join games g on g.game_id = m.game_id
            where lower(m.sportsbook) = 'kalshi' and m.market_id = 'moneyline'
              and m.start_date >= @since and m.start_date < @until
            group by series order by n desc
        """  # nosec B608
        for r in ro_query(self.client, sql, job_config=_discovery_params(league_id)):
            prefix = codes.goal_prefix_for_series(r.series or "")
            if prefix:
                return prefix
        return None


def kalshi_series_exists(series_ticker: str) -> bool | None:
    """True/False from Kalshi's public series endpoint; None if Kalshi could not be asked."""
    try:
        resp = requests.get(f"{KALSHI_API}/series/{series_ticker}", timeout=10)
    except requests.RequestException as exc:
        logger.warning("kalshi series lookup failed for %s: %s", series_ticker, exc)
        return None
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    logger.warning("kalshi series lookup %s → HTTP %s", series_ticker, resp.status_code)
    return None
