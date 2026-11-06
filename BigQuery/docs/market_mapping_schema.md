# market_mapping schema (WIP)

## How we identify a market outcome vs how Optic does

| Our key field | Optic equivalent | Notes |
|---|---|---|
| `date` | `game_id` (contains date) | `game_id` encodes date + league + teams in one opaque string |
| `time` | `game_id` / `start_date` | No separate time field — `start_date` is a timestamp |
| `home` | `game_id` | Team identity baked into `game_id`, or via fixtures table |
| `away` | `game_id` | Same |
| `market_type` | `market_id` | Our `game_total` = their `total_points`, etc. |
| `entity` | `selection` | Our `dennis_schroder` = their `Dennis Schroder` |
| `line` | `points` | Same value, e.g. `9.5` |
| `side` | `selection` + `selection_line` | Our `CLE` = their `Cleveland Cavaliers`; our `over` = their `over` |

`game_id` collapses `date`, `time`, `home`, `away` into one opaque
key. To join the two systems we need to carry `game_id` (and possibly
other Optic fields) alongside our key.

## Import filter

Two filters applied on import (2026-03-08 batch, 23,244 raw rows):

1. **No Optic match** — 4,903 rows (21%) have `optic_odds` entirely
   null. These are Kalshi or PX markets where the mapping pipeline
   found no Optic match. Without Optic fields (`game_id`,
   `fixture_id`, etc.) these rows cannot join to any BQ table.

2. **No exchange data** — rows with an Optic match but no Kalshi,
   Prophet X, or prediction-market (`Polymarket`, `Novig`,
   `Polymarket (USA)`) identifiers in `optic_odds.source_ids` are
   skipped.  Optic-only rows (no exchange source_ids) remain excluded.

Rows with multiple exchange matches produce one output row per
sportsbook (e.g. Kalshi + PX → two rows; Kalshi + Polymarket → two
rows).  Expected counts for the 2026-03-08 batch (Kalshi/PX only):
23,244 raw → 8,236 loaded (1,223×2 both + 1,894 Kalshi-only +
3,896 PX-only).

## Key fields

These are the fields from our mapping key that uniquely identify a
market outcome.

| Column | Type | Nullable | Example |
|---|---|---|---|
| `date` | DATE | NO | `2026-03-08` |
| `time` | TIME | YES | null (no double headers in NBA/NCAAB) |
| `home` | STRING | NO | `CLE` |
| `away` | STRING | NO | `BOS` |
| `market_type` | STRING | NO | `player_points` |
| `entity` | STRING | YES | `dennis_schroder` |
| `line` | FLOAT | YES | `9.5` |
| `side` | STRING | NO | `over` |
| `group` | STRING | YES | null (only populated to disambiguate) |

FLOAT for `line` matches `prices_dedup_state.points` and
`opticodds_prices.points`.

## Optic fields

These are Optic's identifiers for the same market outcome, resolved by
our mapping pipeline. They enable direct joins to
`prices_dedup_state` and `opticodds_fixtures`.

| Column | Type | Nullable | Example |
|---|---|---|---|
| `game_id` | STRING | NO | `77646-11464-2026-03-08` |
| `fixture_id` | STRING | NO | `20260308EB9D41EB` |
| `market_id` | STRING | NO | `total_points` |
| `selection` | STRING | NO | `Cleveland Cavaliers` (empty string for totals) |
| `selection_line` | STRING | YES | `over` |
| `points` | FLOAT | YES | `9.5` |
| `grouping_key` | STRING | NO | `dennis_schroder:9.5` |

`grouping_key` is Optic's grouping, always populated. Our key has a
separate field `group` (from our `key.grouping_key`) which is only
populated when needed to disambiguate (44 of 23,244 rows in the
2026-03-08 batch). Both are kept — they serve different purposes.

## Exchange identifiers

Each row is for a single sportsbook. `sportsbook` is part of the key.
`source_ids` holds that exchange's identifiers in the same per-row
JSON format as `prices_dedup_state.source_ids`, enabling direct
comparison.

| Column | Type | Nullable | Example |
|---|---|---|---|
| `sportsbook` | STRING | NO | `Kalshi` |
| `source_ids` | JSON | YES | `{"market_id": "KXNBAGAME-26MAR08BOSCLE-CLE", "selection_id": "yes"}` |

`source_ids` shapes per sportsbook (same as `prices_dedup_state`):
- Kalshi: `{"market_id": "<ticker>", "selection_id": "<side>"}`
- Prophet X: `{"event_id": "<event_id>", "selection_id": "<line_id>"}`
- Polymarket / Novig / Polymarket (USA):
  `{"selection_id": "<token>"}`
- crypto.com (Optic-decoded):
  `{"security_id": "<FIX SecurityID>", "symbol": "<FIX Symbol>",
    "market_id": "<Optic PM.NPO market_id>"}`
- crypto.com (FIX-only fallback):
  `{"security_id": "<FIX SecurityID>", "symbol": "<FIX Symbol>"}`
- Runshop: `{"fixture_id": "<tx live txOddsFixtureID>", "market_id": "<runshop market id>"}`

For crypto.com, `JSON_VALUE(source_ids, '$.symbol')` is part of the
MERGE / uniqueness identity (NULL for every other sportsbook) so
distinct live FIX Symbols for one canonical bet each keep a row. There
is no denormalized `source_symbol` column — RFQ already joins
`source_ids.symbol` verbatim.

Kalshi and Prophet X `source_ids` are constructed from pipeline match
fields (`kalshi.market_ticker` + `kalshi.side`, `prophet_x.event_id` +
`prophet_x.line_id`).  Prediction-market `source_ids` (Polymarket /
Novig / SX Bet) are taken directly from `optic_odds.source_ids` in the
mapping JSONL.  crypto.com is **not** an `OPTIC_MAPPED_SPORTSBOOKS`
passthrough: Optic's crypto `market_id` is decoded to a FIX Symbol via
the catalogue, then emitted from the pipeline `crypto_com` block
(hybrid with FIX semantic rows for gaps).

## Update strategy

Upsert via MERGE, matching on the key fields (`date`, `home`, `away`,
`market_type`, `entity`, `line`, `side`, `group`, `sportsbook`, and
`JSON_VALUE(source_ids, '$.symbol')`). This follows the existing
project pattern — `prices_dedup_state` and `kalshi_markets` both work
this way: one row per key, overwritten on update, no history.

| Column | Type | Nullable | Example |
|---|---|---|---|
| `last_updated` | TIMESTAMP | NO | `2026-03-08T07:59:00Z` |

BigQuery does not enforce unique constraints. Uniqueness of the key
must be guaranteed by the mapping pipeline before loading. The
incoming batch should be deduped before MERGE (MERGE will error if the
source has duplicate keys). A post-load assertion query can verify:
`GROUP BY` the key fields `HAVING COUNT(*) > 1`.

On MERGE:
- **Match exists:** update exchange identifiers, Optic fields, and
  set `last_updated` to now.
- **No match:** insert a new row with `last_updated` set to now.

The table always reflects the current best mapping. No batch_id, no
history table — consistent with the rest of the backend.

## Deployment

Production table creation requires Terraform and a GitLab merge
request — standard infrastructure-as-code workflow. The schema
documented here is what gets translated into a
`google_bigquery_table` Terraform resource.

For development and testing, create an ad-hoc sandbox dataset in the
existing project (e.g. `greg_sandbox`), create the table there, load
test data, and run joins against the real tables. No Terraform needed
— the real tables are read-only from the sandbox's perspective. Drop
the dataset when done.

## Provenance / extras

TODO — check fields, etc.
