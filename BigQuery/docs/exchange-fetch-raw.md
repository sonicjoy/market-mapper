# Exchange fetch raw tables (mm-infrastructure)

Authoritative DDL lives in **mm-infrastructure**, not this repo. Apply Terraform on
`marketmaking-test` then `rs-marketmaking` before enabling `MAP_SNAPSHOT_SOURCE=bq`.

## Dataset

`raw_ingestion_us` — same dataset as `kalshi_raw` / `novig_raw`.

## Tables

Each table is append-only, **day-partitioned on `fetch_time`**, **7-day partition
expiration**, `deletion_protection = true`.

| Table | Clustering | Purpose |
|---|---|---|
| `optic_fetch_raw` | `league_id`, `snapshot_id` | Optic `/fixtures/odds` lines |
| `kalshi_fetch_raw` | `series_prefix` (always NULL now), `snapshot_id` | Kalshi markets |
| `polymarket_fetch_raw` | `slug_prefix`, `snapshot_id` | Polymarket bridge export |
| `polymarket_usa_fetch_raw` | `inner`, `snapshot_id` | Polymarket US Path 2 tickers (JSONL + sportsMarketType overlay) |
| `crypto_fetch_raw` | `league`, `snapshot_id` | crypto.com catalogue |
| `novig_fetch_raw` | `league`, `snapshot_id` | Novig events + markets (`kind`) |
| `px_events_fetch_raw` | `tournament_id`, `snapshot_id` | ProphetX events |
| `px_markets_fetch_raw` | `tournament_id`, `snapshot_id` | ProphetX markets |

### Shared columns

- `snapshot_id` STRING NOT NULL — e.g. `2026-08-19T10_35` from `data/2026-08-19/10_35`
- `fetch_time` TIMESTAMP NOT NULL — UTC instant of the fetch directory
- `data` STRING NOT NULL — verbatim JSONL line

### Per-table keys (nullable STRING unless noted)

- `optic_fetch_raw`: `league_id`, `game_id`
- `kalshi_fetch_raw`: `event_ticker` (`series_prefix` is no longer written; the snapshot index keys Kalshi lines by their `sport` field)
- `polymarket_fetch_raw`: `slug_prefix`, `condition_id`
- `polymarket_usa_fetch_raw`: `inner`, `ticker`
- `crypto_fetch_raw`: `league`
- `novig_fetch_raw`: `kind` (`events` | `markets`), `league`
- `px_events_fetch_raw`: `tournament_id`, `event_id`
- `px_markets_fetch_raw`: `tournament_id`, `market_id`

## Schema JSON (copy to mm-infrastructure)

Path in this repo (reference copies): `BigQuery/docs/schemas/raw_ingestion/<table>.json`

Path suggestion in mm-infrastructure: `modules/general_us/schemas/raw_ingestion/<table>.json`

Example `optic_fetch_raw.json`:

```json
[
  {"name": "snapshot_id", "type": "STRING", "mode": "REQUIRED"},
  {"name": "fetch_time", "type": "TIMESTAMP", "mode": "REQUIRED"},
  {"name": "league_id", "type": "STRING", "mode": "NULLABLE"},
  {"name": "game_id", "type": "STRING", "mode": "NULLABLE"},
  {"name": "data", "type": "STRING", "mode": "REQUIRED"}
]
```

Repeat for other tables with their key columns. Wire `google_bigquery_table` resources
in `modules/general_us/main.tf` mirroring `kalshi_raw`.

## IAM

Grant the mmmapper VM service account **BigQuery Data Editor** on these tables
(same pattern as existing raw_ingestion loaders).

## Loader (this repo)

`python -m BigQuery.load_exchange_fetch data/YYYY-MM-DD/HH_MM`

Called from `infra/run_pipeline.sh` after fetch, before map.
