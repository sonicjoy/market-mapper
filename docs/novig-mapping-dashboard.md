# Novig Mapping dashboard — pickers, panels, queries

Datasource `af3tswp5dyuioa` (BigQuery). Tags `["novig","mapping","bigquery","coverage"]`.
All SQL run against `marketmaking-test` on 2026-08-14; numbers are real output.

---

## Pickers

### `project` — CustomVariable
**Label:** Environment (BigQuery project)
**Query:** `PROD : rs-marketmaking,TEST : marketmaking-test`
**Description:** Which BigQuery project every panel reads. Default TEST.

### `window` — CustomVariable
**Label:** Lookback window (days)
**Query:** `3,1,7,14`
**Description:** Lookback for `opticodds_mapping` writeback panels only. Coverage panels always pin to the newest `novig_raw` snapshot and ignore this.

### `novig_league` — QueryVariable (multi, includeAll)
**Label:** Novig league
**Description:** League as Novig reports it, read from the raw feed — so unwired leagues (NCAAF, Serie A, Bundesliga, Ligue 1) stay visible instead of vanishing behind our own tables.
```sql
SELECT DISTINCT JSON_VALUE(data, '$.league') AS novig_league
FROM `${project}.raw_ingestion_us.novig_raw`
WHERE kind = 'markets'
  AND insert_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $window DAY)
ORDER BY 1
```

### `novig_type` — QueryVariable (multi, includeAll)
**Label:** Novig market type
**Description:** Market type as Novig reports it. Use this, not `market_type` — `market_type` is our taxonomy and by definition cannot name a market we failed to map.
```sql
SELECT DISTINCT JSON_VALUE(data, '$.type') AS novig_type
FROM `${project}.raw_ingestion_us.novig_raw`
WHERE kind = 'markets'
  AND insert_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $window DAY)
ORDER BY 1
```

### `sport` / `league` / `market_type` — QueryVariable (multi, includeAll)
**Description:** Our taxonomy, for the inspection panel. Scopes published rows only.
```sql
-- sport
SELECT DISTINCT sport FROM `${project}.markets_us.market_mapping`
WHERE sportsbook='Novig' AND start_date>=TIMESTAMP_SUB(CURRENT_TIMESTAMP(),INTERVAL 2 DAY)
-- league  (append: AND sport IN (${sport:sqlstring}))
-- market_type
```

**Drop from the Polymarket original:** `slug_prefix` (Polymarket-only), `provenance` (means something different here — see panel 10).

---

## Shared CTE

Panels 1–8 all start with this. `latest` pin is mandatory: `novig_raw` appends one snapshot per fetch, so an unpinned query counts every historical snapshot and pushes coverage above 100%.

```sql
WITH latest AS (
  SELECT MAX(insert_time) AS snap FROM `${project}.raw_ingestion_us.novig_raw`
),
legs AS (
  SELECT
    JSON_VALUE(o, '$.id')           AS outcome_id,
    JSON_VALUE(r.data, '$.league')  AS novig_league,
    JSON_VALUE(r.data, '$.type')    AS novig_type,
    JSON_VALUE(r.data, '$.eventId') AS novig_event_id
  FROM `${project}.raw_ingestion_us.novig_raw` AS r,
       latest,
       UNNEST(JSON_QUERY_ARRAY(r.data, '$.outcomes')) AS o
  WHERE r.kind = 'markets' AND r.insert_time = latest.snap
),
published AS (
  SELECT DISTINCT JSON_VALUE(source_ids, '$.selection_id') AS outcome_id
  FROM `${project}.markets_us.market_mapping`
  WHERE sportsbook = 'Novig'
    AND start_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)
),
tok AS (
  SELECT legs.*, p.outcome_id IS NOT NULL AS is_published
  FROM legs LEFT JOIN published AS p USING (outcome_id)
)
```

---

## Panels

### 1. Novig legs — `stat`
**Description:** Every outcome Novig currently quotes, from the newest raw snapshot. The denominator for coverage.
```sql
SELECT COUNT(*) AS novig_legs FROM tok
```
→ `20246`

### 2. Published — `stat`
**Description:** Novig outcomes we publish to `market_mapping`. The numerator.
```sql
SELECT COUNTIF(is_published) AS published FROM tok
```
→ `10079`

### 3. Dark — `stat`
**Description:** Novig quotes it, we don't publish it. Panel 6 splits these by who has to act.
```sql
SELECT COUNTIF(NOT is_published) AS dark FROM tok
```
→ `10167`

### 4. Coverage % — `stat`, unit `percent`, min 0 max 100
**Description:** Published ÷ quoted. Above 100 means the snapshot pin was dropped.
```sql
SELECT ROUND(100 * COUNTIF(is_published) / COUNT(*), 1) AS pct_covered FROM tok
```
→ `49.8`

### 5. Fixtures quoted — `stat`
**Description:** Distinct Novig events with at least one open market. Lower than the fetch's event count — events with no open markets don't appear.
```sql
SELECT COUNT(DISTINCT novig_event_id) AS fixtures FROM tok
```
→ `134`

### 6. Gap ownership — `table`
**Description:** For every dark leg, who acts. `vendor` = we map the type, Optic never priced it → raise with OpticOdds. `ignored by design` = deliberate, see `mappers/leagues/novig_markets.py`. `us (unmapped market type)` = Novig shipped a type our crosswalk lacks → add it. Caveat: `NovigConfig` crosswalks are per-sport but this SQL flattens them, so `ASSISTS` (mapped for basketball, ignored for hockey) can be judged by the wrong sport's rule; `mapped` wins ties, so it under-reports `us`, never invents one. Regenerate both lists from `mappers.run.LEAGUES` when a league is wired.
```sql
-- prepend the shared CTE, plus:
mapped AS (
  SELECT * FROM UNNEST([
    'ASSISTS','BLOCKS','BOTH_TEAMS_TO_SCORE','DOUBLE_DOUBLE','FIRST_GOAL_SCORER',
    'FIRST_INNING_TOTAL','FIRST_SET_MONEYLINE','FOULS','GOALS_ASSISTS','GO_THE_DISTANCE',
    'HITS','HITS_RUNS_RBIS','HOME_RUNS','MONEY','MONEYLINE_3_WAY_DRAW','MONEYLINE_3_WAY_WIN',
    'MONEY_1H','PASSING_YARDS','PITCHER_STRIKEOUTS','PLAYER_GOALS','POINTS','POINTS_ASSISTS',
    'POINTS_REBOUNDS','POINTS_REBOUNDS_ASSISTS','REBOUNDS','REBOUNDS_ASSISTS','SAVES',
    'SET_SPREAD','SHOTS','SHOTS_ON_TARGET','SPREAD','SPREAD_1H','STEALS','STEALS_BLOCKS',
    'TEAM_TOTAL','TEAM_TOTAL_CORNERS','THREE_POINTERS_MADE','TOTAL','TOTAL_1H','TOTAL_BASES',
    'TOTAL_CORNERS','TOTAL_SETS','TRIPLE_DOUBLE','TURNOVERS']) AS t
),
ignored AS (
  SELECT * FROM UNNEST([
    'BATTING_STRIKEOUTS','BATTING_WALKS','DRAW','EARNED_RUNS','FIRST_BASKET',
    'FIRST_TOUCHDOWN_SCORER','HITS_ALLOWED','PITCHER_OUTS','PLAYER_GAMES_WON','RBIS','RUNS',
    'STOLEN_BASES','TOUCHDOWNS','VICTORY_BY_DECISION','VICTORY_BY_KO_KTO_OR_DQ',
    'VICTORY_BY_SUBMISSION','WALKS']) AS t
)
SELECT
  CASE
    WHEN is_published                          THEN 'published'
    WHEN novig_type IN (SELECT t FROM ignored) THEN 'ignored by design'
    WHEN novig_type IN (SELECT t FROM mapped)  THEN 'vendor (optic did not price it)'
    ELSE 'us (unmapped market type)'
  END                        AS owner,
  COUNT(*)                   AS legs,
  COUNT(DISTINCT novig_type) AS distinct_types,
  STRING_AGG(DISTINCT novig_type ORDER BY novig_type LIMIT 12) AS sample_types
FROM tok
GROUP BY owner
ORDER BY legs DESC
```
→ published 10079 · vendor 6871 · ignored 3296 · **us 0**

### 7. Coverage by league — `barchart`, stacking normal, xTickLabelRotation −45
**Description:** Coverage per Novig league. A league missing here is out of season or unlisted, not broken.
```sql
SELECT
  novig_league,
  COUNT(*)                                                     AS novig_legs,
  COUNTIF(is_published)                                        AS published,
  COUNTIF(NOT is_published)                                    AS dark,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(is_published), COUNT(*)), 1) AS pct_covered
FROM tok
GROUP BY novig_league
ORDER BY dark DESC
```
→ MLS 9038/40.6% · MLB 6006/52.6% · WTA 1402/51.8% · ATP 1272/53.5% · WNBA 1136/72.2% · NFL 1168/81.6% · UFC 224/31.3%

### 8. Dark-leg detail — `table`, filterable, paginated, footer countRows
**Description:** One row per unpublished Novig leg, carrying the Optic fixture id and entity id — what a vendor ticket needs. `novig_index` 0 = Home/Over/Yes, 1 = Away/Under/No; never infer side from array order.
```sql
-- shared CTE, plus events; replaces `tok` usage with the join below
events AS (
  SELECT
    JSON_VALUE(r.data, '$.id')             AS novig_event_id,
    JSON_VALUE(r.data, '$.description')    AS event_name,
    JSON_VALUE(r.data, '$.opticOddsId')    AS optic_fixture_id,
    JSON_VALUE(r.data, '$.scheduledStart') AS scheduled_start
  FROM `${project}.raw_ingestion_us.novig_raw` AS r, latest
  WHERE r.kind = 'events' AND r.insert_time = latest.snap
),
detail AS (
  SELECT
    JSON_VALUE(o, '$.id')                        AS outcome_id,
    JSON_VALUE(o, '$.description')               AS outcome_desc,
    SAFE_CAST(JSON_VALUE(o, '$.index') AS INT64) AS novig_index,
    JSON_VALUE(r.data, '$.league')               AS novig_league,
    JSON_VALUE(r.data, '$.type')                 AS novig_type,
    JSON_VALUE(r.data, '$.eventId')              AS novig_event_id,
    SAFE_CAST(JSON_VALUE(r.data, '$.strike') AS FLOAT64) AS strike,
    COALESCE(JSON_VALUE(r.data, '$.player.opticOddsId'),
             JSON_VALUE(r.data, '$.competitor.opticOddsId')) AS optic_entity_id
  FROM `${project}.raw_ingestion_us.novig_raw` AS r,
       latest,
       UNNEST(JSON_QUERY_ARRAY(r.data, '$.outcomes')) AS o
  WHERE r.kind = 'markets' AND r.insert_time = latest.snap
)
SELECT
  d.novig_league, d.novig_type, e.event_name, e.scheduled_start,
  d.outcome_desc, d.novig_index, d.strike,
  e.optic_fixture_id, d.optic_entity_id, d.outcome_id
FROM detail AS d
LEFT JOIN published AS p USING (outcome_id)
LEFT JOIN events    AS e USING (novig_event_id)
WHERE p.outcome_id IS NULL
ORDER BY d.novig_league, e.scheduled_start, d.novig_type
```

### 9. Mapping inspection — `table`, filterable, paginated
**Description:** Spot-check our mapping against Novig's own words. `line` must equal `novig_strike` on every SPREAD/TOTAL row, and `optic_selection` must agree in sense with `novig_outcome` (index 0 ↔ Home/Over/Yes). Disagreement is a real bug.
```sql
WITH cur AS (
  SELECT
    JSON_VALUE(source_ids,'$.selection_id') AS outcome_id,
    sport, league, market_id AS optic_market,
    side, selection, selection_line, line, fixture_id
  FROM `${project}.markets_us.market_mapping`
  WHERE sportsbook = 'Novig'
    AND start_date >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(source_ids,'$.selection_id')
    ORDER BY last_updated DESC) = 1
),
latest AS (
  SELECT MAX(insert_time) AS snap FROM `${project}.raw_ingestion_us.novig_raw`
),
nv AS (
  SELECT
    JSON_VALUE(o, '$.id')                        AS outcome_id,
    JSON_VALUE(o, '$.description')               AS novig_outcome,
    SAFE_CAST(JSON_VALUE(o, '$.index') AS INT64) AS novig_index,
    JSON_VALUE(r.data, '$.type')                 AS novig_type,
    SAFE_CAST(JSON_VALUE(r.data, '$.strike') AS FLOAT64) AS novig_strike
  FROM `${project}.raw_ingestion_us.novig_raw` AS r,
       latest,
       UNNEST(JSON_QUERY_ARRAY(r.data, '$.outcomes')) AS o
  WHERE r.kind = 'markets' AND r.insert_time = latest.snap
),
fx AS (
  SELECT id AS fixture_id, home_team_display, away_team_display, start_date
  FROM `${project}.opticodds_us.opticodds_fixtures`
  WHERE start_date >= TIMESTAMP_SUB(TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY), INTERVAL 2 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY start_date DESC) = 1
)
SELECT
  cur.sport, cur.league, cur.optic_market,
  CONCAT(fx.away_team_display, ' @ ', fx.home_team_display) AS optic_fixture,
  fx.start_date,
  COALESCE(NULLIF(cur.selection,''), cur.side) AS optic_selection,
  cur.selection_line, cur.line,
  nv.novig_type, nv.novig_outcome, nv.novig_index, nv.novig_strike,
  cur.outcome_id
FROM cur
JOIN      nv USING (outcome_id)
LEFT JOIN fx USING (fixture_id)
ORDER BY cur.sport, cur.league, cur.optic_market
```

### 10. Writeback state — `piechart` donut
**Description:** GREG here means "reached `opticodds_mapping` via mmmapper's writeback", which for Novig includes the long-standing Optic passthrough as well as constructed rows — it is NOT this mapper's contribution. `optic native only` is the real backlog: outcomes Optic maps that we don't publish. Counts drift a few hundred between refreshes as the writeback runs; read the ratio, not the absolute.
```sql
WITH prov AS (
  SELECT
    JSON_VALUE(source_ids,'$.selection_id') AS outcome_id,
    LOGICAL_OR(mapping_source = 'GREG')     AS has_greg,
    LOGICAL_OR(mapping_source = 'ORIGINAL') AS has_original
  FROM `${project}.opticodds_us.opticodds_mapping`
  WHERE last_updated >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $window DAY)
    AND sportsbook = 'Novig'
    AND JSON_VALUE(source_ids,'$.selection_id') IS NOT NULL
  GROUP BY outcome_id
)
SELECT
  CASE WHEN has_greg AND NOT has_original THEN 'writeback only'
       WHEN has_original AND NOT has_greg THEN 'optic native only'
       ELSE 'both' END AS writeback_state,
  COUNT(*) AS outcomes
FROM prov
GROUP BY writeback_state
ORDER BY outcomes DESC
```
→ writeback only 18617 · both 6445 · optic native only 494

### 11. Writeback trend (14d) — `timeseries`, timeFrom `15d`
**Description:** Distinct Novig outcomes reaching `opticodds_mapping` per day, by channel. Not a coverage trend — see panel 12.
```sql
SELECT
  TIMESTAMP_TRUNC(last_updated, DAY) AS t,
  CASE mapping_source WHEN 'GREG' THEN 'GREG' ELSE 'ORIGINAL' END AS src,
  COUNT(DISTINCT JSON_VALUE(source_ids,'$.selection_id')) AS outcomes
FROM `${project}.opticodds_us.opticodds_mapping`
WHERE last_updated >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  AND sportsbook = 'Novig'
  AND JSON_VALUE(source_ids,'$.selection_id') IS NOT NULL
GROUP BY t, src
ORDER BY t
```

### 12. Coverage trend — `timeseries`
**Description:** Coverage per raw snapshot. Biased: `published` is evaluated against `market_mapping` as it stands now, not as it stood then, so older points are flattered. Honest as "how much of the book have we ever covered", misleading as a regression detector. Reads as one point until several snapshots exist.
```sql
WITH snaps AS (
  SELECT
    TIMESTAMP_TRUNC(insert_time, HOUR) AS t,
    JSON_VALUE(o, '$.id')              AS outcome_id
  FROM `${project}.raw_ingestion_us.novig_raw` AS r,
       UNNEST(JSON_QUERY_ARRAY(r.data, '$.outcomes')) AS o
  WHERE r.kind = 'markets'
    AND r.insert_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
),
published AS (
  SELECT DISTINCT JSON_VALUE(source_ids,'$.selection_id') AS outcome_id
  FROM `${project}.markets_us.market_mapping`
  WHERE sportsbook = 'Novig'
)
SELECT
  snaps.t,
  COUNT(*)                          AS novig_legs,
  COUNTIF(p.outcome_id IS NOT NULL) AS published,
  ROUND(100*SAFE_DIVIDE(COUNTIF(p.outcome_id IS NOT NULL),COUNT(*)),1) AS pct_covered
FROM snaps LEFT JOIN published AS p USING (outcome_id)
GROUP BY snaps.t
ORDER BY snaps.t
```

---

## Panels to drop from the Polymarket original

13–17 (combinable/in-optic/dark/dark-mappable/dark-unrecognized) → replaced by 1–6.
21 (gap by fixture date) → a distribution, not a trend; use 12.
22 (legs w/o fixture date) → impossible, `scheduledStart` is always present.
8 (net-new forms) → depends on GREG-as-ours; use 6.
11 (optic-only gaps) → folded into 10 as `optic native only`.

---

## `novig_raw` field reference

`kind='events'`: `$.id` · `$.description` (fixture name — **there is no `$.name`**) · `$.league` · `$.scheduledStart` · `$.opticOddsId` (= Optic `fixture_id`) · `$.status` · `$.type`

`kind='markets'`: `$.id` · `$.eventId` · `$.league` · `$.type` · `$.strike` · `$.outcomes[]` → `.id` / `.index` / `.description` · `$.player.opticOddsId` **or** `$.competitor.opticOddsId` (COALESCE — team id sits at market level for TEAM_TOTAL and 3-way, at outcome level for SPREAD and player props)
