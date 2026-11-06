# Terraform migration for market_mapping

How to move the `greg_sandbox.market_mapping` (and staging) tables
into the production Terraform-managed infrastructure.

## Background: what we have now (manual sandbox)

The sandbox tables live in `greg_sandbox` — a dataset Greg created by
hand in the BQ console. The schema is defined in
`BigQuery/sql/create-tables.sql` and the load pipeline is
`BigQuery/load_mappings.py`. Changes to the schema mean editing the
SQL file, dropping the table, re-creating it, and reloading.

Nothing about this is tracked in version control as infrastructure —
the SQL file is documentation, not a deployment artifact. There is no
CI gate, no plan/apply cycle, and no state tracking.

## Background: how the production infra works

All production BigQuery resources are defined in Terraform inside the
`mm-infrastructure` repo (`~/Dev/mm-infrastructure`). Key facts:

- **Terraform version**: 1.11.3, Google provider 7.13.0.
- **State backend**: GCS bucket `rs-marketmaking-terraform-state`,
  prefix `terraform/state/prod` (prod) or `terraform/state/test`
  (test).
- **CI/CD**: GitLab pipeline (`.gitlab-ci.yml`). Three stages:
  `terraform_init` → `terraform_plan` → `terraform_apply`. Apply is
  manual (requires clicking a button in the GitLab UI). Runs against
  prod on `main`, test on `test` branch.
- **Environments**: `prod.tfvars` (project `rs-marketmaking`) and
  `test.tfvars` (project `marketmaking-test`). Region for US
  resources is `us-east4` in both.
- **Module structure**: resources are grouped into modules under
  `modules/`. BigQuery datasets, tables, views, and scheduled queries
  all live in `modules/general_us/main.tf` (~2,200 lines). Schema
  JSON files live in `modules/general_us/schemas/<dataset>/`.

### How a Terraform table definition differs from raw DDL

In the sandbox, a table is a `CREATE TABLE` statement you run once.
In Terraform, a table is a *declared resource* — Terraform compares
the declaration to its recorded state and computes the diff each time
you run `terraform plan`. You never run DDL directly.

A typical BigQuery table resource looks like:

```hcl
resource "google_bigquery_table" "market_mapping" {
  dataset_id          = google_bigquery_dataset.opticodds_us.dataset_id
  table_id            = "market_mapping"
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "start_date"
  }

  schema = file("${path.module}/schemas/opticodds/market_mapping.json")
}
```

The schema is a separate JSON file listing every column with `name`,
`type`, `mode` (NULLABLE / REQUIRED), and optional `description`.
This is the BQ REST API schema format, not SQL DDL.

**Key differences from the manual process:**

| Concern | Sandbox (manual) | Terraform |
|---|---|---|
| Schema source of truth | `create-tables.sql` | `schemas/…/market_mapping.json` + HCL resource block |
| How changes are applied | Drop + recreate | `terraform plan` shows diff, `terraform apply` applies it |
| State tracking | None (just what's in BQ) | GCS state file records every attribute |
| Review gate | None | GitLab MR + plan output reviewed before apply |
| Rollback | Re-run old DDL manually | `git revert` + apply, or Terraform state manipulation |
| Partitioning / clustering | SQL keywords in CREATE | HCL blocks (`time_partitioning`, `clustering`) |
| Deletion safety | None | `deletion_protection = true` prevents accidental drops |

## What needs to happen

### 1. Choose a dataset → `markets_us`

`markets_us` — alongside `kalshi_markets` and the three Kalshi mapping
views (`kalshi_formatted_markets`, `kalshi_future_submapping_markets`,
`kalshi_optic_moneyline_mapping`).

The staging table (`market_mapping_stage`) goes in the same dataset.

### 2. Write the schema JSON file

Translate the columns from `BigQuery/sql/create-tables.sql` into BQ
REST API JSON format. Example for a few columns:

```json
[
  {"name": "start_date",  "type": "TIMESTAMP", "mode": "REQUIRED"},
  {"name": "home",        "type": "STRING",    "mode": "REQUIRED"},
  {"name": "source_ids",  "type": "JSON",      "mode": "NULLABLE"},
  {"name": "last_updated","type": "TIMESTAMP", "mode": "REQUIRED"}
]
```

Place the file at
`modules/general_us/schemas/markets/market_mapping.json`. The
staging table can reuse the same schema file.

### 3. Add the Terraform resource blocks

In `modules/general_us/main.tf`, add two
`google_bigquery_table` resources:

- **`market_mapping`** — partitioned by `DATE(start_date)` to match
  the current sandbox table. No clustering defined yet (the sandbox
  has none), but consider clustering by `sportsbook, game_id` to
  match query patterns. Set `deletion_protection = true`.
- **`market_mapping_stage`** — no partitioning (truncated each run).
  `deletion_protection = false`. Used by the main pipeline.
- **`market_mapping_stage_bq`** — same schema, also unpartitioned,
  `deletion_protection = false`. Private stage for the BQ-optic pipeline
  (`MAPPING_STAGE_TABLE`). Do not share one stage across both pipelines;
  see `BigQuery/docs/staging-isolation.md` in mmmapper.

Both reference the same schema JSON file.

### 4. Import existing data (if any)

If the sandbox table has data worth preserving, two options:

- **Terraform import**: `terraform import google_bigquery_table.market_mapping <project>:<dataset>.<table>`.
  This tells Terraform to adopt the existing table into its state
  without recreating it. Only works if the table is in the target
  dataset (not `greg_sandbox`).
- **Data migration**: create the new table via Terraform (empty),
  then `INSERT INTO new_table SELECT * FROM greg_sandbox.market_mapping`.
  This is simpler and more explicit.

### 5. Update the load pipeline

`BigQuery/load_mappings.py` currently hard-codes
`greg_sandbox.market_mapping` and `greg_sandbox.market_mapping_stage`.
Once the Terraform table exists, update `TABLE` and `STAGE_TABLE` to
point at the production dataset. The MERGE logic, schema read, and
bulk load remain the same.

### 6. GitLab MR workflow

1. Create a branch in `mm-infrastructure`.
2. Add the schema JSON + HCL resources.
3. Push and open a merge request.
4. The CI pipeline runs `terraform plan` — review the plan output to
   confirm it will create exactly two tables and nothing else.
5. Merge to `main`.
6. In the GitLab pipeline, manually trigger `terraform apply`.
7. Verify the tables exist in BigQuery.

### 7. Clean up the sandbox

After the production table is loaded and verified:
- Drop `greg_sandbox.market_mapping` and
  `greg_sandbox.market_mapping_stage`.
- Eventually drop the `greg_sandbox` dataset if nothing else uses it.
- Remove sandbox references from `BigQuery/docs/overview.md`.

## Existing patterns to follow

Look at how similar tables are defined in `modules/general_us/main.tf`:

- **`prices_dedup_state`** — unpartitioned, clustered by
  `[sport, league, market, game_id]`. No Pub/Sub subscription (populated
  by a scheduled MERGE query). Closest analogue to `market_mapping`.
- **`kalshi_markets`** (in `modules/kalshi_us/main.tf`) — market
  reference data, another non-streaming table.
- **Hot/cold pattern** (`rfq_latest` + `rfq_history`) — if we ever
  want to keep mapping history, this pattern exists. Not needed now.

## Risks and open questions

- **Schema evolution**: Terraform can add nullable columns to an
  existing table non-destructively. Adding REQUIRED columns or
  changing types requires table recreation (Terraform will show this
  in the plan). The sandbox schema should be finalised before the
  Terraform table is created.
- **Scheduled queries**: `prices_dedup_state` is populated by a
  scheduled MERGE query defined in Terraform. If `market_mapping`
  should be populated on a schedule (rather than by the Python
  pipeline), that query would also need a Terraform resource.
  Currently the Python pipeline is the only writer — no scheduled
  query needed.
- **Test environment**: should `market_mapping` also exist in the
  test project (`marketmaking-test`)? If so, the resource needs to
  be added to the module (it will be created in both envs
  automatically, since the module is called from both).
- **Permissions**: the load pipeline uses `ro_client()` for reads
  and `sandbox_query()` for writes to `greg_sandbox`. Production
  writes will need a service account with `bigquery.dataEditor` on
  the target dataset. Check what the existing pipeline service
  accounts have.
