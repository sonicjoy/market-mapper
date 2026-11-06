-- Missing league×exchange coverage scan (RFQ / all-exchanges rule).
-- Run after: gcloud auth login (or ADC refresh).
-- Horizon: next 14 days published rows vs shadow tip configured exchanges.
--
-- COW: a P_* (or any candidate) rule_set_id is a delta layer, not a full
-- snapshot. Walk tip→root and last-write-wins per league before UNNEST.
-- The depth guard matches BigQuery's own 500-iteration ceiling; a lower cap
-- silently truncates the lineage and under-reports what the tip actually maps.

WITH RECURSIVE
lineage AS (
  SELECT rule_set_id, parent_rule_set_id, created_at, 0 AS depth
  FROM (
    SELECT rule_set_id, parent_rule_set_id, created_at
    FROM `{project}.markets_us.mapping_rule_sets`
    ORDER BY created_at DESC
    LIMIT 1
  )
  UNION ALL
  SELECT s.rule_set_id, s.parent_rule_set_id, s.created_at, lineage.depth + 1
  FROM `{project}.markets_us.mapping_rule_sets` AS s
  INNER JOIN lineage
    ON s.rule_set_id = lineage.parent_rule_set_id
  WHERE lineage.depth < 500
),
ranked_leagues AS (
  SELECT
    l.league,
    l.sport,
    l.exchanges,
    IFNULL(l.tombstone, FALSE) AS tombstone,
    ROW_NUMBER() OVER (PARTITION BY l.league ORDER BY lin.depth) AS rn
  FROM `{project}.markets_us.mapping_leagues` AS l
  INNER JOIN lineage AS lin USING (rule_set_id)
),
configured AS (
  SELECT
    lg.league,
    lg.sport,
    CASE e.sportsbook
      WHEN 'kalshi' THEN 'Kalshi'
      WHEN 'px' THEN 'Prophet X'
      WHEN 'crypto.com' THEN 'crypto.com'
      WHEN 'polymarket' THEN 'Polymarket'
    END AS sportsbook
  FROM ranked_leagues AS lg,
  UNNEST(lg.exchanges) AS e
  WHERE lg.rn = 1
    AND lg.tombstone = FALSE
    AND e.sportsbook IN ('kalshi', 'px', 'crypto.com', 'polymarket')
),
published AS (
  SELECT sportsbook, league, COUNT(*) AS rows_14d
  FROM `{project}.markets_us.market_mapping`
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                       AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
    AND sportsbook IN ('Kalshi', 'Polymarket', 'crypto.com', 'Prophet X')
  GROUP BY 1, 2
),
rollup AS (
  SELECT
    COALESCE(c.league, p.league) AS league,
    ANY_VALUE(c.sport) AS sport,
    MAX(IF(c.sportsbook = 'Kalshi', 1, 0)) AS cfg_kalshi,
    MAX(IF(c.sportsbook = 'Polymarket', 1, 0)) AS cfg_poly,
    MAX(IF(c.sportsbook = 'Prophet X', 1, 0)) AS cfg_px,
    MAX(IF(c.sportsbook = 'crypto.com', 1, 0)) AS cfg_crypto,
    IFNULL(MAX(IF(p.sportsbook = 'Kalshi', p.rows_14d, NULL)), 0) AS pub_kalshi,
    IFNULL(MAX(IF(p.sportsbook = 'Polymarket', p.rows_14d, NULL)), 0) AS pub_poly,
    IFNULL(MAX(IF(p.sportsbook = 'Prophet X', p.rows_14d, NULL)), 0) AS pub_px,
    IFNULL(MAX(IF(p.sportsbook = 'crypto.com', p.rows_14d, NULL)), 0) AS pub_crypto
  FROM configured c
  FULL OUTER JOIN published p
    ON p.league = c.league AND p.sportsbook = c.sportsbook
  GROUP BY 1
)
SELECT
  league,
  sport,
  cfg_kalshi, cfg_poly, cfg_px, cfg_crypto,
  pub_kalshi, pub_poly, pub_px, pub_crypto,
  -- configured but no published rows in horizon
  CASE
    WHEN cfg_kalshi = 1 AND pub_kalshi = 0 THEN 'Kalshi'
    ELSE NULL
  END AS gap_kalshi,
  CASE WHEN cfg_poly = 1 AND pub_poly = 0 THEN 'Polymarket' ELSE NULL END AS gap_poly,
  CASE WHEN cfg_px = 1 AND pub_px = 0 THEN 'Prophet X' ELSE NULL END AS gap_px,
  CASE WHEN cfg_crypto = 1 AND pub_crypto = 0 THEN 'crypto.com' ELSE NULL END AS gap_crypto
FROM rollup
ORDER BY (pub_kalshi + pub_poly + pub_px + pub_crypto) DESC, league
