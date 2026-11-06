# Polymarket mapping gaps

Working taxonomy and Grafana copy-paste SQL for Polymarket / Polymarket US
RFQ legs that lack Optic coords under `MAPPING_FAILED` / `UNMAPPED`.

Related: [`rfq-mapping-gap-classification.md`](rfq-mapping-gap-classification.md),
[`mapping-coverage-grafana.md`](mapping-coverage-grafana.md).

## Paste-ready SQL

```bash
python scripts/print_polymarket_gap_sql.py --summary --project rs-marketmaking
python scripts/print_polymarket_gap_sql.py --detail --project rs-marketmaking
python scripts/print_polymarket_gap_sql.py --census --project rs-marketmaking
```

Templates (with `{project}`):

| File | Role |
|------|------|
| [`BigQuery/sql/polymarket_mapping_gaps.sql`](../BigQuery/sql/polymarket_mapping_gaps.sql) | Per-clob / per-ticker detail |
| [`BigQuery/sql/polymarket_mapping_gaps_summary.sql`](../BigQuery/sql/polymarket_mapping_gaps_summary.sql) | `priority` × `gap_reason` × `slug_prefix` |
| [`BigQuery/sql/polymarket_prefix_optic_census.sql`](../BigQuery/sql/polymarket_prefix_optic_census.sql) | Bridge prefix → Optic league candidates |

Window: `last_updated` 3h, `first_publish_time` 48h, platforms `polymarket%`.

Today the gap SQL reads wired official Path 2 prefixes and Polymarket US
inner codes from the retiring tip (`mapping_leagues.exchanges[]`,
`settings.slug_prefix` / `source_league_id`). That is migration debt (see
`CLAUDE.md`): it reports what is wired, it is not where you wire a league.

## `gap_reason` tree

| Reason | Action |
|--------|--------|
| `maker-lag` | Row already in `market_mapping` — wait for maker cache |
| `no_bridge` | Wait for bridge loader |
| `actionable path2_off (Optic fixture present)` | Code change: wire the league in code, add a test, MR + gate (no tip pin) |
| `actionable game-line gap` | Path 2 on, **real** Optic fixture present (`wsdsyn-` ignored), clob not published |
| `path2_off (no Optic fixture)` | Out of scope / deferred |
| `optic_empty` | Path 2 on, no real Optic name match |
| `outside Optic horizon` | Wait |
| `expected residual: yes-only No` / `exact_score` / `period_market` / `half_or_oddeven_corners` / `completed` / `no_optic_book` | Leave. `no_optic_book` = name hit only on a GREG `wsdsyn-` stand-in |
| `us_optic_no_passthrough` | US symbol on a wired inner; Optic did not expose `polymarket_usa_` |

`is_actionable` = `gap_reason` contains `actionable`.

## Bridge

The mapper tick does not publish a Polymarket coverage alert. A gap is a
code change: vocab in `mappers/vocab/*_markets.py`, profiles in
`mappers/profiles/`, venue matching in `mappers/exchanges/polymarket*.py`,
a test in `tests/mappers/`, then the MR and the `regression:mapping-gate`
row delta (removed rows need a waiver in `regression/waivers.toml`).

| Path | Role |
|------|------|
| `infra/cron_polymarket_bridge.sh` | Independent VM cron (`8,23,38,53`); MERGE `polymarket_position_token_bridge`. Not on `pipeline.lock`. See [`polymarket-bridge.md`](polymarket-bridge.md). |
| `pipeline_gap_propose` CronJob | Legacy. It drafts console Review cards and tip pins; that path is retired. Read its inventory as a list of code changes to make, never approve its cards. |

## Official vs Polymarket US

- **Official:** RFQ `token_id` = bridge `position_id` → `clob_token_id` →
  `market_mapping.selection_id` (`sportsbook = 'Polymarket'`).
- **US:** join on symbol equality to `Polymarket (USA)`
  `source_ids.market_id`. **Do not** use the bridge. The symbol is opaque and
  never split: its inner / sportsMarketType come from the gateway record the
  fetch stored (`raw_ingestion_us.polymarket_usa_fetch_raw`), and Path 2 maps
  from `polymarket_usa_markets.jsonl` typed fields (sportsMarketType,
  market sides). The league binding still reads the tip `polymarket_usa`
  pin (`source_league_id`, e.g. `cfb`) on main; that is debt: move it
  to a code table keyed by the gateway's typed league id.

## Grafana panels (copy-paste)

1. **Summary** — run `--summary`.
2. **Actionable only** — wrap summary with
   `WHERE gap_reason LIKE 'actionable%'`.
3. **Per-clob table** — `--detail` with `LIMIT 500`.
4. **Official vs US** — group summary by `platform`.
5. **Coverage ratio** — for each `slug_prefix`, mapped /
   (mapped + unmapped) from `market_mapping` vs gap occ (operators save
   `snapshot_at` + counts; optional `greg_sandbox.polymarket_gap_baseline`).

Dashboard JSON stays in mm-infrastructure; this file is the SQL source of truth.
After changing the templates, regenerate and re-paste Grafana:

```bash
python scripts/print_polymarket_gap_sql.py --summary --project rs-marketmaking
python scripts/print_polymarket_gap_sql.py --detail --project rs-marketmaking
```

## Baseline 2026-08-25

Captured at run time in
[`scratch/poly_gap_baseline_2026-08-25.json`](../scratch/poly_gap_baseline_2026-08-25.json)
(prod `rs-marketmaking`, summary SQL). Top actionable buckets that day:

| priority | occ (approx) | gap_reason | slug_prefix |
|----------|-------------:|------------|-------------|
| 0 | 15k | actionable wrong_prefix | bun (stale: tip had `bul`) |
| 1 | 152k | actionable path2_off | efl |
| 1 | 71k | actionable game-line gap | kor (Path 2 already on) |
| 1 | 23k | actionable game-line gap | itf |
| 1 | 7.8k | actionable path2_off | saf1 |
| 1 | 5.3k | actionable game-line gap | swe2 |
| 1 | 4.0k | actionable path2_off | crint |
| 1 | 2.4k | actionable path2_off | enl / efa / elc / … |

**2026-09-04:** `bun` is on `germany_bundesliga` (and `bul` on `bulgaria_parva_liga`).
The bun/bul special-case is removed. Unmapped `bun` RFQs are exact-score /
Yes-only No / 1H–2H period and corners residuals, not a prefix miss. Re-paste
Grafana from `--detail` / `--summary` so the panel stops showing P0
`actionable wrong_prefix`.

Compare **coverage ratio per prefix**, not raw occ — the rolling window
conflates RFQ volume drift with mapping change.

Regenerate:

```bash
python scripts/print_polymarket_gap_sql.py --summary --project rs-marketmaking --out scratch/poly_gap_baseline_2026-08-25.sql
$env:PYTHONPATH='.'; $env:GCP_PROJECT='rs-marketmaking'; python scripts/_tmp_poly_baseline.py
```

### Census note (same day)

Bulk census found ~80 unwired bridge prefixes that resolve to live Optic
leagues. Several prefixes previously filed as `optic_empty` (`kor`, `swe2`,
…) are already on the tip — residual volume there is stamp / Optic book,
not Path 2 off. See `--census` output and the same-day execution plan.
