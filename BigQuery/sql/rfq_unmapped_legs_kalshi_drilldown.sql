-- Drill-down: top optic-priceable Kalshi true gaps (not in market_mapping).
-- Substitute {project}: marketmaking-test | rs-marketmaking

WITH rfqs AS (
  SELECT external_rfq_id, platform, legs
  FROM `{project}.reporting_us.rfq_latest`
  WHERE last_updated > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 HOUR)
    AND first_publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    AND platform IN (
      'kalshi', 'kalshi-inplay', 'kalshi-inplay-cashout', 'kalshi-cashout'
    )
    AND reason IN ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs AS (
  SELECT
    r.platform,
    r.external_rfq_id,
    JSON_VALUE(l.platform_mapping, '$.market_ticker') AS market_ticker,
    JSON_VALUE(l.platform_mapping, '$.event_ticker') AS event_ticker,
    JSON_VALUE(l.platform_mapping, '$.side') AS kalshi_side
  FROM rfqs r, UNNEST(r.legs) AS l
  WHERE l.optic_fixture_id IS NULL OR l.market IS NULL OR l.selection IS NULL
),
classified AS (
  SELECT
    u.*,
    CASE
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXATPCHALLENGER') THEN 'KXATPCHALLENGER'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCONMEBOLSUD') THEN 'KXCONMEBOLSUD'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLEAGUESCUP') THEN 'KXLEAGUESCUP'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXARGPREMDIV') THEN 'KXARGPREMDIV'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXELITESERIEN') THEN 'KXELITESERIEN'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXPERLIGA1') THEN 'KXPERLIGA1'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXODIMATCH') THEN 'KXODIMATCH'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNCAAMB') THEN 'KXNCAAMB'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLIGAMX') THEN 'KXLIGAMX'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLALIGA') THEN 'KXLALIGA'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCLUBF') THEN 'KXCLUBF'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXBOXING') THEN 'KXBOXING'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCHNSL') THEN 'KXCHNSL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXAPFDDH') THEN 'KXAPFDDH'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXITFW') THEN 'KXITFW'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNWSL') THEN 'KXNWSL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWNBA') THEN 'KXWNBA'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLNBP') THEN 'KXLNBP'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXMLS') THEN 'KXMLS'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCFL') THEN 'KXCFL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXUCL') THEN 'KXUCL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXEPL') THEN 'KXEPL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXUFC') THEN 'KXUFC'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNHL') THEN 'KXNHL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNBA') THEN 'KXNBA'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNFL') THEN 'KXNFL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXMLB') THEN 'KXMLB'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXATP') THEN 'KXATP'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWTA') THEN 'KXWTA'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXITF') THEN 'KXITF'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNPB') THEN 'KXNPB'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXKBO') THEN 'KXKBO'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWC') THEN 'KXWC'
      ELSE REGEXP_EXTRACT(COALESCE(u.event_ticker, u.market_ticker), r'^(KX[A-Z0-9]+)')
    END AS series_prefix,
    CASE
      WHEN u.market_ticker LIKE '%SPREAD%' OR u.event_ticker LIKE '%SPREAD%' THEN 'spread'
      WHEN u.market_ticker LIKE '%TOTAL%' OR u.event_ticker LIKE '%TOTAL%' THEN 'total'
      WHEN u.market_ticker LIKE '%BTTS%' OR u.event_ticker LIKE '%BTTS%' THEN 'btts'
      WHEN u.market_ticker LIKE '%MOV%' OR u.event_ticker LIKE '%MOV%' THEN 'method_of_victory'
      WHEN u.market_ticker LIKE '%GAME%' OR u.event_ticker LIKE '%GAME%' THEN 'game_moneyline'
      WHEN u.market_ticker LIKE '%MATCH%' OR u.event_ticker LIKE '%MATCH%' THEN 'match_moneyline'
      WHEN u.market_ticker LIKE '%FIGHT%' OR u.event_ticker LIKE '%FIGHT%' THEN 'fight_moneyline'
      ELSE 'other'
    END AS market_shape
  FROM unmapped_legs u
),
mapped AS (
  SELECT DISTINCT
    JSON_VALUE(TO_JSON_STRING(source_ids), '$.market_id') AS market_ticker,
    LOWER(JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id')) AS kalshi_side
  FROM `{project}.markets_us.market_mapping`
  WHERE sportsbook = 'Kalshi'
    AND start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),
optic AS (
  SELECT c.*
  FROM classified c
  -- Join ticker AND side: a mapped Yes does not clear the No of the same
  -- ticker.  Legs with no side in platform_mapping fall back to ticker-only
  -- so they are not reported as fresh true gaps.
  LEFT JOIN mapped m
    ON m.market_ticker = c.market_ticker
   AND (c.kalshi_side IS NULL OR m.kalshi_side = LOWER(c.kalshi_side))
  WHERE m.market_ticker IS NULL
    AND c.series_prefix IN (
      'KXATPCHALLENGER', 'KXCONMEBOLSUD', 'KXLEAGUESCUP', 'KXARGPREMDIV',
      'KXELITESERIEN', 'KXPERLIGA1', 'KXODIMATCH', 'KXNCAAMB', 'KXLIGAMX',
      'KXLALIGA', 'KXCLUBF', 'KXBOXING', 'KXCHNSL', 'KXAPFDDH', 'KXITFW',
      'KXNWSL', 'KXWNBA', 'KXLNBP', 'KXMLS', 'KXCFL', 'KXUCL', 'KXEPL',
      'KXUFC', 'KXNHL', 'KXNBA', 'KXNFL', 'KXMLB', 'KXATP', 'KXWTA',
      'KXITF', 'KXNPB', 'KXKBO', 'KXWC'
    )
)
SELECT
  platform,
  series_prefix AS league,
  market_shape,
  COUNT(*) AS occ,
  COUNT(DISTINCT market_ticker) AS distinct_markets,
  COUNT(DISTINCT event_ticker) AS distinct_events,
  COUNT(DISTINCT external_rfq_id) AS distinct_rfqs,
  STRING_AGG(DISTINCT CONCAT(IFNULL(event_ticker, ''), ' / ', IFNULL(market_ticker, '')), ' || ' LIMIT 5)
    AS samples
FROM optic
GROUP BY platform, series_prefix, market_shape
ORDER BY occ DESC
LIMIT 100
