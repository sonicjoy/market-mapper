-- Our mappings enriched with fixture context from optic.
--
-- One row per mapping row, joined 1:1 to opticodds_fixtures for
-- team names, start time, sport, league, status.  Each mapping
-- row is already per-sportsbook, so no fan-out.
--
-- The fixtures CTE filters to games starting in the next 24 hours
-- and deduplicates rescheduled games (latest start_date wins).
--
-- ~6.5 MB scan.

WITH fixtures AS (
  SELECT *
  FROM opticodds_us.opticodds_fixtures
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
)
SELECT
  f.start_date,
  f.sport.name AS sport,
  f.league.name AS league,
  f.home_team_display,
  f.away_team_display,
  f.status,

  m.market_type,
  m.entity,
  m.line,
  m.side,

  m.game_id,
  m.market_id,
  m.selection,
  m.selection_line,
  m.points,

  m.sportsbook,
  m.source_ids,

  m.last_updated
FROM greg_sandbox.market_mapping m
JOIN fixtures f ON f.game_id = m.game_id
ORDER BY f.start_date, f.home_team_display, m.market_type, m.entity, m.line, m.side, m.sportsbook
