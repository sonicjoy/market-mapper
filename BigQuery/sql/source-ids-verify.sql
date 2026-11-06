-- Verify that our exchange mappings agree with Optic's source_ids.
--
-- Joins greg_sandbox.market_mapping against prices_dedup_state,
-- matching on sportsbook (each market_mapping row is now one exchange).
-- Classifies every mapped row as:
--   match    — our source_ids equals Optic's source_ids
--   mismatch — our source_ids disagrees (needs investigation)
--   novel    — Optic has no source_ids; our mapping is new value
--
-- ~11 MB scan (essentially free).

SELECT
  m.sportsbook,
  CASE
    WHEN p.source_ids IS NULL THEN "novel"
    WHEN TO_JSON_STRING(m.source_ids) = TO_JSON_STRING(p.source_ids) THEN "match"
    ELSE "mismatch"
  END AS status,
  COUNT(*) AS n
FROM greg_sandbox.market_mapping m
LEFT JOIN opticodds_us.prices_dedup_state p
  ON  m.game_id = p.game_id
  AND m.market_id = p.market_id
  AND m.selection = p.selection
  AND m.selection_line = p.selection_line
  AND m.points = p.points
  AND m.sportsbook = p.sportsbook
GROUP BY 1, 2
ORDER BY 1, 2
