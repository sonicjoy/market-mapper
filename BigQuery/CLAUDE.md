# CLAUDE.md — `BigQuery/`
Root rules and deploy facts: `../CLAUDE.md`. No new tables in `rs-marketmaking` without asking.

## Purpose
Everything that reads or writes BigQuery for the mapper: loading `markets_us.market_mapping`, venue raw-fetch loaders, the oom fold, alert checks, gap SQL.

## Entry points
| File | Role |
|---|---|
| `load_mappings.py` | stage table + MERGE key, deletes, override lane, post-load ALERT checks; duplicate-key guard (`:46-52`) |
| `client.py` | `bq_client`; refuses DML outside `markets_us` / `opticodds_us` / sandbox (`:33`) |
| `load_<venue>_raw.py`, `load_exchange_fetch.py`, `exchange_fetch_*.py` | raw `*_fetch_raw` ticks (replayed by the regression gate) |
| `oom_fold_rank.py`, `sql/oom_fold_rank.sql`, `oom_winner_query.py` | folds `market_mapping` into `opticodds_us.opticodds_mapping`; load-bearing (cronjob ships with the console) |
| `override_lane.py`, `activate_mapping_rule_set.py`, `mapping_rule_rows.py` | legacy tip / override paths; no new use |
| `alerts.py`, `mapping_run_audit.py`, `optic_crosscheck_*.py` | post-run checks and Slack alerts |
| `sql/`, `docs/` | gap and coverage SQL; `docs/market_mapping_schema.md`, `docs/overview.md` |

## Test
`GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q tests/BigQuery` (BQ is mocked; nothing hits prod).

## Gotchas
- `load_mappings` reads its schema from the stage table; do not create tables to change it.
- A new sportsbook must be replayed through the loader, not only `mappers.run`: a duplicate key froze test mapping for every book (2026-09-24).
- Joining `market_mapping` with `opticodds_mapping`: split on `mapping_source` or you double count.
- `ai_validation*` is suspended (VM cron removed, GKE CronJob `suspend: true`).
