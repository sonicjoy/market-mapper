"""Verify Polymarket fixture coverage in markets_us.market_mapping vs opticodds_fixtures."""

import os
import sys

from BigQuery.client import ro_client, ro_query

PROJECT = os.environ.get("GCP_PROJECT", "marketmaking-test")
FIXTURES = f"`{PROJECT}.opticodds_us.opticodds_fixtures`"
MAPPING = f"`{PROJECT}.markets_us.market_mapping`"

COVERAGE_SQL = f"""
WITH optic_fixtures AS (
  SELECT
    game_id,
    id AS fixture_id,
    start_date,
    sport.name AS sport,
    league.name AS league,
    home_team_display,
    away_team_display,
    status
  FROM {FIXTURES}
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
),
poly_mapped_games AS (
  SELECT DISTINCT game_id
  FROM {MAPPING}
  WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
    AND DATE(start_date) BETWEEN CURRENT_DATE()
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  COUNT(*) AS optic_fixture_count,
  COUNTIF(m.game_id IS NOT NULL) AS mapped_fixture_count,
  COUNTIF(m.game_id IS NULL) AS unmapped_fixture_count,
  ROUND(100.0 * COUNTIF(m.game_id IS NOT NULL) / NULLIF(COUNT(*), 0), 1) AS pct_mapped
FROM optic_fixtures o
LEFT JOIN poly_mapped_games m USING (game_id)
"""

UNMAPPED_SQL = f"""
WITH optic_fixtures AS (
  SELECT
    game_id,
    id AS fixture_id,
    start_date,
    sport.name AS sport,
    league.name AS league,
    home_team_display,
    away_team_display,
    status
  FROM {FIXTURES}
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
),
poly_mapped_games AS (
  SELECT DISTINCT game_id
  FROM {MAPPING}
  WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
    AND DATE(start_date) BETWEEN CURRENT_DATE()
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  o.start_date,
  o.sport,
  o.league,
  o.home_team_display,
  o.away_team_display,
  o.status,
  o.game_id
FROM optic_fixtures o
LEFT JOIN poly_mapped_games m USING (game_id)
WHERE m.game_id IS NULL
ORDER BY o.start_date, o.league, o.home_team_display
LIMIT 50
"""

BY_LEAGUE_SQL = f"""
WITH optic_fixtures AS (
  SELECT
    game_id,
    sport.name AS sport,
    league.name AS league
  FROM {FIXTURES}
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
),
poly_mapped_games AS (
  SELECT DISTINCT game_id
  FROM {MAPPING}
  WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
    AND DATE(start_date) BETWEEN CURRENT_DATE()
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  o.sport,
  o.league,
  COUNT(*) AS optic_fixtures,
  COUNTIF(m.game_id IS NOT NULL) AS mapped,
  COUNTIF(m.game_id IS NULL) AS unmapped
FROM optic_fixtures o
LEFT JOIN poly_mapped_games m USING (game_id)
GROUP BY 1, 2
ORDER BY unmapped DESC, optic_fixtures DESC
"""

POLY_STATS_SQL = f"""
SELECT
  sportsbook,
  COUNT(DISTINCT game_id) AS distinct_games,
  COUNT(*) AS mapping_rows,
  MIN(start_date) AS earliest,
  MAX(start_date) AS latest
FROM {MAPPING}
WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
  AND DATE(start_date) BETWEEN CURRENT_DATE()
    AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1
"""

MAPPED_DETAIL_SQL = f"""
SELECT DISTINCT
  m.start_date,
  m.league,
  m.home,
  m.away,
  m.game_id,
  COUNT(*) OVER (PARTITION BY m.game_id) AS poly_rows
FROM {MAPPING} m
WHERE m.sportsbook IN ('Polymarket', 'Polymarket (USA)')
  AND DATE(m.start_date) BETWEEN CURRENT_DATE()
    AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY m.start_date, m.home
"""

PRICE_VS_MAP_SQL = f"""
WITH fixtures AS (
  SELECT game_id
  FROM {FIXTURES}
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
),
poly_prices AS (
  SELECT DISTINCT game_id
  FROM `{PROJECT}.opticodds_us.prices_dedup_state`
  WHERE sportsbook = 'Polymarket'
    AND start_date BETWEEN CURRENT_TIMESTAMP()
      AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
),
mapped AS (
  SELECT DISTINCT game_id
  FROM {MAPPING}
  WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
    AND DATE(start_date) BETWEEN CURRENT_DATE()
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  COUNT(DISTINCT f.game_id) AS fixtures_with_poly_prices,
  COUNT(DISTINCT m.game_id) AS fixtures_mapped_poly,
  COUNT(DISTINCT IF(m.game_id IS NULL, f.game_id, NULL)) AS poly_price_but_unmapped
FROM fixtures f
JOIN poly_prices p USING (game_id)
LEFT JOIN mapped m USING (game_id)
"""

GAP_SQL = f"""
WITH fixtures AS (
  SELECT
    game_id,
    league.name AS league,
    home_team_display,
    away_team_display,
    start_date
  FROM {FIXTURES}
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
    AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY start_date DESC) = 1
),
mapped AS (
  SELECT DISTINCT game_id
  FROM {MAPPING}
  WHERE sportsbook IN ('Polymarket', 'Polymarket (USA)')
    AND DATE(start_date) BETWEEN CURRENT_DATE()
      AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
),
poly_prices AS (
  SELECT DISTINCT game_id
  FROM `{PROJECT}.opticodds_us.prices_dedup_state`
  WHERE sportsbook = 'Polymarket'
    AND start_date BETWEEN CURRENT_TIMESTAMP()
      AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT
  f.start_date,
  f.league,
  f.home_team_display,
  f.away_team_display,
  f.game_id
FROM fixtures f
JOIN poly_prices p USING (game_id)
LEFT JOIN mapped m USING (game_id)
WHERE m.game_id IS NULL
ORDER BY f.start_date
LIMIT 30
"""


def print_rows(title: str, rows) -> None:
    print(f"\n=== {title} ===")
    rows = list(rows)
    if not rows:
        print("(no rows)")
        return
    keys = rows[0].keys()
    print(" | ".join(keys))
    print("-" * 80)
    for row in rows:
        print(" | ".join(str(row[k]).encode("ascii", "replace").decode() for k in keys))


def main() -> None:
    client = ro_client()
    print(f"Project: {client.project}")

    print_rows("Polymarket rows in market_mapping (next 7 days)", ro_query(client, POLY_STATS_SQL))
    print_rows("Mapped Polymarket fixtures (detail)", ro_query(client, MAPPED_DETAIL_SQL))
    print_rows("Fixture coverage summary (all optic fixtures)", ro_query(client, COVERAGE_SQL))
    print_rows("Polymarket prices vs mapping (only fixtures with Optic Polymarket prices)", ro_query(client, PRICE_VS_MAP_SQL))
    print_rows("Coverage by league", ro_query(client, BY_LEAGUE_SQL))
    print_rows("Fixtures with Polymarket prices but no mapping (up to 30)", ro_query(client, GAP_SQL))
    print_rows("Unmapped optic fixtures (up to 50)", ro_query(client, UNMAPPED_SQL))


if __name__ == "__main__":
    main()
