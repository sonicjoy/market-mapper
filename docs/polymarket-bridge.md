# Polymarket position bridge (independent cron)

The bridge table `raw_ingestion_us.polymarket_position_token_bridge` maps
RFQ combo-leg `position_id` → CLOB `clob_token_id` (plus slug / question /
outcome). Official Polymarket mapping and `mmpolymarketrfq` depend on it.
Polymarket US Path 2 does **not** use it.

## Why it is not inside `run_pipeline.sh`

Paging combos-rfq-api `/v1/rfq/combo-markets` is ~6 minutes (`limit=50`,
no date/sport filter). When that ran as the first step of the 15-min
mapping tick it held `logs/pipeline.lock`, so the next `:15` skipped.

The mapping tick only **reads** the last MERGE. Existing rows are
immutable on-chain pairings; skipping a catalog pull does not flip sides
or drop mapped tokens. A **new** combo `position_id` waits until the next
successful bridge run (`gap_reason` `no_bridge` until then).

## Schedule (VM crontab, installed on deploy)

| Job | Cadence | Lock | Log |
|-----|---------|------|-----|
| Mapping | `*/15` (`cron_pipeline.sh`) | `logs/pipeline.lock` | `logs/pipeline.log` |
| Bridge | `8,23,38,53 * * * *` (`cron_polymarket_bridge.sh`) | `logs/polymarket_bridge.lock` | `logs/polymarket_bridge.log` |

Offset +8 min from the mapping tick so they do not start on the same
second. `:10/:25/:40/:55` is ITF synth. If a bridge run is still active,
the next slot logs `skip: previous polymarket bridge run still active`
and exits 0 (no Slack). A real loader failure Slack-alerts via the cron
wrapper.

Manual / `--cids-file` backfill: `infra/run_polymarket_bridge.sh`.

## History

- **2026-07-08** (`e8aa06a`) — loaders added; hourly VM cron + 3-hourly GKE
  CronJob both MERGEd the same table.
- **2026-07-27** (`948b879`, Victor Popa) — collapse the duplicate jobs onto
  the VM pipeline so the MERGE ran once.
- **2026-07-27** (`2e16f46`, review follow-up) — move the rebuild **before**
  fetch for same-tick freshness. That is what blocked `pipeline.lock`.
- **2026-08-28** — move it back to an independent cron (own lock). Mapping
  fetch starts immediately; bridge freshness is “last successful MERGE”
  (typically this 15-min offset slot, not same-tick).
