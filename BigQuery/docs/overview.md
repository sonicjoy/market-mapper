# BigQuery backend overview

Project: **rs-marketmaking**

## Datasets

| Dataset | Purpose |
|---|---|
| `opticodds_us` | Optic Odds fixtures, prices, leagues, sports, sportsbooks. Core reference data. |
| `markets_us` | Kalshi markets/series and mapping views (moneyline, formatted, submapping). |
| `processed_upstream_us` | Derived data: fair prices, best bid/ask, orderbooks, trades, volumes. |
| `raw_ingestion_us` | Raw exchange messages: Kalshi RFQ, ProphetX parlay RFQ, Polymarket. |
| `trading_us` | Orders, RFQ, barriers, registration, market filters. |
| `reporting_us` | Positions, account balances, resolutions, order timings, live orders. |
| `parlay_pricing_us` | Parlay leg pricing and quotes. |
| `analysis_us` | Closing prices (single table). |
| `infrastructure_us` | Error and request logs. |
| `operational_us` | RFQ config changes, sport subscriptions. |
| `rs_billing_export` | GCP billing data. |
| `temp_data` | Empty. |

## Key tables for market mapping

### `opticodds_us.prices_dedup_state`

Regular table (~111k rows as of 2026-03-10), not a materialized view.
Clustered by `sport, league, market, game_id`. Provisioned via
Terraform, populated by an external pipeline.

Holds the latest deduplicated price per selection. **Only holds
current/recent data** — past games are flushed (March 8th data was
gone by March 10th).

Approximate natural key: `game_id, market_id, sportsbook, selection,
selection_line, points` (excluding `is_main` and `is_live` for now to
see what happens — a couple of duplicate rows exist at the full key
level, likely a dedup bug).

~84% of rows have empty `source_ids` (traditional sportsbooks like
FanDuel, DraftKings). Only ~16% (17k rows) have exchange identifiers
(Kalshi, PX, Polymarket). The purpose of the non-exchange rows is
unclear.

Key columns:

- `game_id` (STRING, REQUIRED) — Optic game identifier
- `start_date` (TIMESTAMP, REQUIRED)
- `sport`, `league` (STRING)
- `market_id`, `market` (STRING) — e.g. "moneyline", "Moneyline"
- `sportsbook` (STRING) — e.g. "Kalshi", "Prophet X"
- `selection`, `selection_line` (STRING)
- `points`, `selection_points` (FLOAT)
- `is_main`, `is_live`, `exclude_fees` (BOOLEAN)
- `source_ids` (JSON) — exchange-specific identifiers, per-sportsbook
  row. Each sportsbook has its own JSON shape:
  - Kalshi: `{"market_id": "KXNBATOTAL-26MAR10DALATL-224", "selection_id": "yes"}`
  - Prophet X: `{"event_id": "90107679", "selection_id": "5d77141226880d9e..."}`
  - PX `selection_id` is our `px_line_id`; Kalshi `market_id` is our
    `kalshi_market_ticker` and `selection_id` is our `kalshi_side`.
  - Note: `opticodds_prices` has a *different* `source_ids` structure
    (per-betting-exchange IDs like Betfair/Polymarket, not per-platform).
- `last_updated` (TIMESTAMP, REQUIRED)

### `opticodds_us.v_optic_market_mapping` (VIEW)

Joins deduplicated fixtures to `prices_dedup_state`. Enriches with:
- `sport`, `sport_id`, `league`, `league_id`
- `home_team_display`, `away_team_display`
- `status`, `fixture_is_live`

Deduplicates fixtures by `game_id`, keeping the latest `start_date`
(handles rescheduled games). Window: 1 day ago to 14 days ahead.

This view is the live equivalent of the file-based batch mappings.

### `opticodds_us.opticodds_prices`

Raw prices table, one row per sportsbook price update. Partitioned by
`publish_time`. Used by the Grafana "missing mappings" dashboard.

Joined to `opticodds_fixtures` via the fixture hex ID (`f.id =
p.fixture_id`), **not** `game_id`. This is a different join key from
`prices_dedup_state` which uses `game_id`.

Has its own `source_ids` JSON field, but the structure is
per-betting-exchange (Betfair-style selection IDs, Polymarket token
IDs) — not the same as `prices_dedup_state.source_ids` which holds
Kalshi/PX identifiers.

### `markets_us.kalshi_markets`

Kalshi market data. Three associated views:
- `kalshi_formatted_markets` — formatted for display
- `kalshi_optic_moneyline_mapping` — maps Kalshi to Optic for moneylines
- `kalshi_future_submapping_markets` — future/sub-market structure

### ProphetX

No dedicated PX tables. PX data flows through Optic's `source_ids` JSON
field in `prices_dedup_state`. Raw PX parlay RFQs land in
`raw_ingestion_us.prophetx_parlay_rfq`, and resolutions in
`reporting_us.prophetx_resolutions`.

## Data flow

```
Optic API → opticodds_fixtures (raw)
          → opticodds_prices (raw, all sportsbooks)
          → prices_dedup_state (deduplicated, latest per selection)
          → v_optic_market_mapping (joined with fixture metadata)
```

The file-based batch mappings in `data/` produce the same linkage
(Optic fixture → Kalshi ticker → PX line_id) but offline, from fetched
snapshots. Integration means getting these mappings into (or validated
against) the BQ pipeline.

## market_mapping table

WIP schema design for a new table to hold our file-based mappings in
BQ, enabling joins against the existing tables. See
`BigQuery/docs/market_mapping_schema.md` for full details.

Key decisions so far:
- One row per sportsbook per market outcome (unpivoted), matching
  the structure of `prices_dedup_state`. Key fields (date, time,
  home, away, market_type, entity, line, side, group, sportsbook)
  plus resolved Optic fields (game_id, fixture_id, etc.) plus
  per-exchange `source_ids` JSON.
- Upsert via MERGE with `last_updated` — matches existing project
  patterns (no batch_id, no history).
- Two import filters: skip rows with no Optic match (21%), and skip
  rows with no exchange data (62% of remainder). Only rows with at
  least one exchange (Kalshi/PX) are loaded.
- Production table via Terraform + GitLab MR (later).

## Sandbox for development

Dataset `greg_sandbox` in `rs-marketmaking`, region `us-east4` (must
match production datasets to allow joins). Create the table there,
load test data from the mappings files, and join against the real
tables (read-only). Drop when done.

All production datasets are in `us-east4`. BQ cannot join across
regions.

Sandbox views:

- `v_verify_source_ids` — counts of match/mismatch/novel comparing our
  exchange mappings against Optic's `source_ids` in `prices_dedup_state`.
  See `BigQuery/sql/source-ids-verify.sql`.
- `v_market_mapping_enriched` — our mappings joined 1:1 to
  `opticodds_fixtures` for fixture context (team names, start time,
  sport, league, status). See `BigQuery/sql/market-mapping-enriched.sql`.

## Verification results (2026-03-11)

Compared our mappings against Optic's `source_ids` in
`prices_dedup_state`. Zero mismatches:

| Exchange | Status | Count |
|---|---|---|
| Kalshi | match | 599 |
| Kalshi | novel | 1,434 |
| PX | match | 647 |
| PX | novel | 1,474 |

Every mapping where Optic already had `source_ids` agreed with ours.
Novel rows are where Optic has no `source_ids` — our mapping adds
new value.

## Join from market_mapping to prices_dedup_state

Now that `market_mapping` has one row per sportsbook (matching
`prices_dedup_state`), the natural join includes `sportsbook`:

    JOIN prices_dedup_state p
      ON  m.game_id = p.game_id
      AND m.market_id = p.market_id
      AND m.selection = p.selection
      AND m.selection_line = p.selection_line
      AND m.points = p.points
      AND m.sportsbook = p.sportsbook

This gives one price row per mapping row. To see all sportsbook
prices for a mapped outcome, omit `m.sportsbook = p.sportsbook`
(or use an outer join).

Because `prices_dedup_state` only holds current data, the mapping
batch must be recent enough that the games are still in the table.

## Interactive usage

Always use `BigQuery/client.py`:

```python
from BigQuery.client import ro_client, ro_query

client = ro_client()
rows = ro_query(client, "SELECT game_id, source_ids FROM opticodds_us.prices_dedup_state LIMIT 5")
```

See `BigQuery/CLAUDE.md` for the read-only policy.
