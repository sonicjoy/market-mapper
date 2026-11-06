# Milestone 1 — infra schema + seed (mmmapper)

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

**Status for the team / agents:** [`docs/mapping-rules/m1-status.md`](mapping-rules/m1-status.md)
(roadmap, query recipes, Slack announce, hard “don’t activate” rules).

Companion to `mm-infrastructure` M1 mapping-rules schema (applied on test + prod).

## This repo

- `mappers/seed/` — extract IR from live `LEAGUES` + TOML, parity checks, audit helpers
- `scripts/seed_mapping_rules_from_code.py` — write local snapshot JSON / `--check`
- `BigQuery/mapping_rule_rows.py` — IR → BigQuery row shapes (pure, unit tested)
- `BigQuery/load_mapping_rules.py` — load a shadow snapshot into `markets_us`
- `BigQuery/load_mappings.py` — MERGE value columns include nullable provenance fields
  (populated in later milestones / when rule_set is active)

## Commands

```powershell
python scripts/seed_mapping_rules_from_code.py --out .tmp/mapping_rules_s0.json
python scripts/seed_mapping_rules_from_code.py --check --league ufc --allow-incomplete-profiles
python -m pytest tests/mappers/test_seed_extract.py tests/BigQuery/test_mapping_rule_rows.py -q

# Shadow load (never activates)
$env:GCP_PROJECT="marketmaking-test"
python -m BigQuery.load_mapping_rules --environment test --dry-run
python -m BigQuery.load_mapping_rules --environment test
```

`rule_set_id` is content-addressed (`S0_<sha12>`), so re-running after a config
change produces a new snapshot and re-running unchanged is a no-op. The tables
are append-only; superseded snapshots stay as history and are never activated.

Companion infra notes (Terraform apply order) live in mm-infrastructure
`modules/general_us/docs/mapping-rules-m1.md` (local; `**.md` is gitignored there).

## Nothing goes live until activation

`mapping_rule_current` reads only `rule_set_activated` / `rule_set_rolled_back`
events. The seed writes `rule_set_seeded` (`status='shadow'`), so the live
mapper keeps using the Python path until M2 flips it.

## Apply order

1. Apply mm-infrastructure M1 Terraform on **test**
2. Seed shadow `S0` on test and verify counts — **do not activate**
3. Promote infra to prod, then seed `--environment prod`
4. Wire full `PARSER_PROFILE_REGISTRY` for all leagues (seed warns until complete)
