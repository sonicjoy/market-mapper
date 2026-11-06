"""BigQuery reads/writes for the goalscorer mapper (all queries parameterised).

opticodds_fixtures and opticodds_mapping are start_date-partitioned and
kalshi_tickers_v2 is publish_time-partitioned; every query bounds them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from google.cloud import bigquery

from BigQuery.client import ro_query, sandbox_query
from goalscorer import codes
from goalscorer.config import (
    FIRST_GOAL_MARKET_ID,
    MAPPING_SOURCE,
    MARKET_ID,
    MARKET_NAMES,
    MULTI_GOAL_LINES,
    PLAYER_GOALS_MARKET_ID,
    PLAYER_GOALS_MARKET_NAME,
)
from goalscorer.models import (
    Fixture,
    GoalMapping,
    KnowledgeRow,
    LineKnowledgeRow,
    LineMapping,
    Moneyline,
    OverrideState,
)

logger = logging.getLogger(__name__)

_P = bigquery.ScalarQueryParameter
_A = bigquery.ArrayQueryParameter


def _config(*params) -> bigquery.QueryJobConfig:
    """QueryJobConfig from parameters."""
    return bigquery.QueryJobConfig(query_parameters=list(params))


def _window(since: datetime, until: datetime) -> tuple[bigquery.ScalarQueryParameter, ...]:
    """@since / @until timestamp parameters."""
    return _P("since", "TIMESTAMP", since), _P("until", "TIMESTAMP", until)


_FIXTURE_COLUMNS = """
    f.game_id, f.start_date, f.league.id as league_id,
    f.home_competitors[safe_offset(0)].name as home_name,
    f.home_competitors[safe_offset(0)].id as home_id,
    f.away_competitors[safe_offset(0)].name as away_name,
    f.away_competitors[safe_offset(0)].id as away_id,
    row_number() over (partition by f.game_id order by f.publish_time desc) as rn
"""

_GOAL_MAPPING_FILTER = """
    lower(m.sportsbook) = 'kalshi' and m.market_id in unnest(@market_ids)
    and m.start_date >= @since and m.start_date < @until
"""

# The mapping_override key shape anytime and first goalscorer overrides share (@market_id picks one).
_OVERRIDE_KEY_FILTER = """
    market_id = @market_id and lower(sportsbook) = 'kalshi' and ifnull(selection_line, '') = ''
    and ifnull(points, 0) = 0 and ifnull(selection_points, 0) = 0 and grouping_key = 'default'
"""

# player_goals over 1.5 / 2.5 — the lines Kalshi's 2+ / 3+ goal markets map to.
_LINE_POINTS = ", ".join(str(p) for p in sorted(MULTI_GOAL_LINES.values()))
_LINE_KEY_FILTER = f"""
    market_id = '{PLAYER_GOALS_MARKET_ID}' and lower(sportsbook) = 'kalshi' and selection_line = 'over'
    and points in ({_LINE_POINTS})
"""


class GoalscorerStore:
    """Query layer over opticodds_us, processed_upstream_us and markets_us."""

    def __init__(self, client: bigquery.Client, project: str) -> None:
        self.client = client
        self.project = project

    def _rows(self, sql: str, *params) -> list[bigquery.Row]:
        """Run a parameterised read-only query."""
        return list(ro_query(self.client, sql, job_config=_config(*params)))

    def fixtures(self, since: datetime, until: datetime, league_ids: Iterable[str]) -> list[Fixture]:
        """Fixtures kicking off in [since, until) for the given leagues."""
        sql = f"""
            select * except (rn) from (
              select {_FIXTURE_COLUMNS}
              from `{self.project}.opticodds_us.opticodds_fixtures` f
              where f.start_date >= @since and f.start_date < @until
                and f.league.id in unnest(@league_ids)
            ) where rn = 1 order by start_date
        """  # nosec B608 — project from env, values bound as parameters
        rows = self._rows(sql, *_window(since, until), _A("league_ids", "STRING", sorted(league_ids)))
        return [Fixture(**dict(r.items())) for r in rows]

    def fixture_by_ref(self, ref: str, since: datetime, until: datetime) -> Fixture | None:
        """Look a fixture up by Optic fixture id or game_id."""
        sql = f"""
            select * except (rn) from (
              select {_FIXTURE_COLUMNS}
              from `{self.project}.opticodds_us.opticodds_fixtures` f
              where f.start_date >= @since and f.start_date < @until
                and (f.game_id = @ref or f.id = @ref)
            ) where rn = 1
        """  # nosec B608
        rows = self._rows(sql, *_window(since, until), _P("ref", "STRING", ref))
        return Fixture(**dict(rows[0].items())) if rows else None

    def games_for_fixture_part(self, fixture: str, since: datetime, until: datetime) -> list[str]:
        """Optic game_ids whose Kalshi moneyline ticker carries this fixture part."""
        sql = f"""
            select distinct m.game_id
            from `{self.project}.opticodds_us.opticodds_mapping` m
            where lower(m.sportsbook) = 'kalshi' and m.market_id = 'moneyline'
              and m.start_date >= @since and m.start_date < @until
              and split(json_value(m.source_ids, '$.market_id'), '-')[safe_offset(1)] = @fixture
        """  # nosec B608
        return [r.game_id for r in self._rows(sql, *_window(since, until), _P("fixture", "STRING", fixture))]

    def moneylines(self, game_ids: Sequence[str], since: datetime, until: datetime) -> dict[str, Moneyline]:
        """Kalshi moneyline fixture part + team abbreviations per game."""
        if not game_ids:
            return {}
        sql = f"""
            select distinct m.game_id, m.selection, json_value(m.source_ids, '$.market_id') as ticker
            from `{self.project}.opticodds_us.opticodds_mapping` m
            where lower(m.sportsbook) = 'kalshi' and m.market_id = 'moneyline'
              and m.game_id in unnest(@game_ids) and m.selection != 'Draw'
              and m.start_date >= @since and m.start_date < @until
        """  # nosec B608
        out: dict[str, Moneyline] = {}
        for r in self._rows(sql, *_window(since, until), _A("game_ids", "STRING", list(game_ids))):
            if not r.ticker:
                continue
            ml = out.setdefault(r.game_id, Moneyline(codes.fixture_part(r.ticker), codes.series(r.ticker), {}))
            ml.teams[r.selection] = codes.ml_team_abbrev(r.ticker)
        return out

    def goal_mappings(
        self, game_ids: Sequence[str], since: datetime, until: datetime, market_id: str = MARKET_ID
    ) -> list[GoalMapping]:
        """Kalshi anytime (or first goalscorer) rows already in opticodds_mapping for these games."""
        return self._kalshi_rows(game_ids, since, until, [market_id])

    def held_rows(self, game_ids: Sequence[str], since: datetime, until: datetime) -> list[GoalMapping]:
        """Kalshi anytime, first goalscorer and player_goals rows for these games, in one read.

        Each market and goal line has its own tickers, so one set answers "is this ticker held" for all of them.
        """
        return self._kalshi_rows(game_ids, since, until, [MARKET_ID, FIRST_GOAL_MARKET_ID, PLAYER_GOALS_MARKET_ID])

    def _kalshi_rows(
        self, game_ids: Sequence[str], since: datetime, until: datetime, market_ids: Sequence[str]
    ) -> list[GoalMapping]:
        """Kalshi rows on `market_ids` in opticodds_mapping for these games."""
        if not game_ids:
            return []
        sql = f"""
            select m.game_id, m.start_date, m.selection, ifnull(m.mapping_source, '') as mapping_source,
                   json_value(m.source_ids, '$.market_id') as ticker
            from `{self.project}.opticodds_us.opticodds_mapping` m
            where {_GOAL_MAPPING_FILTER} and m.game_id in unnest(@game_ids)
        """  # nosec B608
        params = (_A("game_ids", "STRING", list(game_ids)), _A("market_ids", "STRING", list(market_ids)))
        rows = self._rows(sql, *_window(since, until), *params)
        return [GoalMapping(**dict(r.items())) for r in rows if r.ticker]

    def line_mappings(self, game_ids: Sequence[str], since: datetime, until: datetime) -> list[LineMapping]:
        """Kalshi player_goals over 1.5 / 2.5 rows already in opticodds_mapping for these games."""
        if not game_ids:
            return []
        sql = f"""
            select m.game_id, m.selection, m.points, ifnull(m.mapping_source, '') as mapping_source,
                   json_value(m.source_ids, '$.market_id') as ticker
            from `{self.project}.opticodds_us.opticodds_mapping` m
            where {_LINE_KEY_FILTER} and m.game_id in unnest(@game_ids)
              and m.start_date >= @since and m.start_date < @until
        """  # nosec B608
        rows = self._rows(sql, *_window(since, until), _A("game_ids", "STRING", list(game_ids)))
        return [LineMapping(**dict(r.items())) for r in rows if r.ticker]

    def latest_line_overrides(self, game_ids: Sequence[str]) -> list[OverrideState]:
        """Latest mapping_override message per player_goals over 1.5 / 2.5 key for these games."""
        if not game_ids:
            return []
        sql = f"""
            select game_id, selection, points,
              json_value(array_agg(source_ids order by publish_time desc limit 1)[offset(0)], '$.market_id')
                as ticker,
              array_agg(active order by publish_time desc limit 1)[offset(0)] as active,
              array_agg(ifnull(json_value(attributes, '$.source'), '')
                order by publish_time desc limit 1)[offset(0)] as source
            from `{self.project}.opticodds_us.mapping_override`
            where game_id in unnest(@game_ids) and {_LINE_KEY_FILTER}
            group by game_id, selection, points
        """  # nosec B608
        rows = self._rows(sql, _A("game_ids", "STRING", list(game_ids)))
        return [
            OverrideState(r.game_id, r.selection, r.ticker or "", bool(r.active), r.source, float(r.points))
            for r in rows
        ]

    def line_overrides_since(self, since: datetime, source: str) -> list[OverrideState]:
        """Latest player_goals 1.5 / 2.5 override per key on every game `source` published lines to since `since`."""
        games = f"""
            select distinct game_id from `{self.project}.opticodds_us.mapping_override`
            where publish_time >= @since and json_value(attributes, '$.source') = @source and {_LINE_KEY_FILTER}
        """  # nosec B608
        game_ids = [
            r.game_id for r in self._rows(games, _P("since", "TIMESTAMP", since), _P("source", "STRING", source))
        ]
        return self.latest_line_overrides(game_ids)

    def team_history(
        self, competitor_ids: Sequence[str], since: datetime, until: datetime
    ) -> dict[str, list[GoalMapping]]:
        """Kalshi anytime and first goalscorer rows from each competitor's games in [since, until).

        Both carry the player's code; Optic maps Kalshi's first goalscorer markets
        for players it doesn't map on anytime, so they widen the history.
        """
        if not competitor_ids:
            return {}
        sql = f"""
            with prev as (
              select distinct c.id as competitor_id, f.game_id
              from `{self.project}.opticodds_us.opticodds_fixtures` f,
                   unnest(array_concat(f.home_competitors, f.away_competitors)) c
              where f.start_date >= @since and f.start_date < @until
                and c.id in unnest(@competitor_ids)
            )
            select p.competitor_id, m.game_id, m.start_date, m.selection,
                   ifnull(m.mapping_source, '') as mapping_source,
                   json_value(m.source_ids, '$.market_id') as ticker
            from prev p
            join `{self.project}.opticodds_us.opticodds_mapping` m on m.game_id = p.game_id
            where {_GOAL_MAPPING_FILTER}
        """  # nosec B608
        params = (
            *_window(since, until),
            _A("competitor_ids", "STRING", list(competitor_ids)),
            _A("market_ids", "STRING", list(MARKET_NAMES)),
        )
        out: dict[str, list[GoalMapping]] = {}
        for r in self._rows(sql, *params):
            if r.ticker:
                row = GoalMapping(r.game_id, r.start_date, r.selection, r.mapping_source, r.ticker)
                out.setdefault(r.competitor_id, []).append(row)
        return out

    def sportsbook_names(self, game_ids: Sequence[str], since: datetime, until: datetime) -> dict[str, set[str]]:
        """Goalscorer selection names any book publishes (Optic ORIGINAL) per game."""
        if not game_ids:
            return {}
        sql = f"""
            select distinct m.game_id, m.selection
            from `{self.project}.opticodds_us.opticodds_mapping` m
            where m.market_id in unnest(@market_ids) and m.mapping_source = 'ORIGINAL'
              and m.game_id in unnest(@game_ids)
              and m.start_date >= @since and m.start_date < @until
        """  # nosec B608
        params = (_A("game_ids", "STRING", list(game_ids)), _A("market_ids", "STRING", list(MARKET_NAMES)))
        out: dict[str, set[str]] = {}
        for r in self._rows(sql, *_window(since, until), *params):
            out.setdefault(r.game_id, set()).add(r.selection)
        return out

    def goal_leg_tickers(
        self, prefixes: Sequence[str], fixtures: Sequence[str], since: datetime, until: datetime
    ) -> list[str]:
        """Distinct Kalshi goal tickers seen as RFQ legs for these fixtures."""
        if not prefixes or not fixtures:
            return []
        sql = f"""
            select distinct leg.market_ticker as ticker
            from `{self.project}.processed_upstream_us.kalshi_tickers_v2` t, unnest(t.legs) leg
            where t.publish_time >= @since and t.publish_time < @until
              and split(leg.market_ticker, '-')[safe_offset(0)] in unnest(@prefixes)
              and split(leg.market_ticker, '-')[safe_offset(1)] in unnest(@fixtures)
        """  # nosec B608
        params = (
            *_window(since, until),
            _A("prefixes", "STRING", list(prefixes)),
            _A("fixtures", "STRING", list(fixtures)),
        )
        return sorted(r.ticker for r in self._rows(sql, *params))

    def _latest_overrides(self, game_filter: str, *params) -> list[OverrideState]:
        """Latest mapping_override message per goalscorer key on the games `game_filter` selects."""
        sql = f"""
            select game_id, selection,
              json_value(array_agg(source_ids order by publish_time desc limit 1)[offset(0)], '$.market_id')
                as ticker,
              array_agg(active order by publish_time desc limit 1)[offset(0)] as active,
              array_agg(ifnull(json_value(attributes, '$.source'), '')
                order by publish_time desc limit 1)[offset(0)] as source
            from `{self.project}.opticodds_us.mapping_override`
            where {game_filter} and {_OVERRIDE_KEY_FILTER}
            group by game_id, selection
        """  # nosec B608
        rows = self._rows(sql, *params)
        return [OverrideState(r.game_id, r.selection, r.ticker or "", bool(r.active), r.source) for r in rows]

    def latest_overrides(self, game_ids: Sequence[str], market_id: str = MARKET_ID) -> list[OverrideState]:
        """Latest mapping_override message per anytime (or first goalscorer) key for these games."""
        if not game_ids:
            return []
        return self._latest_overrides(
            "game_id in unnest(@game_ids)",
            _A("game_ids", "STRING", list(game_ids)),
            _P("market_id", "STRING", market_id),
        )

    def overrides_since(self, since: datetime, source: str, market_id: str = MARKET_ID) -> list[OverrideState]:
        """Latest override per anytime (or first goalscorer) key on every game `source` published to since `since`."""
        games = f"""game_id in (
              select game_id from `{self.project}.opticodds_us.mapping_override`
              where publish_time >= @since and json_value(attributes, '$.source') = @source
                and {_OVERRIDE_KEY_FILTER})"""  # nosec B608
        return self._latest_overrides(
            games,
            _P("since", "TIMESTAMP", since),
            _P("source", "STRING", source),
            _P("market_id", "STRING", market_id),
        )

    def insert_knowledge(self, rows: Sequence[KnowledgeRow], market_id: str = MARKET_ID) -> int:
        """Record anytime (or first goalscorer) rows for past games; skips any game+selection or ticker present.

        The existence check is a separate SELECT: inside DML the same read is not
        cluster-pruned (dry run 0 GB as SELECT vs ~2 GB as INSERT … SELECT).
        """
        if not rows:
            return 0
        starts = [r.start_date for r in rows]
        existing = self.goal_mappings(
            sorted({r.game_id for r in rows}),
            min(starts) - timedelta(days=1),
            max(starts) + timedelta(days=1),
            market_id,
        )
        taken = {(m.game_id, m.selection) for m in existing} | {(m.game_id, m.ticker) for m in existing}
        new = [r for r in rows if (r.game_id, r.selection) not in taken and (r.game_id, r.ticker) not in taken]
        if not new:
            return 0
        sql = f"""
            insert into `{self.project}.opticodds_us.opticodds_mapping`
              (game_id, start_date, sport, league, market_id, market, sportsbook, selection,
               selection_line, points, selection_points, is_main, is_live, grouping_key, exclude_fees,
               source_ids, last_updated, is_mapping_override, mapping_source)
            select s.game_id, s.start_date, s.sport, s.league, @market_id, @market, 'Kalshi',
                   s.selection, '', 0.0, 0.0, true, false, 'default', false,
                   json_object('market_id', s.ticker, 'selection_id', 'yes'),
                   current_timestamp(), true, '{MAPPING_SOURCE}'
            from unnest(@rows) s
        """  # nosec B608
        params = (
            _A("rows", "STRUCT", [_knowledge_struct(r) for r in new]),
            _P("market_id", "STRING", market_id),
            _P("market", "STRING", MARKET_NAMES[market_id]),
        )
        result = sandbox_query(self.client, sql, job_config=_config(*params))
        inserted = result.num_dml_affected_rows or 0
        logger.info("%s knowledge rows inserted=%d of %d", market_id, inserted, len(rows))
        return inserted

    def insert_line_knowledge(self, rows: Sequence[LineKnowledgeRow]) -> int:
        """Record 2+ / 3+ tickers as player_goals over rows for past games.

        Skips any game+selection+points or game+ticker already present (same
        separate-SELECT existence check as insert_knowledge).
        """
        if not rows:
            return 0
        starts = [r.start_date for r in rows]
        existing = self.line_mappings(
            sorted({r.game_id for r in rows}), min(starts) - timedelta(days=1), max(starts) + timedelta(days=1)
        )
        taken = {(m.game_id, m.selection, m.points) for m in existing}
        taken_tickers = {(m.game_id, m.ticker) for m in existing}
        new = [
            r
            for r in dict.fromkeys(rows)
            if (r.game_id, r.selection, r.points) not in taken and (r.game_id, r.ticker) not in taken_tickers
        ]
        if not new:
            return 0
        sql = f"""
            insert into `{self.project}.opticodds_us.opticodds_mapping`
              (game_id, start_date, sport, league, market_id, market, sportsbook, selection,
               selection_line, points, selection_points, is_main, is_live, grouping_key, exclude_fees,
               source_ids, last_updated, is_mapping_override, mapping_source)
            select s.game_id, s.start_date, s.sport, s.league, '{PLAYER_GOALS_MARKET_ID}',
                   '{PLAYER_GOALS_MARKET_NAME}', 'Kalshi', s.selection, 'over', s.points, s.points,
                   true, false, s.grouping_key, false,
                   json_object('market_id', s.ticker, 'selection_id', 'yes'),
                   current_timestamp(), true, '{MAPPING_SOURCE}'
            from unnest(@rows) s
        """  # nosec B608
        params = (_A("rows", "STRUCT", [_line_knowledge_struct(r) for r in new]),)
        result = sandbox_query(self.client, sql, job_config=_config(*params))
        inserted = result.num_dml_affected_rows or 0
        logger.info("line knowledge rows inserted=%d of %d", inserted, len(rows))
        return inserted


def _knowledge_struct(row: KnowledgeRow) -> bigquery.StructQueryParameter:
    """One @rows struct for insert_knowledge."""
    return bigquery.StructQueryParameter(
        None,
        _P("game_id", "STRING", row.game_id),
        _P("start_date", "TIMESTAMP", row.start_date),
        _P("sport", "STRING", row.sport),
        _P("league", "STRING", row.league),
        _P("selection", "STRING", row.selection),
        _P("ticker", "STRING", row.ticker),
    )


def _line_knowledge_struct(row: LineKnowledgeRow) -> bigquery.StructQueryParameter:
    """One @rows struct for insert_line_knowledge."""
    return bigquery.StructQueryParameter(
        None,
        _P("game_id", "STRING", row.game_id),
        _P("start_date", "TIMESTAMP", row.start_date),
        _P("sport", "STRING", row.sport),
        _P("league", "STRING", row.league),
        _P("selection", "STRING", row.selection),
        _P("ticker", "STRING", row.ticker),
        _P("points", "FLOAT64", row.points),
        _P("grouping_key", "STRING", codes.player_goals_key(row.selection, row.points)),
    )
