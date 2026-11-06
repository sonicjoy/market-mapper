# Grafana spec — AI mapping validation

Panel-by-panel spec for a dashboard over `markets_us.market_mapping_ai_validation`
(written by `BigQuery/ai_validation.py`; see `docs/ai-validation.md`). The queries
are copy-paste ready; the dashboard JSON itself belongs in
`mm-infrastructure/dashboards/trading/mapping_ai_validation.json`.

**Panel 1 is the point of the dashboard**: every uncertain mapping on a fixture
that has not started yet — the queue you work before those markets trade.

## Conventions (mm-infrastructure)

- **v2 ("v13") schema** — top-level `elements` + `layout`, no `schemaVersion`.
  rawSql lives at
  `elements["panel-N"].spec.data.spec.queries[0].spec.query.spec.rawSql`;
  a mislocated query is silently dropped by the loader.
- BQ datasource type `grafana-bigquery-datasource`, each panel's
  `query.datasource.name = "${datasource}"`.
- `datasource` is a CustomVariable labelled `Environment`:
  `Test : affp9dbswmdxcd,Production : bfaqzgj5o4bnke`.
- Multi-value variables go through `:sqlstring` (never a bare `'${var}'`).
- Upload: `mm-infrastructure/dashboards/upload-dashboard.sh mapping_ai_validation.json "Trading Dashboards"`.

### Variables

| Name | Kind | Definition |
|---|---|---|
| `datasource` | Custom | `Test : affp9dbswmdxcd,Production : bfaqzgj5o4bnke` |
| `sportsbook` | Query, multi, include-all | `SELECT DISTINCT sportsbook FROM markets_us.market_mapping_ai_validation WHERE start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY) ORDER BY 1` |
| `league` | Query, multi, include-all | `SELECT DISTINCT league FROM markets_us.market_mapping_ai_validation WHERE start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY) ORDER BY 1` |
| `prompt_version` | Query, single | `SELECT DISTINCT CAST(prompt_version AS STRING) FROM markets_us.market_mapping_ai_validation ORDER BY 1 DESC` |

Every query keeps an explicit `start_date` bound: the table is DAY-partitioned on
`start_date`, so an unbounded scan is both slow and needless.

**While a run is in progress**, pinning `prompt_version` to the newest value shows
only the slice already re-judged — the MERGE key is `row_fingerprint` alone, so
rows move to the new version one batch at a time. An exchange with fewer rows
finishes sooner, not later (batches interleave), but a panel can still look
short-changed until the run's final flush. Check `judged N/M batches` in
`logs/ai_validation.log`, or select the previous `prompt_version`, before
concluding data is missing.

**Seeing nothing at all?** Check the `Environment` dropdown. The verdict table
currently exists only in **Test** (`marketmaking-test`); Production has no
`markets_us.market_mapping_ai_validation` until the job is deployed there.

---

## Panel 1 — Uncertain mappings, upcoming fixtures (table, full width, top)

The review queue. Soonest kickoff first, because that is the row that trades next.
**Deliberately ignores the dashboard time picker** — "upcoming" is always
`now → +14d`, whatever range is selected. A flag means *look at it*, not
*definitely wrong*: uncertainty resolves to pass in the prompt, so what lands here
is a nameable contradiction the model could articulate.

```sql
SELECT
  start_date,
  sportsbook,
  league,
  fixture_name,
  market_type,
  side,
  line,
  points,
  ARRAY_TO_STRING(
    ARRAY(
      SELECT c FROM UNNEST([
        IF(fixture_ok = FALSE, 'fixture', NULL),
        IF(entity_ok  = FALSE, 'player',  NULL),
        IF(market_ok  = FALSE, 'market',  NULL),
        IF(side_ok    = FALSE, 'side',    NULL),
        IF(line_ok    = FALSE, 'line',    NULL)
      ]) AS c WHERE c IS NOT NULL
    ), ', '
  ) AS failed,
  reason,
  exchange_ref,
  exchange_side,
  exchange_text,
  game_id,
  market_id,
  selection,
  selection_line,
  validated_at
FROM `markets_us.market_mapping_ai_validation`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  AND prompt_version = ${prompt_version}
  AND NOT mapping_ok
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
ORDER BY start_date, sportsbook, league
```

Panel options: table, `start_date` as time, `reason` + `exchange_text` wide enough
to read without hovering. Colour `failed` by value if you want the polarity bugs
(`side`) to jump out from the threshold ones (`line`).

## Panel 2 — Flags by failed check (bar gauge, beside panel 1)

Where the errors cluster. `side` heavy = a polarity bug class; `line` heavy = a
threshold/encoding one; `fixture` heavy = usually a date or alias problem, and if
it spikes across every league suspect the timezone rule in the prompt before the
matcher.

```sql
SELECT check_name, sportsbook, COUNT(*) AS flags
FROM `markets_us.market_mapping_ai_validation`,
     UNNEST([
       STRUCT('fixture' AS check_name, fixture_ok AS ok),
       STRUCT('player',  entity_ok),
       STRUCT('market',  market_ok),
       STRUCT('side',    side_ok),
       STRUCT('line',    line_ok)
     ]) AS c
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  AND prompt_version = ${prompt_version}
  AND c.ok = FALSE
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
GROUP BY check_name, sportsbook
ORDER BY flags DESC
```

## Panel 3 — Review coverage: judged vs unjudged, upcoming (table)

How much of what we publish has actually been looked at. `unjudged` is normal
right after a `PROMPT_VERSION` bump (everything re-enters the queue) and should
drain within a cron cycle or two; a bucket that never drains is the signal —
usually rows the job skips for missing exchange text (see `docs/ai-validation.md`).

The fingerprint expression below must stay in lockstep with `_fingerprint_expr()`
in `BigQuery/ai_validation.py` (it is derived there from
`load_mappings.KEY_COLUMNS`). If a key column is added to `market_mapping`, add it
here too or this panel silently under-reports.

```sql
WITH map AS (
  SELECT
    sportsbook, league,
    TO_HEX(SHA256(ARRAY_TO_STRING([
      IFNULL(sport, ''), IFNULL(league, ''),
      CAST(UNIX_MILLIS(start_date) AS STRING),
      IFNULL(home, ''), IFNULL(away, ''), IFNULL(market_type, ''),
      IFNULL(entity, ''), IFNULL(FORMAT('%.4f', line), ''),
      IFNULL(side, ''), IFNULL(group_key, ''), IFNULL(sportsbook, ''),
      IFNULL(TO_JSON_STRING(source_ids), '')
    ], '|'))) AS row_fingerprint
  FROM `markets_us.market_mapping`
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                       AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
    AND sportsbook IN ('Kalshi', 'Polymarket', 'crypto.com', 'Novig')
), v AS (
  SELECT row_fingerprint, mapping_ok
  FROM `markets_us.market_mapping_ai_validation`
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                       AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
    AND prompt_version = ${prompt_version}
)
SELECT
  m.sportsbook,
  m.league,
  COUNT(*)                                        AS mappings,
  COUNTIF(v.row_fingerprint IS NULL)              AS unjudged,
  COUNTIF(v.mapping_ok)                           AS passed,
  COUNTIF(v.mapping_ok = FALSE)                   AS flagged,
  ROUND(100 * COUNTIF(v.mapping_ok = FALSE)
        / NULLIF(COUNTIF(v.row_fingerprint IS NOT NULL), 0), 1) AS flag_pct
FROM map m
LEFT JOIN v USING (row_fingerprint)
WHERE m.sportsbook IN (${sportsbook:sqlstring})
  AND m.league IN (${league:sqlstring})
GROUP BY m.sportsbook, m.league
ORDER BY flagged DESC, mappings DESC
```

## Panel 4 — Flag rate over time (timeseries, by sportsbook)

Uses the dashboard time picker (unlike panels 1–3) so a prompt change or a matcher
fix shows up as a step. Bucketed on fixture day, not `validated_at`: a mapping is
judged once, so the fixture day is the stable x-axis.

```sql
SELECT
  TIMESTAMP_TRUNC(start_date, DAY) AS time,
  sportsbook,
  ROUND(100 * COUNTIF(NOT mapping_ok) / COUNT(*), 2) AS flag_pct
FROM `markets_us.market_mapping_ai_validation`
WHERE $__timeFilter(start_date)
  AND prompt_version = ${prompt_version}
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
GROUP BY time, sportsbook
ORDER BY time
```

## Panel 5 — Judge freshness (stat row)

Three stats, to catch "the cron died and the queue looks clean because nothing was
judged":

```sql
SELECT
  COUNT(*)                                                            AS verdicts_14d,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(validated_at), MINUTE)      AS mins_since_last_verdict,
  COUNT(DISTINCT model)                                               AS models_in_play
FROM `markets_us.market_mapping_ai_validation`
WHERE start_date BETWEEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  AND prompt_version = ${prompt_version}
```

Thresholds: `mins_since_last_verdict` amber > 180 (the cron runs every 2h, so
~120 min between runs is normal — amber is one and a half missed runs), red > 360
(three missed runs). `models_in_play` > 1 means a run used a
different Gemini model — fine, but worth knowing when comparing flag rates.

## Panel 6 — Flagged history for one exchange id (table, collapsed row)

For chasing a specific ticker/token/symbol after an override: paste it into the
`ref` variable (textbox) and see every verdict recorded for it.

```sql
SELECT validated_at, start_date, sportsbook, league, fixture_name, market_type,
       side, line, points, mapping_ok, fixture_ok, market_ok, side_ok, line_ok,
       entity_ok, reason, exchange_text, prompt_version, model
FROM `markets_us.market_mapping_ai_validation`
WHERE start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND exchange_ref = '${ref}'
ORDER BY validated_at DESC
```

---

## What Panel 1 shows today

Verified against `marketmaking-test` on 2026-08-03, prompt v1, 3,869 verdicts over
`today → +14d` (Kalshi 412, Polymarket 2,849, crypto.com 608): **Panel 1 is
empty**. The run's only 3 flags were crypto.com `point_spread` rows on a fixture
that had already kicked off, so they fall outside the upcoming window — and they
are false positives of the intermittent spread-polarity class documented in
`docs/ai-validation.md`.

So the expected steady state of this panel is "empty, or a handful of spread rows".
If it fills with something else, that is new signal — work it.

## Reading the dashboard

1. **Panel 1 non-empty** → work it top-down; the soonest fixture is the one that
   trades first. Cross-check a row with `mappers/eyeball.py` before touching the
   matcher — the fix is usually an alias or vocab change in code
   (`mappers/vocab/`, `mappers/exchanges/`, with a test and the
   `regression:mapping-gate` delta), not a scoring change.
2. **A whole league or market type flagged the same way** → suspect a convention,
   a join, or an unjudgeable input field on our side, not N bugs. All five classes
   found so far were ours: US-Eastern vs UTC dates, winner-anchored correct-score
   vs home–away, a fixture name lost to a window filter, Kalshi titles describing
   the YES side, and Polymarket slug dates set by local tournament day. See
   "False-positive classes already fixed" in `docs/ai-validation.md` before
   editing the matcher.
   Note that `mapping_ok` is **derived** from the component verdicts, so a row in
   Panel 1 always has at least one failing component in `failed`.
3. **Panel 3 `unjudged` stuck > 0** → the job is skipping those rows, almost
   always missing exchange text upstream (stale `kalshi_raw` stash, token absent
   from the Polymarket bridge, symbol absent from the crypto catalogue).
4. **Panel 1 empty and panel 5 stale** → nothing was judged; check
   `logs/ai_validation.log` on the VM before believing the mappings are clean.
