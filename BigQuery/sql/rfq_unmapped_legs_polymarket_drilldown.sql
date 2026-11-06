-- Drill-down: top optic-priceable Polymarket true gaps (not in market_mapping).
-- Substitute {project}: marketmaking-test | rs-marketmaking

WITH rfqs AS (
  SELECT external_rfq_id, platform, legs
  FROM `{project}.reporting_us.rfq_latest`
  WHERE last_updated > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 HOUR)
    AND first_publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    AND platform IN ('polymarket', 'polymarket-cashout')
    AND reason IN ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs AS (
  SELECT
    r.platform,
    r.external_rfq_id,
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
    u.platform,
    u.external_rfq_id,
    REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') AS slug_prefix,
    b.slug,
    b.question,
    b.outcome_label,
    -- coarse market shape from slug / question
    CASE
      WHEN b.slug LIKE '%-exact-score-%' OR LOWER(b.question) LIKE 'exact score:%'
        THEN 'exact_score'
      WHEN b.slug LIKE '%corners%' OR LOWER(b.question) LIKE '%corners%'
        THEN 'corners'
      WHEN b.slug LIKE '%-btts%' OR LOWER(b.question) LIKE '%both teams to score%'
        THEN 'btts'
      WHEN b.slug LIKE '%-total-%' OR b.question LIKE '%O/U %'
        THEN 'total'
      WHEN b.slug LIKE '%-spread-%' OR LOWER(b.question) LIKE 'spread:%'
        THEN 'spread'
      WHEN b.slug LIKE '%-team-total-%' OR b.question LIKE '% O/U %'
        THEN 'team_total_or_ou'
      WHEN b.slug LIKE '%doubles%' OR LOWER(b.question) LIKE '%(doubles)%'
        THEN 'doubles'
      WHEN b.slug LIKE '%extra-innings%' OR LOWER(b.question) LIKE '%extra innings%'
        THEN 'extra_innings'
      WHEN b.slug LIKE '%first-five%' OR b.slug LIKE '%-f5-%'
        THEN 'f5'
      WHEN b.slug LIKE '%win-by-%' OR LOWER(b.question) LIKE 'will the fight be won%'
        THEN 'method_of_victory'
      ELSE 'moneyline_or_other'
    END AS market_shape
  FROM unmapped_legs u
  JOIN bridge b ON b.position_id = u.position_id
  LEFT JOIN mapped m ON m.clob_token_id = b.clob_token_id
  WHERE m.clob_token_id IS NULL
    AND REGEXP_EXTRACT(b.slug, r'^([a-z0-9]+)-') IN (
      'mlb', 'nba', 'nfl', 'nhl', 'ncaab', 'wnba',
      'epl', 'fifwc', 'mls', 'mex', 'ucl', 'uel', 'col', 'lec', 'lal', 'arg', 'bra', 'nor', 'clf',
      'atp', 'wta', 'itf', 'ufc', 'cfl',
      'kor', 'kor2', 'swe', 'swe2', 'fin1', 'uslc', 'usl1', 'ecu1', 'nor2',
      'isl1', 'irl1'
    )
)
SELECT
  platform,
  slug_prefix AS league,
  market_shape,
  COUNT(*) AS occ,
  COUNT(DISTINCT slug) AS distinct_slugs,
  COUNT(DISTINCT external_rfq_id) AS distinct_rfqs,
  STRING_AGG(DISTINCT CONCAT(slug, ' | ', IFNULL(question, '')), ' || ' LIMIT 3) AS samples
FROM enriched
GROUP BY platform, slug_prefix, market_shape
ORDER BY occ DESC
LIMIT 100
