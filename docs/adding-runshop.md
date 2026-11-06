# Adding Runshop support

Runshop is the sportsbook label in `markets_us.market_mapping` for
betbuilder price lookup. Downstream clients holding Optic IDs resolve
Runshop keys (`txOddsFixtureID` + `market_id`) from the same table
used by Kalshi, Prophet X, and crypto.com.

## Architecture

```
Optic leg (canonical row)
  → runshop_tx_odds_fixture_id  (tx live / API fixture_id)
  → runshop_market_id           (Runshop market dictionary)
  → market_mapping row (sportsbook='Runshop')
  → client filters getBetBuilderModelPrices snapshot locally
```

Fixture join is an **exact ID chain**, not semantic team matching:

```
tx_odds_fixture_id (tx live)     [betbuilder API — fixture selector]
  → tx_legacy_fixture_id         [txodds-fusion.public.fixture, when ≠ tx live]
  → poly_game_id                 [poly_tx_mapping.fixtures]
  → optic_fixture_id             [poly event title/start + Optic schedule]
```

Market IDs decode from the Runshop vendor dictionary (see below).
Optic → Runshop name mapping is
[`runshop_crosswalk.toml`](../vendor/world_cup/runshop_crosswalk.toml),
read by `load_crosswalk` in `mappers/exchanges/runshop_crosswalk.py`.

### Vendor dictionary (BigQuery)

The full vendor dictionary (~14k rows) is reference data, not a mapping rule.
It is reference data in ``raw_ingestion_us.runshop_vendor_markets`` (stub
loader: ``python -m BigQuery.load_runshop_vendor --from-toml
vendor/world_cup/runshop_markets.toml``). Until a fetch job replaces the
one-shot TOML import, stamping reads
[`runshop_markets.toml`](../vendor/world_cup/runshop_markets.toml) via
``runshop_vendor.load_vendor_markets``.

Archive conversion from CSV:
[`scripts/convert_runshop_markets_to_toml.py`](../scripts/convert_runshop_markets_to_toml.py).

## GCP Secret Manager (one-time per project)

Create these secrets in **both** `marketmaking-test` and `rs-marketmaking`:

| Secret | Purpose |
|---|---|
| `runshop_txodds_fusion_db_password` | txodds-fusion Postgres (`markets_reader`) |
| `runshop_poly_db_password` | polymarket Postgres (`spyridon`) |
| `runshop_betbuilder_api_key` | `X-WSD-API-KEY` for betbuilder price API (fixture list) |

Hosts, database names, and usernames are constants in
[`fetch/runshop.py`](../fetch/runshop.py) (not secrets).

Runtime access uses `gcloud secrets versions access` with `GCP_PROJECT`,
same pattern as [`fetch/kalshi.py`](../fetch/kalshi.py).

Deploy runs [`infra/verify_runshop_secrets.sh`](../infra/verify_runshop_secrets.sh)
after [`infra/ensure_env.sh`](../infra/ensure_env.sh) (warn-only).

If the VM cannot read secrets, grant `roles/secretmanager.secretAccessor`
on each secret to the compute service account.

## Fetch

[`fetch/runshop.py`](../fetch/runshop.py) runs when `world_cup` is in
the league list (`python -m fetch`). Output:

- `runshop_prices.jsonl` — verbatim betbuilder price snapshot (API
  response fields: `id`, `txOddsFixtureID`, `updateTimeStamp`,
  `marketIds`, `modelId`, `price`, `metadataId`)
- `runshop_fixture_chain.jsonl` — tx live id, legacy id, poly game_id,
  poly event title/start for schedule correlation.

**Fixture selector:** `GET getBetBuilderModelPrices?modelId=224` —
unique `txOddsFixtureID` values are the only fixtures included each run
(typically a small rolling window of upcoming World Cup games).

**DB enrichment (scoped to those ids only):**

1. `poly_tx_mapping.fixtures` — legacy id → poly `game_id`
2. `txodds-fusion.public.fixture` — tx live → legacy when they differ
3. `polymarket.public.events` — title + kickoff for Optic matching

No delta time window or accumulated catalogue — each fetch replaces
the chain with the current betbuilder fixture set.

Requires `pg8000`, `gcloud auth`, and `GCP_PROJECT`.

## Mapper

[`mappers/exchanges/runshop.py`](../mappers/exchanges/runshop.py):

- `load_runshop_markets()` — TOML market dictionary
- `build_fixture_chain_index()` — poly metadata → Optic `fixture_id`
- `stamp_runshop_rows()` — after Optic merge in the pipeline

Stamped fields on `CanonicalRow`:

- `runshop_tx_odds_fixture_id`
- `runshop_market_id`

JSONL block:

```json
"runshop": {
  "tx_odds_fixture_id": 905827989,
  "market_id": 3
}
```

## BigQuery load

### Mappings

[`BigQuery/load_mappings.py`](../BigQuery/load_mappings.py) emits one
row per Optic leg with `sportsbook='Runshop'`:

```json
"source_ids": {
  "fixture_id": "905827989",
  "market_id": "3"
}
```

Requires `optic_odds` present (same as Kalshi/PX).

### Prices

[`BigQuery/load_runshop_prices.py`](../BigQuery/load_runshop_prices.py)
appends `runshop_prices.jsonl` to `raw_ingestion_us.runshop_prices`
(day-partitioned on `insert_time`).  The loader stamps one `insert_time`
per snapshot and skips rows whose `(id, updateTimeStamp)` pair already
exists in the table (30-day partition window).  The table is created on
first run if missing.  Wired into [`infra/run_pipeline.sh`](../infra/run_pipeline.sh)
as a best-effort step after mappings load.

## League scope

World Cup only, via the `runshop_generic_v1` profile
(`RunshopGenericProfile` in `mappers/profiles/_builders.py`). Today its
settings and any `rule_kind=crosswalk` rows are still read from the
retiring tip (`mappers/seed/tip_exchange_build.py`,
`mappers/seed/overlay_taxonomy.py`). That is migration debt: never add
Runshop settings or crosswalk rows to the tip (see `CLAUDE.md`).

## Market crosswalk

Runshop market ids come from the vendor dictionary (TOML archive or BQ table).
Optic → Runshop name mapping is
[`runshop_crosswalk.toml`](../vendor/world_cup/runshop_crosswalk.toml).
To change it: edit the TOML, add a case to `tests/mappers/test_runshop.py`,
run `GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q`, open the MR and
read the `regression:mapping-gate` row delta. Removed rows need a waiver
in `regression/waivers.toml`.

A crosswalk rule is **active** only when:

1. its `runshop_market` exists in the loaded markets TOML, and
2. its `optic_market_type` appears in the current upstream rows.

Stamping tries active rules against the market index; no match → skip.

| Runshop market | Optic `market_type` | Notes |
|---|---|---|
| OU Goals | `game_total` | over/under |
| OU Goals - HT | `1h_total` | over/under |
| Asian Handicap | `point_spread` | home/away side |
| Asian Handicap - HT | `1h_point_spread` | home/away side |
| Home/Away Team Goals - FT | `team_total` | entity home/away |
| Total Corners - FT | `total_corners` | over/under |
| Home/Away Team Corners - FT | `team_total_corners` | entity + over/under |
| Handicap Team Corners - FT/HT | `asian_handicap_corners`* | home/away side |
| Euro Handicap* | `point_spread_yn`* | three-way |

\* Active only when upstream maps the Optic market type and TOML carries
the Runshop market name.

Add crosswalk rows via the control plane (or archive TOML for re-seed) when
a new Runshop market family should join; no Python changes required unless a
new `selection` mode is needed (`over_under`, `home_away`, `three_way`).

## Regenerating markets TOML

```powershell
python scripts/convert_runshop_markets_to_toml.py path\to\markets.csv
```

Skips CSV rows with `NULL` value (combo markets with no scalar line).

## Tests

```powershell
pytest tests/fetch/test_runshop.py tests/mappers/test_runshop.py tests/BigQuery/test_flatten_rows.py tests/BigQuery/test_load_runshop_prices.py -k runshop
```
