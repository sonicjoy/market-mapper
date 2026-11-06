# BigQuery rule-set tip (legacy)

**Audience:** mmmapper developers and AI agents working in this repo.

**Mapping rules are code.** New leagues, market types, vocab, venue league
ids and aliases go in Python, ship by MR and pass the regression gate. See
[`CLAUDE.md`](../../CLAUDE.md). This page only describes the legacy BigQuery
tip so you can recognise it and move rules off it. It is not a place to put
rules, and there are no supported propose / approve / activate steps.

## Status

The "rules as data" milestones (M1–M5, 2026-08) moved classify onto an
activated BigQuery rule-set snapshot (the "tip"). That design is retiring.
Today the mapper **still loads the tip**, which is migration debt:

- `mappers/seed/sot.py` `load_snapshot()` returns the tip, COW-coalesced. It
  reads the offline fixture named by `MAPPING_SOT_FIXTURE` when set, else
  BigQuery through `mappers.control_plane.bq_store.BigQueryStore`.
  `mappers/run.py`, `mappers/pipeline.py` and the provenance modules call it.
- `infra/ensure_env.sh` still writes `MAPPING_SOT=bq` on the test and prod
  mapper VMs.
- Tests use `tests/fixtures/sot/tip.json` (set by `tests/conftest.py`).
- The regression live gate exports the tip once with
  `scripts/build_sot_fixture.py` and runs both engines on that file, so a
  gate delta is always a code change.
- Other tip readers: `mappers/seed/tip_*.py`, `mappers/seed/tip_alignment.py`.

When you touch code that reads the tip, move the rule it reads into code.
Where a code-owned table and the tip both define something, the code table
wins (merge it last).

## Legacy tables

All in `markets_us`; the project is the environment (`marketmaking-test` =
test, `rs-marketmaking` = prod). DDL lives in mm-infrastructure
(`modules/general_us/schemas/markets/mapping_*.sql`).

| Table / view | Role |
|---|---|
| `mapping_rule_sets` | Snapshot receipt (`rule_set_id`, `parent_rule_set_id`, counts) |
| `mapping_leagues` | League + exchange settings / parser profiles |
| `mapping_market_rules` | Taxonomy map/ignore rules per sportsbook |
| `mapping_entities` | Teams/players/fighters + aliases; `canonical_name` for display |
| `mapping_audit_events` | Seed / activate / gap / decision stream |
| `mapping_work_items` | Console inbox |
| `mapping_rule_current` | The activated rule set |
| `mapping_rule_validity` / `mapping_rule_validity_windows` | Per-rule on/off history |
| `mapping_entities_current` | Materialised current entities (convenience only) |

Rule-set ids: `S0_*` are seed snapshots, `P_*` are console proposal layers.
Storage is copy-on-write: a `P_*` layer holds only the keys it changed (plus
tombstones); the logical snapshot is tip → root, last write wins.

Do not add rows to any of these tables, and do not run
`BigQuery/activate_mapping_rule_set.py` as a fix.

## Reading what the mapper loaded (read-only)

Useful when you are moving a rule into code and need to see what the tip
says today. Never `join latest using (rule_set_id)` on content tables: walk
`parent_rule_set_id`, last write wins. Keep the depth guard at 500 (BigQuery's
recursion ceiling); a lower cap silently returns a partial tip.

```sql
-- Logical crypto.com market rules for the newest tip (COW coalesce)
with recursive
lineage as (
  select rule_set_id, parent_rule_set_id, 0 as depth
  from (
    select rule_set_id, parent_rule_set_id
    from `markets_us.mapping_rule_sets`
    order by created_at desc
    limit 1
  )
  union all
  select s.rule_set_id, s.parent_rule_set_id, lineage.depth + 1
  from `markets_us.mapping_rule_sets` s
  join lineage on s.rule_set_id = lineage.parent_rule_set_id
  where lineage.depth < 500
),
ranked as (
  select r.*,
         row_number() over (
           partition by r.league, r.sportsbook, r.source_key_type, r.source_key
           order by lin.depth
         ) as rn
  from `markets_us.mapping_market_rules` r
  join lineage lin using (rule_set_id)
)
select * except (rn)
from ranked
where rn = 1
  and ifnull(tombstone, false) = false
  and sportsbook = 'crypto.com'
order by league, action, source_key;
```

Entities use the same lineage, partitioned by
`league, entity_type, canonical_key`, with `unnest(aliases)`.

## Code map (legacy)

| Path | Purpose |
|---|---|
| `mappers/seed/sot.py` | Loads the tip for the mapper |
| `mappers/seed/fixture_store.py` | Offline tip fixture reader |
| `mappers/seed/bq_snapshot.py`, `tip_*.py` | Tip readers / builders |
| `BigQuery/mapping_rule_rows.py` | IR → BQ row shapes |
| `BigQuery/activate_mapping_rule_set.py` | Legacy activate CLI; do not use as a fix |
| `scripts/build_sot_fixture.py` | Exports the tip for tests and the regression gate |
| `docs/mapping-coverage-grafana.md` | Grafana SQL: `market_mapping` inventory |
