# Grafana spec — mapping coverage (platforms × leagues)

Panel-by-panel SQL for a dashboard over published mappings in
`markets_us.market_mapping`, with a **configured-vs-published gap** panel that
reads the latest seed tip from `markets_us.mapping_leagues` /
`mapping_rule_sets`.

The dashboard JSON itself belongs in
`mm-infrastructure/dashboards/trading/mapping_coverage.json` (not in this repo).
This file is the copy-paste source of truth for panel SQL.

**Tip debt.** Panels 4 and 5 read the retiring BigQuery tip
(`mapping_leagues` / `mapping_rule_sets`). They show legacy wiring only and
go when the tip goes (see `CLAUDE.md`). Leagues wired in code
(`VENUE_TOKEN_BY_SLUG`, `SLUG_BY_LEAGUE_ID`, `UNDERDOG_LEAGUE_SLUGS`,
`NOVIG_LEAGUE_NAMES`; see `with_code_*` in `mappers/seed/tip_factories.py`)
do not appear in the tip, so Panel 4 cannot judge them. Never fix a Panel 4
gap by seeding or activating a tip.

**Related:** AI quality over the same mappings → `docs/ai-validation-grafana.md`.
Rule-table status → `docs/mapping-rules/m1-status.md`.

## What to query (and what not to)

| Table | Use on this dashboard |
|---|---|
| `markets_us.market_mapping` | Live published row counts by `sportsbook` × `league` |
| `markets_us.mapping_rule_sets` + `mapping_leagues` | Latest **seed** tip: which leagues / matcher platforms are configured |
| `markets_us.mapping_rule_current` | **Do not use** for this dashboard — coverage is seed-vs-published, not the served tip |
| `markets_us.market_mapping_ai_validation` | Out of scope here (AI validation dashboard) |

Gap panels mean “configured in the latest **seed** tip, but no published rows
in the horizon.” That is not the served tip. Classify uses the **activated**
BQ tip when `MAPPING_SOT=bq`.

### Config key → published `sportsbook`

`mapping_leagues.exchanges[].sportsbook` uses seed keys. Map them before joining
`market_mapping`:

| Config key | `market_mapping.sportsbook` |
|---|---|
| `kalshi` | `Kalshi` |
| `px` | `Prophet X` |
| `crypto.com` | `crypto.com` |
| `polymarket` | `Polymarket` |
| `runshop` | `Runshop` |
| `optic` | *(not a published sportsbook — skip)* |

Optic passthrough books that appear only in `market_mapping`
(`Polymarket (USA)`, `Novig`, `SX Bet`, `DraftKings`, …) are **not** listed as
separate exchanges on `mapping_leagues`. They show up in inventory panels but
are excluded from the configured-vs-published gap (no config key to join).

## Conventions (mm-infrastructure)

Same as `docs/ai-validation-grafana.md`:

- **v2 ("v13") schema** — top-level `elements` + `layout`; rawSql at
  `elements["panel-N"].spec.data.spec.queries[0].spec.query.spec.rawSql`.
- BQ datasource type `grafana-bigquery-datasource`,
  `query.datasource.name = "${datasource}"`.
- `datasource` CustomVariable labelled `Environment`:
  `Test : affp9dbswmdxcd,Production : bfaqzgj5o4bnke`.
- Multi-value variables through `:sqlstring` (never bare `'${var}'`).
- Upload:
  `mm-infrastructure/dashboards/upload-dashboard.sh mapping_coverage.json "Trading Dashboards"`.

### Variables

| Name | Kind | Definition |
|---|---|---|
| `datasource` | Custom | `Test : affp9dbswmdxcd,Production : bfaqzgj5o4bnke` |
| `sportsbook` | Query, multi, include-all | see below |
| `league` | Query, multi, include-all | see below |
| `horizon_days` | Custom | `14 : 14,30 : 30,90 : 90` (default `14`) |

**sportsbook variable**

```sql
SELECT DISTINCT sportsbook
FROM `markets_us.market_mapping`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
ORDER BY 1
```

**league variable**

```sql
SELECT DISTINCT league
FROM `markets_us.market_mapping`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
ORDER BY 1
```

Every inventory query keeps an explicit `start_date` bound: the table is
DAY-partitioned on `start_date`, so an unbounded scan is both slow and needless.

Panels 1–4 deliberately ignore the dashboard time picker and use
`now → +${horizon_days}` (same idea as AI validation Panel 1). Seasonal
off-leagues (nba / nhl / epl / world_cup, …) correctly show as gaps when the
horizon has no fixtures.

---

## Panel 1 — Rows by platform (bar / table)

```sql
SELECT
  sportsbook,
  COUNT(*) AS mapping_rows,
  COUNT(DISTINCT league) AS leagues,
  COUNT(DISTINCT game_id) AS distinct_games
FROM `markets_us.market_mapping`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
GROUP BY sportsbook
ORDER BY mapping_rows DESC
```

---

## Panel 2 — Rows by league (table)

```sql
SELECT
  league,
  sport,
  COUNT(*) AS mapping_rows,
  COUNT(DISTINCT sportsbook) AS sportsbooks,
  STRING_AGG(DISTINCT sportsbook ORDER BY sportsbook) AS sportsbook_list,
  COUNT(DISTINCT game_id) AS distinct_games
FROM `markets_us.market_mapping`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
GROUP BY league, sport
ORDER BY mapping_rows DESC
```

---

## Panel 3 — Platform × league matrix (table)

Wide table: one row per league, one column per platform that has any rows in the
horizon. Grafana table viz; sort by `mapping_rows` total.

```sql
SELECT
  league,
  sport,
  sportsbook,
  COUNT(*) AS mapping_rows,
  COUNT(DISTINCT game_id) AS distinct_games
FROM `markets_us.market_mapping`
WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                     AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
  AND sportsbook IN (${sportsbook:sqlstring})
  AND league IN (${league:sqlstring})
GROUP BY league, sport, sportsbook
ORDER BY league, sportsbook
```

Use Grafana’s **partition by values** / pivot on `sportsbook`, or keep long form
and filter. Long form is the safer default (no hard-coded sportsbook columns).

---

## Panel 4 — Configured vs published gaps (table) ★

The point of using BQ `mapping_*` alongside `market_mapping`: every
league×matcher-platform present on the **latest shadow tip** that has **zero**
published rows in the horizon.

A `P_*` tip is a COW **delta layer**. Join `mapping_leagues` through the
tip→root parent chain and last-write-wins per league; do not `JOIN tip USING
(rule_set_id)` alone. Keep the depth guard at BigQuery's own 500-iteration
ceiling — a lower cap silently truncates the chain and reports mapped
leagues as uncovered.

```sql
WITH RECURSIVE
lineage AS (
  SELECT rule_set_id, parent_rule_set_id, created_at, 0 AS depth
  FROM (
    SELECT rule_set_id, parent_rule_set_id, created_at
    FROM `markets_us.mapping_rule_sets`
    ORDER BY created_at DESC
    LIMIT 1
  )
  UNION ALL
  SELECT s.rule_set_id, s.parent_rule_set_id, s.created_at, lineage.depth + 1
  FROM `markets_us.mapping_rule_sets` AS s
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
    (SELECT rule_set_id FROM lineage WHERE depth = 0) AS rule_set_id,
    (SELECT created_at FROM lineage WHERE depth = 0) AS tip_created_at,
    ROW_NUMBER() OVER (PARTITION BY l.league ORDER BY lin.depth) AS rn
  FROM `markets_us.mapping_leagues` AS l
  INNER JOIN lineage AS lin USING (rule_set_id)
),
configured AS (
  SELECT
    lg.rule_set_id,
    lg.tip_created_at,
    lg.league,
    lg.sport,
    e.sportsbook AS config_key,
    CASE e.sportsbook
      WHEN 'kalshi' THEN 'Kalshi'
      WHEN 'px' THEN 'Prophet X'
      WHEN 'crypto.com' THEN 'crypto.com'
      WHEN 'polymarket' THEN 'Polymarket'
      WHEN 'runshop' THEN 'Runshop'
      ELSE NULL
    END AS sportsbook
  FROM ranked_leagues AS lg,
  UNNEST(lg.exchanges) AS e
  WHERE lg.rn = 1
    AND lg.tombstone = FALSE
    AND e.sportsbook != 'optic'
),
published AS (
  SELECT sportsbook, league, COUNT(*) AS mapping_rows
  FROM `markets_us.market_mapping`
  WHERE start_date BETWEEN CURRENT_TIMESTAMP()
                       AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL ${horizon_days} DAY)
  GROUP BY sportsbook, league
)
SELECT
  c.league,
  c.sport,
  c.sportsbook,
  c.config_key,
  c.rule_set_id,
  c.tip_created_at,
  IFNULL(p.mapping_rows, 0) AS mapping_rows
FROM configured c
LEFT JOIN published p
  ON p.league = c.league AND p.sportsbook = c.sportsbook
WHERE c.sportsbook IS NOT NULL
  AND IFNULL(p.mapping_rows, 0) = 0
  AND c.league IN (${league:sqlstring})
ORDER BY c.league, c.sportsbook
```

**League filter:** Grafana multi-value `includeAll` should expand to the full
value list. If a custom all-value breaks `IN (...)`, clear “Custom all value”
or drop the league predicate and use table search.

**Sportsbook filter:** gap rows are *missing* published sportsbooks, so do **not**
filter `published` by `${sportsbook}`. Optionally restrict to configured books:

```sql
AND c.sportsbook IN (${sportsbook:sqlstring})
```

### How to read Panel 4

1. **Offseason majors** (`nba`, `nhl`, `ncaab`, `epl`, `world_cup`, …) with every
   book at 0 → expected when the horizon has no fixtures; widen `horizon_days` or
   ignore until the season opens.
2. **In-season league, one book at 0** (e.g. `crypto.com` on `liga_mx` while
   Kalshi/Polymarket have rows) → real coverage hole; check fetch + matcher for
   that exchange.
3. **Whole league empty but tip lists exchanges** → fetch/league wiring or no
   Optic fixtures in window. The fix, if any, is in code (league catalogue,
   vocab, profile) with a test and the `regression:mapping-gate` delta.

Verified against `rs-marketmaking` on 2026-08-11 with a 14-day horizon: gap set
includes seasonal empties (nba/nhl/ncaab/epl/world_cup) and targeted holes such
as `crypto.com` on `atp_challenger` / `itf_*` / `liga_mx` / `ufc`, and
`Polymarket` on `cfl`.

---

## Panel 5 — Tip freshness (stat)

Catch a stale shadow seed (Panel 4 would then describe yesterday’s wiring):

```sql
SELECT
  rule_set_id,
  created_at AS tip_created_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) AS hours_since_tip,
  expected_league_count,
  expected_market_rule_count,
  expected_entity_count
FROM `markets_us.mapping_rule_sets`
ORDER BY created_at DESC
LIMIT 1
```

Threshold suggestion: amber when `hours_since_tip` > 48 if you re-seed on a
cadence; red if tip is missing entirely (query returns 0 rows).

---

## Suggested layout

| Row | Panels |
|---|---|
| 1 | Panel 1 (bar, half) · Panel 5 (stat, half) |
| 2 | Panel 2 (table, full) |
| 3 | Panel 3 (table, full) |
| 4 | Panel 4 (table, full) — gaps |

---

## Reading the dashboard

1. **Panel 1 / 2 look thin vs yesterday** → check pipeline cron and
   `last_updated` on a sample `market_mapping` row before assuming matcher
   regressions.
2. **Panel 4 full of offseason leagues** → noise; filter `league` to in-season
   books or raise `horizon_days`.
3. **Panel 4 shows an in-season matcher gap** → start with fetch logs for that
   sportsbook, then the code: venue league catalogue
   (`mappers/exchanges/*_leagues.py`), vocab (`mappers/vocab/`), profile
   (`mappers/profiles/`), aliases (`mappers/vocab/*_aliases.py`). Add a test,
   open an MR, read the `regression:mapping-gate` delta; removed rows need a
   waiver in `regression/waivers.toml`.
4. **Panel 5 tip old** → expected; the tip is retiring. Do not re-seed or run
   `BigQuery.load_mapping_rules`; read Panel 4 as legacy only.

---

## Appendix — Polymarket RFQ gap panels

Copy-paste source: [`docs/polymarket-mapping-gaps.md`](polymarket-mapping-gaps.md).
Generate SQL with:

```bash
python scripts/print_polymarket_gap_sql.py --summary --project ${GCP_PROJECT}
python scripts/print_polymarket_gap_sql.py --detail --project ${GCP_PROJECT}
python scripts/print_polymarket_gap_sql.py --census --project ${GCP_PROJECT}
```

Suggested panels:

| Panel | Query |
|-------|-------|
| Poly gap summary | `--summary` |
| Poly actionable only | summary + `WHERE gap_reason LIKE 'actionable%'` |
| Poly per-clob | `--detail` `LIMIT 500` |
| Poly prefix census | `--census` |

Wired prefixes come from tip COW lineage inside the SQL (not Grafana variables);
that read is tip debt. There is no bun/bul special-case — `bun` is Bundesliga.

---

## Appendix — Crypto.com RFQ unmapped classify

Copy-paste source: [`BigQuery/sql/crypto_rfq_unmapped_classify.sql`](../BigQuery/sql/crypto_rfq_unmapped_classify.sql).

Use this panel when Grafana **Unmapped reasons** still regexes
`metadata.reason_detail` — the Java maker (2026-09+) stores leg symbols in
`metadata.quote_details` (`qr.symbols[].legs[].symbol`). The classify query
unions quote_details, legacy reason_detail, and structured `legs` rows (same
kernel as [`mappers/control_plane/crypto_rfq_symbols_sql.py`](../mappers/control_plane/crypto_rfq_symbols_sql.py)).

Suggested panels:

| Panel | Query |
|-------|-------|
| Crypto unmapped by gap_reason | classify SQL grouped by `gap_reason`, `league` |
| Crypto period overlay only | `WHERE gap_reason LIKE 'period overlay gap:%'` |
| Crypto maker-lag | `WHERE gap_reason LIKE 'maker-lag%'` |

**Reading labels**

- **`period overlay gap`** — full-game fixture is mapped; crypto publishes
  1H/1Q/2H game lines under the same contract strings. Fix is mapper
  `period_contract_types` (NFL/NCAAF), not alias pins.
- **`completed fixture (stale)`** — kickoff in the past; harvest skips these.
- **`maker-lag`** — row already in `market_mapping`; RFQ cache/lookup lag.
- **`league not onboarded`** — only for leagues not in the run set (e.g. GOLF).
  CFB/NCAAAF are wired; stale CFB rows in old panels were false positives.

Davis Cup: the `atp` league fetches Optic `davis_cup` fixtures via
`extra_optic_league_ids`. That field is still set from the tip today
(`scripts/submit_atp_davis_cup_extra.py` was the submit path); both are
retired. A change to it is a code change.

---

## Appendix — Gap-propose ledger (`mapping_gap_ledger`)

Table: `` `{project}.markets_us.mapping_gap_ledger` `` (DDL in mm-infrastructure).
Writer: gap-propose CronJob (`MAPPING_GAP_LEDGER=1`, default on). Rows are
append-only per harvest tick. Legacy: read a skipped key as a code change to
make, not a console card to approve.

**Outcome counts (last 24h)**

```sql
select outcome, count(*) as keys, sum(demand) as rfq_demand
from `markets_us.mapping_gap_ledger`
where run_at > timestamp_sub(current_timestamp(), interval 24 hour)
group by 1
order by rfq_demand desc
```

**Top unexplained demand (skipped / not_walked / needs_probe)**

```sql
select book, key, demand, outcome, reason
from `markets_us.mapping_gap_ledger`
where run_at > timestamp_sub(current_timestamp(), interval 24 hour)
  and outcome in ('skipped', 'not_walked', 'needs_probe', 'needs_league')
qualify row_number() over (partition by book, key order by run_at desc) = 1
order by demand desc
limit 50
```

**Latest skipped demand by book, league, and reason** (7 days, latest row per key). `demand` is the RFQ demand the harvest copied onto the ledger. `no_pin` is included because those rows predate the walk recorder.

```sql
with latest as (
  select book, key, league_token, outcome, reason, demand
  from `markets_us.mapping_gap_ledger`
  where run_at > timestamp_sub(current_timestamp(), interval 7 day)
    and book not in ('_reopen', 'rfq')
  qualify row_number() over (partition by book, key order by run_at desc) = 1
)
select
  book,
  league_token,
  reason,
  count(*) as keys,
  sum(demand) as rfq_demand,
  array_agg(key order by demand desc limit 1)[offset(0)] as sample_key
from latest
where outcome = 'skipped' or reason = 'no_pin'
group by 1, 2, 3
order by rfq_demand desc
limit 50
```

**Same keys joined to live `rfq_latest` legs** (7 days). A leg matches the ledger key exactly, or a market ticker under that event.

```sql
with latest as (
  select book, key, league_token, outcome, reason
  from `markets_us.mapping_gap_ledger`
  where run_at > timestamp_sub(current_timestamp(), interval 7 day)
    and book not in ('_reopen', 'rfq')
  qualify row_number() over (partition by book, key order by run_at desc) = 1
),
legs as (
  select coalesce(
    json_value(leg.platform_mapping, '$.market_ticker'),
    json_value(leg.platform_mapping, '$.ticker'),
    json_value(leg.platform_mapping, '$.symbol')
  ) as leg_key
  from `reporting_us.rfq_latest` as r, unnest(r.legs) as leg
  where r.last_updated > timestamp_sub(current_timestamp(), interval 7 day)
    and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
)
select
  s.book,
  s.league_token,
  s.reason,
  count(distinct s.key) as keys,
  count(legs.leg_key) as rfq_legs
from latest as s
left join legs
  on legs.leg_key = s.key
  or starts_with(legs.leg_key, concat(s.key, '-'))
where s.outcome = 'skipped' or s.reason = 'no_pin'
group by 1, 2, 3
order by rfq_legs desc
limit 50
```

**Unknown RFQ platforms** (outside `rfq_platforms.py`) — compare to gap-propose
logs; optional panel when the table is not deployed yet:

```sql
select r.platform, count(*) as demand
from `reporting_us.rfq_latest` r
where r.last_updated > timestamp_sub(current_timestamp(), interval 3 hour)
  and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
  and lower(r.platform) not like 'polymarket%'
  and r.platform not in (
    'kalshi', 'kalshi-inplay', 'kalshi-inplay-cashout',
    'cryptocom', 'cryptocom-inplay', 'novig', 'novig-inplay', 'prophetx'
  )
group by 1
order by demand desc
```
