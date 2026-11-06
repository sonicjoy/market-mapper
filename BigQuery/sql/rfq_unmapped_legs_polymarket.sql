-- RFQ unmapped-leg inventory for Polymarket (optic-priceable mission).
-- Same time window as the coverage dashboard; mapping-failure reasons only.
-- RFQ platform_mapping.token_id is the Polymarket position_id (not clob).
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
    AND platform IN ('polymarket', 'polymarket-cashout')
    AND reason IN ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs AS (
  SELECT
    r.platform,
    r.reason,
    r.external_rfq_id,
    JSON_VALUE(l.platform_mapping, '$.token_id') AS position_id,
    JSON_VALUE(l.platform_mapping, '$.condition_id') AS condition_id,
    JSON_VALUE(l.platform_mapping, '$.side') AS pm_side
  FROM rfqs r,
  UNNEST(r.legs) AS l
  WHERE l.optic_fixture_id IS NULL
     OR l.market IS NULL
     OR l.selection IS NULL
),
bridge AS (
  SELECT
    position_id,
    ANY_VALUE(clob_token_id) AS clob_token_id,
    ANY_VALUE(slug) AS slug,
    ANY_VALUE(question) AS question,
    ANY_VALUE(outcome_label) AS outcome_label,
    ANY_VALUE(game_start_time) AS game_start_time
  FROM `{project}.raw_ingestion_us.polymarket_position_token_bridge`
  WHERE last_updated > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  GROUP BY position_id
),
mapped AS (
  SELECT DISTINCT
    JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id') AS clob_token_id
  FROM `{project}.markets_us.market_mapping`
  WHERE sportsbook = 'Polymarket'
    AND start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),
enriched AS (
  SELECT
    u.platform,
    u.reason,
    u.external_rfq_id,
    u.position_id,
    u.condition_id,
    b.clob_token_id,
    b.slug,
    b.question,
    b.outcome_label,
    REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') AS slug_prefix,
    m.clob_token_id IS NOT NULL AS already_in_market_mapping,
    CASE
      WHEN b.slug IS NULL THEN 'no_bridge'
      WHEN REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') IN (
        -- majors + wired soccer / tennis / combat
        'mlb', 'nba', 'nfl', 'nhl', 'ncaab', 'wnba',
        'epl', 'fifwc', 'mls', 'mex', 'ucl', 'uel', 'col', 'lec', 'lal', 'arg', 'bra', 'nor', 'clf',
        'atp', 'wta', 'itf', 'ufc', 'cfl',
        -- soccer_expansion (BQ-optic + poly)
        'kor', 'kor2', 'swe', 'swe2', 'fin1', 'uslc', 'usl1', 'ecu1', 'nor2',
        'isl1', 'irl1'
      ) THEN 'optic_priceable'
      ELSE 'non_optic_expected'
    END AS gap_bucket
  FROM unmapped_legs u
  LEFT JOIN bridge b ON b.position_id = u.position_id
  LEFT JOIN mapped m ON m.clob_token_id = b.clob_token_id
)
SELECT
  platform,
  gap_bucket,
  IFNULL(slug_prefix, '(null)') AS slug_prefix,
  already_in_market_mapping,
  COUNT(*) AS unmapped_leg_occurrences,
  COUNT(DISTINCT position_id) AS distinct_positions,
  COUNT(DISTINCT clob_token_id) AS distinct_clobs,
  COUNT(DISTINCT condition_id) AS distinct_conditions,
  COUNT(DISTINCT external_rfq_id) AS distinct_rfqs
FROM enriched
GROUP BY platform, gap_bucket, slug_prefix, already_in_market_mapping
ORDER BY
  platform,
  CASE gap_bucket
    WHEN 'optic_priceable' THEN 0
    WHEN 'no_bridge' THEN 1
    ELSE 2
  END,
  unmapped_leg_occurrences DESC
