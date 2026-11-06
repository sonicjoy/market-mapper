-- Price coverage for a single fixture, matching the Grafana dashboard logic.
-- Replace @fixture_id with the opticodds_fixtures.id (hex ID).
--
-- Returns one row per (sportsbook × market) combination seen in the
-- last 6 hours, with a count of price rows. Absence of a row means
-- that exchange has no recent prices for that market type on this fixture.

SELECT
  sportsbook,
  market,
  market_id,
  COUNT(*) AS cnt
FROM `rs-marketmaking.opticodds_us.opticodds_prices`
WHERE fixture_id = @fixture_id
  AND DATE(publish_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND publish_time > TIMESTAMP_SECONDS(UNIX_SECONDS(CURRENT_TIMESTAMP()) - 21600)
  AND market_id IN ('total_points', 'point_spread', 'moneyline', 'asian_handicap', 'total_goals')
  AND sportsbook IN ('Kalshi', 'Prophet X')
GROUP BY sportsbook, market, market_id
ORDER BY sportsbook, market
