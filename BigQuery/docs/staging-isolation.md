# Per-pipeline staging isolation (RESOLVED 2026-08-14)

**Problem:** the main pipeline (`infra/run_pipeline.sh`, `*/15`) and the
BQ-optic pipeline (`infra/run_pipeline_bq.sh`, `5,20,35,50`) both called
`BigQuery.load_mappings`, which hard-coded a single staging table
`markets_us.market_mapping_stage`. The two crons run on **different locks**
(`pipeline.lock` vs `pipeline_bq.lock`) precisely so they can overlap, and the
5-minute offset is only a hope — the BQ optic pull is unbounded in duration and
the main tick's pre-fetch bridge step can push its fetch minutes later.

When the two loads overlapped, they shared one mutable batch buffer:

1. `load_mappings` bulk-loads the batch into the stage with `WRITE_TRUNCATE`,
   so one run's load wipes the other run's staged rows.
2. Between the load and the MERGE, several steps re-`SELECT` from the stage
   (`stage_dates`, `stage_leagues`, reschedule/stale cleanup) and can observe a
   different run's contents.
3. The `MERGE ... USING market_mapping_stage` has no league predicate — it
   merges whatever is in the stage at that instant.
4. `markets_us.market_mapping` has **no enforced unique constraint** (BigQuery
   does not support them), so two overlapping MERGEs can each take the
   `WHEN NOT MATCHED THEN INSERT` path for the same key and write **exact
   duplicate rows**.

The post-MERGE uniqueness guard (`_assert_no_duplicate_keys`, scoped only by
`start_date` partition, not by league) then aborts the run with
`FATAL: N+ duplicate key groups in markets_us.market_mapping`.

## Evidence (2026-08-14)

- Duplicate groups were Polymarket `cs2` / `lol` moneylines. Each pair was a
  byte-identical row (same clob token, same `source_ids`, same `last_updated`
  `2026-08-14T06:54:31Z`) — an exact double INSERT, not two twin tickers.
- Only keys **new** to that write doubled; pre-existing cs2/lol rows stayed
  unique.
- BigQuery `INFORMATION_SCHEMA.JOBS_BY_PROJECT` showed two LOAD+MERGE pairs one
  minute apart on the same stage: 06:53 (BQ pipeline, ~229 KB, 0 inserted) and
  06:54 (main pipeline, ~7.8 MB, 715 inserted). The alert fired at 06:54:57.

The alert naming Polymarket was incidental: the guard audits every league in
the touched date partitions, so a BQ-soccer run can report a main-pipeline
Polymarket insert.

> Note: this is distinct from the ITF-doubles / Kalshi dup-key case (two
> legitimate complementary Kalshi tickers per canonical side), which was fixed
> by extending the source identity in the MERGE key. Same FATAL text, different
> root cause.

## Fix

A staging table is owned by exactly one load for the duration of
load -> assert -> cleanup -> MERGE. It must not be shared between concurrent
pipelines (nor between overlapping ticks of the same pipeline).

- `BigQuery/load_mappings.py` reads the stage from `MAPPING_STAGE_TABLE`
  (default `markets_us.market_mapping_stage`).
- `infra/run_pipeline_bq.sh` exports
  `MAPPING_STAGE_TABLE=markets_us.market_mapping_stage_bq`, so the BQ-optic
  pipeline stages into its own table.
- The main pipeline keeps the default stage.
- `TABLE` (`markets_us.market_mapping`) stays **shared**: both pipelines write
  disjoint league rows into it through a key-scoped MERGE. Only the *stage*
  must be private.

Overlapping ticks of the *same* pipeline are still serialized by that
pipeline's flock, so each stage still has a single writer at a time.

## Create the BQ stage table

Terraform owns this table in `mm-infrastructure`
(`modules/general_us/main.tf` → `google_bigquery_table.market_mapping_stage_bq_us`),
mirroring `market_mapping_stage` (same `schemas/markets/market_mapping.sql`, no
partitioning, `deletion_protection = false`). Apply that change in
`mm-infrastructure` before deploying a mapper VM that points the BQ pipeline at
`MAPPING_STAGE_TABLE=markets_us.market_mapping_stage_bq`.

Until Terraform has been applied in an environment, you can bootstrap with:

```sql
create table markets_us.market_mapping_stage_bq
like markets_us.market_mapping_stage;
```

`load_mappings` reads its schema from the stage table at run time, so the two
stages must stay schema-identical; cloning from the existing stage (or applying
the Terraform resource that shares the same schema file) guarantees that.

## One-shot cleanup of existing duplicates

Remove the exact-duplicate rows already merged into prod before/at the incident.
Rows are identical across the full key + source identity, so keep one per group:

```sql
delete from markets_us.market_mapping t
where t.start_date in (
  select start_date
  from markets_us.market_mapping
  group by sport, league, start_date, home, away, market_type, entity, line,
           side, group_key, sportsbook, to_json_string(source_ids)
  having count(*) > 1
);
```

Prefer the scoped, group-aware delete used by the guard rather than a blanket
partition delete; confirm the exact recovery statement against the current
`_assert_no_duplicate_keys` identity before running in prod.

## Do NOT

- Do not serialize the whole pipelines under one lock — that reintroduces the
  never-runs starvation the split was created to fix.
- Do not point both pipelines back at one stage table.
- Do not remove the 5-minute cron offset assuming the MERGE alone makes overlap
  safe; overlap is safe only with private stages.
