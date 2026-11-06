# Exchange fetch canary (prod)

Run after mm-infrastructure applies the `raw_ingestion_us.*_fetch_raw` tables
and before flipping `MAP_SNAPSHOT_SOURCE=bq` on the mapping VM.

## Preconditions

1. Terraform applied on `marketmaking-test`, then `rs-marketmaking`
2. `load_exchange_fetch` STEP succeeds on recent ticks
3. `MAP_SNAPSHOT_SOURCE` still `jsonl` (default) until checks pass

## Pipeline log checks

From `logs/pipeline.log` on the mapping VM:

```bash
grep 'STEP name=load_fetch' logs/pipeline.log | tail -20
grep 'STEP name=map ' logs/pipeline.log | tail -20
grep 'STEP name=map_league' logs/pipeline.log | tail -50
grep '^ALERT: reconcile' logs/pipeline.log | tail -20
```

Success criteria:

- `load_fetch` completes in under ~120s (non-fatal WARN if slower; investigate)
- `map` wall time drops vs pre-change baseline (~815s on 2026-08-19 sample)
- Offseason 0-row leagues (`nba`, `nhl`, `ncaab`) `map_league` drops from ~130s
- No increase in `skip: previous pipeline run still active`
- `reconcile` ALERT rate ~0 after tables exist

## BigQuery checks

Provenance (Tier A) on new writes:

```sql
select
  count(*) as rows,
  countif(mapping_run_id is not null) as with_run_id,
  countif(mapped_at is not null) as with_mapped_at,
  countif(mapper_git_commit is not null) as with_commit
from `rs-marketmaking.markets_us.market_mapping`
where last_updated >= timestamp_sub(current_timestamp(), interval 1 day);
```

Fetch snapshot load (after first successful tick):

```sql
select snapshot_id, count(*) as rows
from `rs-marketmaking.raw_ingestion_us.optic_fetch_raw`
where fetch_time >= timestamp_sub(current_timestamp(), interval 1 day)
group by 1
order by 1 desc
limit 10;
```

## Flip to BQ hydrate

When canary is green for 24h on test, then prod:

```bash
# infra/ensure_env.sh or .env on mapping VM
MAP_SNAPSHOT_SOURCE=bq
```

Keep JSONL writes enabled; reconciliation still compares JSONL ↔ BQ.

## Rollback

```bash
MAP_SNAPSHOT_SOURCE=jsonl
```

Map immediately falls back to file reads (no redeploy needed beyond env).
