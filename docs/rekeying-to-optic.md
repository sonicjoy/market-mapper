# Rekeying market_mapping to Optic's natural key

## Background

The `market_mapping` BQ table currently uses a 9-column custom merge
key:

```
(start_date, home, away, market_type, entity, line, side, group, sportsbook)
```

This key was designed to be human-readable and Optic-independent — it
describes a bet in our own terms.  In practice it has caused significant
complexity:

- **Reschedule handling.**  `start_date` is part of the key, so any
  time shift (even minutes) means the MERGE inserts a duplicate instead
  of updating.  This required `_clean_reschedules()` in
  `load_mappings.py`: two detection passes, 80+ lines of code and
  comments, and ongoing maintenance risk.

- **league_id gap.**  Without `league_id` in the key, NBA and NCAAB
  rows with the same `(start_date, home, away, ...)` would collide.
  Adding `league_id` means a 10th key column, ALTER TABLE, pipeline
  changes, and a full reload.  Same argument for `sport_id` when soccer
  is added.

- **Double-header gap.**  MLB double-headers need time-of-day
  disambiguation.  (Kalshi's game now comes from its typed milestone,
  joined in `mappers/pipeline.py`; the ticker is never read for a date.)  The
  custom key makes this our problem; Optic's `game_id` already
  distinguishes the two games.

Meanwhile, the downstream consumer (`mapping_loader.py` in MMkalshi)
ignores our key entirely.  Its `greg_raw` CTE reads `game_id`,
`market_id`, `selection`, `selection_line`, `points`, and `source_ids`
— all Optic identifiers — and joins to `prices_dedup_state` on Kalshi
`source_ids` and to `opticodds_fixtures` on `game_id`.  Our key
columns (`home`, `away`, `market_type`, etc.) are never referenced.


## Optic's natural key

### The `odd.id` composite

Every Optic odd has an `id` field with three colon-separated parts:

```
{game_id}:{market_id}:{selection_slug}
```

Examples:

```
34537-29249-2026-03-07:player_assists:seth_trimble_over_3_5
11464-48840-2026-03-09:total_points:over_210_5
35142-24860-2026-03-08:moneyline:duke
35142-24860-2026-03-08:point_spread:duke_-16
```

The `selection_slug` encodes `(normalized_selection, selection_line,
points)` into a single string.  `odd.id` is unique per odd within a
game, and since `game_id` is unique across leagues and sports, `odd.id`
is globally unique.

### Decomposed form

The same information lives in structured fields on the Odd model
(`mappers/exchanges/optic.py`):

| Field | Example | Notes |
|---|---|---|
| `game_id` | `34537-29249-2026-03-07` | Unique per game across all leagues/sports |
| `market_id` | `player_assists` | Market type slug |
| `selection` | `Seth Trimble` | Entity name; empty string for game totals |
| `selection_line` | `over` / `under` / `null` | Side for totals/props; null for moneylines |
| `points` | `3.5` / `null` | Line value; null for moneylines |

These five fields are unique per odd in all observed data — **except
for H2H player props**.

### The H2H exception: grouping_key is needed

H2H markets pit two players against each other (e.g. "Stephon Castle
vs Scottie Barnes — who gets more assists?").  Both sides of the bet
can share the same `(market_id, selection, selection_line, points)`:

```
market_id = player_assists_h2h_moneyline
selection = stephon_castle
points    = null
```

If Castle appears in two matchups (vs Barnes AND vs Quickley), the
5-tuple collides.  The only distinguishing field is `grouping_key`:
`"scottie_barnes_stephon_castle"` vs
`"immanuel_quickley_stephon_castle"`.

For all non-H2H markets, `grouping_key` is redundant with the other
fields (e.g. `"default:217.5"` just restates the line, `"jalen_duren:5.5"`
restates entity + line).  See `mappers/docs/add-grouping-key.md` for
the full analysis.

### The full Optic key (decomposed, 7-column)

Including `grouping_key` for H2H correctness and `sportsbook` for our
per-exchange row design:

```
(game_id, market_id, selection, selection_line, points, grouping_key, sportsbook)
```

7 columns.  All already exist in the BQ table — they just need to be
reclassified from value columns to key columns.

**However, empirical testing revealed this decomposed key is
problematic — see "Verification results" below.**


## Stability: game_id and reschedules

`game_id` format is `{num1}-{num2}-{date}`, e.g.
`18107-33911-2026-02-14`.  The numeric pair is stable across
reschedules; the date suffix is not.

- **Same-day time shifts** (game moves from 7pm to 9pm): `game_id`
  stays the same.  MERGE updates correctly.  No cleanup needed.
  This is the common case — 27 out of 27 observed reschedules across
  953 games and 55 fetches kept their `game_id` (verified 2026-03-16).

- **Cross-date reschedules** (game moves to a different day):
  `game_id` changes (date suffix shifts).  MERGE inserts a new row;
  old row persists as a stale duplicate.  This is rare but real
  (documented: `18107-33911-2026-02-14` → `18107-33911-2026-02-25`).

Compared to the current custom key, where ALL reschedules (including
same-day time shifts) cause duplicates, Optic keying eliminates the
common case entirely.  Cross-date reschedules still need cleanup, but
`_clean_reschedules` Pass 2 (Kalshi ticker match) may be all that's
needed — Pass 1 (game_id match with different start_date) becomes
irrelevant since game_id IS the key.


## What changes

### Key columns (new)

```
game_id, market_id, selection, selection_line, points, grouping_key, sportsbook
```

### Value columns (kept for readability and ad-hoc queries)

```
start_date, home, away, market_type, entity, line, side, group,
fixture_id, source_ids, last_updated
```

Plus new informational columns that become trivial to add:

```
league_id, sport_id
```

These no longer need to be in the key — `game_id` is already globally
unique across leagues and sports — but are valuable for filtering and
human readability.

### Reschedule handling (simplified)

The current two-pass `_clean_reschedules` can be reduced.  Pass 1
(join on `game_id` with different `start_date`) becomes unnecessary
because `game_id` is now the key — same `game_id` means MERGE updates
in place.  Only cross-date reschedules (different `game_id`, same
logical game) need detection, and Pass 2 (Kalshi ticker match) handles
those.

### Downstream consumer (mapping_loader.py)

No change needed.  It already reads Optic fields, not our key columns.

### Pipeline output (canonical_row_to_json)

No structural change to the JSONL format.  The same Optic fields are
already emitted under `optic_odds`.  `flatten_rows` in
`load_mappings.py` already extracts them.  The change is in which
columns the MERGE matches on.


## What this does NOT solve

- **Cross-date reschedules** still produce stale duplicates (different
  `game_id`).  Some form of cleanup remains necessary, though the
  scope is much narrower.

- **Optic dependency.**  If Optic changes their ID scheme, the key
  breaks.  But this is already true at the system level — the entire
  pipeline (fixtures, odds, source_ids, joins to prices_dedup_state)
  depends on Optic.  The custom key provided theoretical independence
  that didn't exist in practice.


## Verification results

`scripts/verify_optic_key.py` tested five assertions across 71
`optic_fixtures_odds.jsonl` files (740,927 odds total, covering NBA,
NCAAB, NHL, soccer, and UFC data from 2026-02 through 2026-03).

### CHECK 1 PASS: odd.id is unique per game

No two odds within the same game share the same `id`.  This is the
baseline: `odd.id` is a reliable unique identifier.

### CHECK 2 FAIL: decomposed 6-tuple has 48 intra-file duplicates

48 cases where two odds in the **same file** share the same
`(game_id, market_id, selection, selection_line, points, grouping_key)`.

Root cause: stale odds from reschedules.  When a game is rescheduled
(e.g. Howard/UMBC from 03-16 to 03-17), the parent Game object's
`game_id` is updated to `38843-26699-2026-03-17`, but some odds still
carry the old date in their `odd.id`:

```
Game.game_id:  38843-26699-2026-03-17  (updated)
odd[0].id:     38843-26699-2026-03-17:moneyline:umbc  (fresh)
odd[1].id:     38843-26699-2026-03-16:moneyline:umbc  (stale)
```

Since the 6-tuple takes `game_id` from the parent Game (not from the
odd's `id`), both odds map to the same tuple.  Using `odd.id` directly
avoids this — the stale and fresh odds have different `id` values.

### CHECK 3a FAIL: selection and grouping_key are unstable

740,927 unique `odd.id` values vs 740,772 unique 6-tuples (155
discrepancy).  Same `odd.id` maps to different structured field values
across fetches because **Optic mutates display names**:

```
odd.id (stable):  ...player_points_either_:giannis_antetokounmpo_+_keyonte_george_over_29_5
  fetch 1:  selection = "Giannis Antetokounmpo + Keyonte George"
            grouping_key = "giannis_antetokounmpo_+_keyonte_george:29.5"
  fetch 2:  selection = "G. Antetokounmpo + Keyonte George"
            grouping_key = "g_antetokounmpo_+_keyonte_george:29.5"
```

The slug in `odd.id` stays `giannis_antetokounmpo_...` regardless,
but the `selection` display name and `grouping_key` (which contains
the normalized name) both change.  This means `selection` and
`grouping_key` **cannot be used as key columns** — successive loads
would create duplicates when Optic flips a display name.

Observed for: Giannis Antetokounmpo ↔ G. Antetokounmpo, Shai
Gilgeous-Alexander ↔ S. Gilgeous-Alexander, and similar long-name
players in combo/either prop markets.

### CHECK 3b FAIL: slug is more stable than structured fields

244 cases where the same slug maps to different `(selection,
selection_line, points, grouping_key)` tuples across fetches.  All
from the same display-name instability as 3a.  Confirms the slug is
the stable identifier; the structured fields are derived and mutable.

### CHECK 3c FAIL: slug encodes H2H matchup identity

9,061 cases where the same `(selection, selection_line, points)` maps
to different slugs.  These are all H2H markets where the slug encodes
the matchup pairing:

```
selection = "Klay Thompson", points = None, selection_line = None

slug 1: klay_thompson_sam_hauser_--_klay_thompson
slug 2: klay_thompson_payton_pritchard_--_klay_thompson
```

The slug carries the opponent identity (the `--` separated pair) which
`(selection, selection_line, points)` cannot express.  This confirms
that `grouping_key` is needed if using decomposed fields — or that the
slug alone carries sufficient discriminating power.


## Key finding: the slug is the real key

The slug (third component of `odd.id`) is the atomic identifier for a
selection within a `(game_id, market_id)` context:

- **Stable across fetches** — unlike `selection` and `grouping_key`
  display fields, which Optic mutates.
- **Encodes H2H identity** — unlike the decomposed structured fields,
  which collide on H2H markets.
- **Not cleanly decomposable** — `_` is overloaded as word separator,
  decimal point (`3_5` = 3.5), and implicit field boundary.  Parsing
  it back into structured fields would be fragile.

The decomposed 7-column key proposed earlier is therefore not viable.
The structured fields are useful as value columns (for human
readability and ad-hoc queries) but cannot serve as a stable merge key.


## How the downstream consumer sidesteps all of this

The mapping_loader (`MMkalshi/services/rfq_consumer_v0/mapping_loader.py`)
keys on neither our custom key nor Optic's key.  Its effective key is
**Kalshi's own identifiers**: `market_ticker:side` (from `source_ids`).

The `greg_raw` CTE (mapping_loader.py:40–53):

```sql
SELECT
    STRING(gmp.source_ids.market_id) as market_ticker,
    STRING(gmp.source_ids.selection_id) as side
    ...
FROM greg_sandbox.market_mapping gmp
WHERE sportsbook = 'Kalshi'
```

The FULL OUTER JOIN to `original_raw` is on `market_ticker + side`.
The JOIN to `fixtures` is on `game_id`, but only as a filter/enrichment
join (to get `start_date`, `sport`, `league`), not as a uniqueness key.

This means:

- Our custom key columns (`home`, `away`, `market_type`, etc.) are
  never read by the consumer.
- Optic's `selection`, `grouping_key`, even `odd.id` are never read.
- The consumer is immune to display-name instability, the H2H
  problem, and the stale-odd problem because it uses exchange
  `source_ids` as its join path.
- `game_id` instability on cross-date reschedules could affect the
  fixtures join, but in practice the consumer only looks at future
  games (`start_date >= CURRENT_TIMESTAMP`), so stale old-date rows
  age out naturally.


## Decision: keep the custom key, add league_id and sport_id

After investigating Optic rekeying options (A: opaque `odd_id`, C:
hybrid `game_id + slug`), the conclusion is that the complexity
trade-off is not worth it.  The current custom key's main cost is
reschedule handling, but:

- The reschedule code already works and handles both same-day and
  cross-date cases.
- Optic keying would eliminate same-day reschedule handling but
  introduce a new stale-odd filtering problem (CHECK 2) that the
  current approach doesn't have.
- The net complexity is similar — just different.

The real gap in the current key is `league_id`: without it, NBA and
NCAAB rows could collide on `(start_date, home, away, ...)`.  Adding
`league_id` and `sport_id` as key columns closes this gap with
minimal disruption.

### Downstream consumer impact

**No breakage.**  The mapping_loader keys on `source_ids`
(`market_ticker:side`), not on our key columns.  It SELECTs specific
named columns; two new columns in the table are invisible to it.
Same for the Grafana coverage dashboard — it reads named columns, not
`SELECT *`.

### Options considered but rejected

**Option A: `(odd_id, sportsbook)` — 2-column opaque key.**
Simplest key, proven unique and stable.  Rejected because: fully
opaque (can't query by market type or game), introduces the stale-odd
problem (CHECK 2), and Optic dependency is total — if Optic changes
`odd.id` format, the key breaks with no fallback.

**Option C: `(game_id, odd_slug, sportsbook)` — 3-column hybrid.**
`game_id` is queryable, slug carries full selection identity.
Rejected for similar reasons: slug is opaque, stale-odd problem
persists, and the slug's `_`-overloaded encoding makes it
non-decomposable for human queries.


## Migration plan (revised 2026-03-20)

The original plan assumed adding columns to the existing
`greg_sandbox.market_mapping` table in place, requiring a complex
backfill/cleanup sequence (disable cron, ALTER TABLE, delete orphans,
backfill league_id/sport_id from fixtures, assert zero NULLs, then
deploy code changes).  That plan is superseded by the Terraform
approach below.

### Why the backfill plan is no longer needed

The `mm-infrastructure` repo defines the `market_mapping` and
`market_mapping_stage` tables as Terraform resources in
`modules/general_us/main.tf`, targeting the `markets_us` dataset
(not `greg_sandbox`).  Terraform creates fresh, empty tables with
the full schema — including `league` (REQUIRED) and `sport`
(REQUIRED) from the start.  No existing data means:

- No orphan cleanup needed.
- No backfill from `opticodds_fixtures`.
- No NULL-gate before code deployment.
- No cron disable/re-enable dance.
- Both columns can be NOT NULL (REQUIRED) since there's no legacy
  data to accommodate.

The `greg_sandbox` tables remain as-is for dev/ad-hoc use.  They
are not migrated — the new `markets_us` tables are populated fresh
by the pipeline.

### Phase 1: Infrastructure (Terraform) ✅ DONE

MR !71 (`market_mapping_tables` branch) merged to `test`.  Terraform
created empty `markets_us.market_mapping` and
`markets_us.market_mapping_stage` tables with the full schema
including `sport`, `league`, and `group_key`.

`market_mapping` is partitioned by `start_date` (with required
partition filter) and clustered on `(sportsbook, sport, league,
game_id)`.  `market_mapping_stage` has no partitioning or clustering
(bulk-truncated each load).

### Phase 2: Code changes (market-mapping repo) ✅ DONE

**Step 4: Pipeline — emit sport and league.** ✅

League and Sport enums in `mappers/leagues/__init__.py` derive sport
from league via a static mapping.  `CanonicalRow` gained a `league`
field, threaded through all `build_rows` call sites.
`canonical_row_to_json` emits `sport` and `league` in the JSONL key
block.  `load_mappings.py` adds both to `KEY_COLUMNS` and
`flatten_rows`.  Test fixtures regenerated.

**Step 5: Rename group → group_key.** ✅

`group_key` in `KEY_COLUMNS`, `NULLABLE_KEYS`, and `flatten_rows`
in `load_mappings.py`.  Backtick-quoting comment removed from
`test_merge.py`.

**Step 6: Cut create-tables.sql.** ✅

Deleted — Terraform is the source of truth for table creation.

**Step 7: Point TABLE/STAGE_TABLE at `markets_us`.** ✅

`load_mappings.py` now targets `markets_us.market_mapping` and
`markets_us.market_mapping_stage`.  `client.py` gained
`WRITABLE_DATASETS` (greg_sandbox + markets_us) and a
`GCP_PROJECT` env var (default `rs-marketmaking`, overridden to
`marketmaking-test` via `.env`).

**Step 7b: Partition-filter compliance.** ✅

`markets_us.market_mapping` has a required partition filter on
`start_date`.  Queries that used subqueries as partition bounds
(reschedule detection, MERGE, post-merge duplicate check) were
rewritten to inject date literals computed in Python.
`RescheduleCleanup.delete_sql` gained an explicit
`DATE(start_date) IN (...)` clause — the tuple IN alone didn't
satisfy BQ's partition filter check.

### Phase 3: Test load + verify

**Step 8: Load to `marketmaking-test` from laptop.** ✅

Full fetch + load against `marketmaking-test` from local.
12,123 rows across 3 dates (2026-03-19 to 2026-03-21).
`destructive_test_merge.py` (renamed from `test_merge.py`)
passes all 9 steps including a new reschedule detection test.
Added a prod safety guard that refuses to run against
`rs-marketmaking`.

**Step 9: E2E test on VM against `marketmaking-test`.** ✅

Spun up a dedicated VM (`market-mapping-test`) in the
`marketmaking-test` project rather than granting the prod VM's SA
cross-project access (would have required Owner-level IAM, which
was unavailable).  The test project's default compute SA already
had `bigquery.jobUser` + `editor` via Terraform.

During setup, discovered `GCP_PROJECT` was hardcoded to
`rs-marketmaking` in all fetch scripts.  Fixed by reading from
`os.environ["GCP_PROJECT"]` with no default — forces explicit
configuration via `.env` on every VM.  Same change applied to
`client.py`.

Full fetch → pipeline → load ran cleanly.  14,444 rows across
4 dates (2026-03-19 to 2026-03-22).  Zero duplicate keys.
Second load confirmed idempotent MERGE — no new rows, no
duplicates, no reschedules detected.

Test VM stopped (not deleted) for future use.

**Step 10: Verify downstream consumer.** ✅

Ran the `greg_raw` CTE from `mapping_loader.py` (MMkalshi)
against `marketmaking-test.markets_us.market_mapping`.  Returns
valid `market_ticker` and `side` values.  The consumer keys on
`source_ids`, not our key columns, so no breakage.  Only change
needed in MMkalshi: update the table reference from
`greg_sandbox.market_mapping` to `markets_us.market_mapping`.

### Phase 4: Promote to prod

**Step 11: Update `mapping_loader.py` in MMkalshi.**

Two changes needed in `KALSHI_MARKET_MAPPING_QUERY` (line 50):
1. Dataset: `greg_sandbox` → `markets_us`.
2. Project ID: `rs-marketmaking` is hardcoded in the fully
   qualified table reference
   (`FROM \`rs-marketmaking.greg_sandbox.market_mapping\``).
   Needs to become configurable or updated for both test and
   prod environments.

Verify in the test GKE environment against
`marketmaking-test.markets_us` (data already there from Step 9).

The `markets_us.market_mapping` table has a required partition
filter on `start_date`.  Verify that all queries in
`mapping_loader.py` include a `start_date` predicate or they
will fail at runtime.

Open question (posted to Slack 2026-03-20): can/should we test
`mapping_loader` in the test GKE environment before prod?
Deployment workflow for MMkalshi's test environment is unclear
(no `test` branch on origin as of 2026-03-20).  Coordinate with
Dom.

**Step 12: MR in mm-infrastructure targeting `main`.**

Creates `markets_us.market_mapping` and
`markets_us.market_mapping_stage` in `rs-marketmaking` (prod)
via Terraform.  Same schema as the test tables from MR !71.

**Step 13: Cut `epl` from `run_pipeline.sh`.** ✅

EPL support held back from initial prod deployment.

**Step 14: Prod VM cutover.**

1. Disable cron.
2. `git pull` (gets HEAD: `markets_us` targeting,
   `GCP_PROJECT` env var, no `epl`).
3. Run one fetch + load manually.
4. Verify `markets_us.market_mapping` is populated (row counts,
   no duplicate keys).
5. Re-enable cron.

Requires Step 12 (prod tables exist).

**Step 15: Update dashboards.**

Price Coverage Analysis dashboard (and any others) references
`greg_sandbox.market_mapping`.  Audit all Grafana/Looker
dashboards for `greg_sandbox` references and update to
`markets_us`.  Verify all dashboard queries include a
`start_date` partition filter — `markets_us.market_mapping`
requires one.

**Step 16: Deploy `mapping_loader` change to prod.**

Merge the MMkalshi change to `main` and deploy to prod GKE.
At this point prod `markets_us` is populated and being
refreshed by cron.  `greg_sandbox` data remains available
as fallback until decommissioned.

Depends on wider team: Dom's team handles MMkalshi prod
deploys.
