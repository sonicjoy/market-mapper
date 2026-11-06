-- Sample questions for top optic-priceable Polymarket unmapped legs.
-- Substitute {project}

WITH rfqs AS (
  SELECT external_rfq_id, platform, legs
  FROM `{project}.reporting_us.rfq_latest`
  WHERE last_updated > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 HOUR)
    AND first_publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    AND platform = 'polymarket'
    AND reason IN ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs AS (
  SELECT
    JSON_VALUE(l.platform_mapping, '$.token_id') AS position_id
  FROM rfqs r, UNNEST(r.legs) AS l
  WHERE l.optic_fixture_id IS NULL OR l.market IS NULL OR l.selection IS NULL
),
bridge AS (
  SELECT
    position_id,
    ANY_VALUE(clob_token_id) AS clob_token_id,
    ANY_VALUE(slug) AS slug,
    ANY_VALUE(question) AS question,
    ANY_VALUE(outcome_label) AS outcome_label
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
    REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') AS slug_prefix,
    b.slug,
    b.question,
    b.outcome_label,
    m.clob_token_id IS NOT NULL AS already_in_market_mapping,
    COUNT(*) AS occ
  FROM unmapped_legs u
  JOIN bridge b ON b.position_id = u.position_id
  LEFT JOIN mapped m ON m.clob_token_id = b.clob_token_id
  WHERE REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') IN (
    'ucl', 'uel', 'col', 'lec', 'clf', 'epl', 'itf', 'atp', 'nor', 'lal', 'arg', 'mex', 'ufc', 'mlb', 'mls', 'nfl',
    'kor', 'kor2', 'swe', 'swe2', 'fin1', 'uslc', 'usl1', 'ecu1', 'nor2', 'isl1', 'irl1',
    'wnba', 'wta', 'cfl', 'bra'
  )
  GROUP BY 1, 2, 3, 4, 5
)
SELECT * FROM enriched
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY slug_prefix, already_in_market_mapping
  ORDER BY occ DESC
) <= 5
ORDER BY slug_prefix, already_in_market_mapping, occ DESC
