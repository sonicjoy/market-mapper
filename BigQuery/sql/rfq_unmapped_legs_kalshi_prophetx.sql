-- Cross-platform RFQ unmapped-leg inventory (Kalshi family + ProphetX).
-- Same window + mapping-failure reasons as the coverage dashboard.
-- Kalshi identity: platform_mapping.market_ticker / event_ticker
-- ProphetX identity: platform_mapping.event_id + line_id
-- Substitute {project}: marketmaking-test | rs-marketmaking

WITH rfqs AS (
  SELECT
    external_rfq_id,
    platform,
    reason,
    legs
  FROM `{project}.reporting_us.rfq_latest`
  WHERE last_updated > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 HOUR)
    AND first_publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    AND platform IN (
      'kalshi', 'kalshi-inplay', 'kalshi-inplay-cashout', 'kalshi-cashout',
      'prophetx'
    )
    AND reason IN ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs AS (
  SELECT
    r.platform,
    r.reason,
    r.external_rfq_id,
    JSON_VALUE(l.platform_mapping, '$.market_ticker') AS market_ticker,
    JSON_VALUE(l.platform_mapping, '$.event_ticker') AS event_ticker,
    JSON_VALUE(l.platform_mapping, '$.side') AS kalshi_side,
    JSON_VALUE(l.platform_mapping, '$.event_id') AS px_event_id,
    JSON_VALUE(l.platform_mapping, '$.line_id') AS px_line_id
  FROM rfqs r,
  UNNEST(r.legs) AS l
  WHERE l.optic_fixture_id IS NULL
     OR l.market IS NULL
     OR l.selection IS NULL
),
classified AS (
  SELECT
    u.*,
    -- Longest-prefix first so KXATPCHALLENGER* does not collapse to KXATP
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
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLOL') THEN 'KXLOL'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWC') THEN 'KXWC'
      WHEN u.platform = 'prophetx' THEN 'PROPHETX'
      ELSE REGEXP_EXTRACT(COALESCE(u.event_ticker, u.market_ticker), r'^(KX[A-Z0-9]+)')
    END AS series_prefix,
    CASE
      WHEN u.platform = 'prophetx' THEN 'optic_priceable'
      WHEN STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXATPCHALLENGER')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCONMEBOLSUD')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLEAGUESCUP')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXARGPREMDIV')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXELITESERIEN')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXPERLIGA1')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXODIMATCH')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNCAAMB')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLIGAMX')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLALIGA')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCLUBF')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXBOXING')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCHNSL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXAPFDDH')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXITFW')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNWSL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWNBA')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXLNBP')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXMLS')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXCFL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXUCL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXEPL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXUFC')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNHL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNBA')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNFL')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXMLB')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXATP')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWTA')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXITF')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXNPB')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXKBO')
        OR STARTS_WITH(COALESCE(u.event_ticker, u.market_ticker), 'KXWC')
        THEN 'optic_priceable'
      WHEN COALESCE(u.event_ticker, u.market_ticker) IS NULL
        AND u.platform != 'prophetx' THEN 'no_identity'
      ELSE 'non_optic_expected'
    END AS gap_bucket
  FROM unmapped_legs u
),
kalshi_mapped AS (
  SELECT DISTINCT
    JSON_VALUE(TO_JSON_STRING(source_ids), '$.market_id') AS market_ticker,
    LOWER(JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id')) AS kalshi_side
  FROM `{project}.markets_us.market_mapping`
  WHERE sportsbook = 'Kalshi'
    AND start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),
px_mapped AS (
  SELECT DISTINCT
    JSON_VALUE(TO_JSON_STRING(source_ids), '$.event_id') AS event_id,
    JSON_VALUE(TO_JSON_STRING(source_ids), '$.line_id') AS line_id
  FROM `{project}.markets_us.market_mapping`
  WHERE sportsbook = 'Prophet X'
    AND start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),
enriched AS (
  SELECT
    c.platform,
    c.gap_bucket,
    c.series_prefix,
    CASE
      WHEN c.platform = 'prophetx' THEN pm.event_id IS NOT NULL
      ELSE km.market_ticker IS NOT NULL
    END AS already_in_market_mapping,
    c.external_rfq_id,
    c.market_ticker,
    c.event_ticker,
    c.px_event_id,
    c.px_line_id
  FROM classified c
  -- Join ticker AND side: a mapped Yes does not clear the No of the same
  -- ticker.  Legs with no side in platform_mapping fall back to ticker-only
  -- so they are not reported as fresh true gaps.
  LEFT JOIN kalshi_mapped km
    ON c.platform != 'prophetx'
   AND km.market_ticker = c.market_ticker
   AND (c.kalshi_side IS NULL OR km.kalshi_side = LOWER(c.kalshi_side))
  LEFT JOIN px_mapped pm
    ON c.platform = 'prophetx'
   AND pm.event_id = c.px_event_id
   AND pm.line_id = c.px_line_id
)
SELECT
  platform,
  gap_bucket,
  IFNULL(series_prefix, '(null)') AS series_prefix,
  already_in_market_mapping,
  COUNT(*) AS unmapped_leg_occurrences,
  COUNT(DISTINCT COALESCE(market_ticker, CONCAT(IFNULL(px_event_id, ''), ':', IFNULL(px_line_id, '')))) AS distinct_markets,
  COUNT(DISTINCT COALESCE(event_ticker, px_event_id)) AS distinct_events,
  COUNT(DISTINCT external_rfq_id) AS distinct_rfqs
FROM enriched
GROUP BY platform, gap_bucket, series_prefix, already_in_market_mapping
ORDER BY
  platform,
  CASE gap_bucket
    WHEN 'optic_priceable' THEN 0
    WHEN 'no_identity' THEN 1
    ELSE 2
  END,
  unmapped_leg_occurrences DESC
