# synthetic/ — fixtures + mappings for ANY Kalshi market Optic has no fixture for

**General pipeline, not ITF-specific.** Mints our own fixture + mapping for Kalshi
markets **OpticOdds gives us no fixture for**, so the leg resolves to a fixture id
and can be priced off the Kalshi order book. Any sport/market Optic can't fixture
is in scope.

Three write surfaces, and they are **not** interchangeable:

| surface | what it does | required? |
|---|---|---|
| `opticodds_us.opticodds_fixtures` | the fixture itself (`wsdsyn-` id); also what the odds screen lists | always |
| `mapping-override-us` Pub/Sub | feeds `trading_us.prices_dedup_state` — **this is what makes a fixture priceable** | always |
| `markets_us.market_mapping` (GREG) | read by in-play registration only | only if `write_greg_rows` |

The override is the load-bearing one. GREG rows do **not** feed
`prices_dedup_state` (`prices_state_merge.sql` says so explicitly), and a leg maps
fine without one: with no GREG row the RFQ loader's `greg_fixture_id` is NULL and
its fixture join falls back to `f.game_id = c.game_id`, which resolves because a
synthetic fixture sets `id == game_id`. The manual F1/NASCAR fixtures wrote zero
GREG rows and took 210 confirmed bets. So set `write_greg_rows = false` unless the
series needs **in-play** — that also avoids the split-fixture exposure, which can
only occur when `greg_fixture_id` is non-NULL.

**What it runs on is data, not code — `series.toml`.** Add a `[[series]]` block to
onboard a new league/market; no code change. Live entries:

| series | shape | league | notes |
|---|---|---|---|
| `KXNASCARRACE` | `outright` | `Nascar` | Cup **and** O'Reilly Auto Parts, one series |

Tennis **doubles** (`KXITFDOUBLES`, `KXITFWDOUBLES`, and the never-onboarded
`KXATPCHALLENGERDOUBLES`) are intentionally OFF since 2026-10-20 (see `series.toml`).
`KXF1RACE` is staged but commented out — the builder handles it, the book is just
too thin to quote (see the block for the numbers).

Two market shapes, set by `market_type`:

- **`match_winner`** — 2 competitors, exactly 2 Kalshi markets, each with a
  `yes_sub_title`. `start_date` is 00:01 UTC on the day of the event's Kalshi
  milestone `start_date`; an event with no milestone is skipped.
- **`outright`** — N runners, one binary contract each (a race winner). Mapping
  rows are **yes side only** — contract X's yes is "X wins" and there is no other
  side to mirror. `start_date` comes from Kalshi's `expected_expiration_time`
  minus `start_bias_minutes`, because a race has no game milestone. A missing `expected_expiration_time` is the season-future
  signal and **rejects** the event — the opposite of the 2-way gate, which fails
  open.

The gate keeps us out of everyone else's lane automatically: we synthesize ONLY
events nothing else maps, so anything the ORIGINAL (Optic) or GREG pipelines
already cover is skipped. For an outright that check is all-or-nothing — one
already-mapped runner suppresses the whole race rather than leaving a field of 40
half-mapped.

Full design + rationale: `docs_workspace/proposals/2026-08-13-itf-synthetic-fixtures.md`.

## Onboarding a series

`series.toml` is the one place to onboard a series; it ships by MR like any
other mapping change (`CLAUDE.md`). These leagues stay **out of** mapper
`LEAGUES` — there is no Optic spine to classify against, and this job, not
the mapper, writes their rows.

The old step that copied synthetic leagues into the BigQuery tip
(`markets_us.mapping_leagues`, `fixture_source=synthetic`, via
`mappers/seed/synthetic_leagues.py` and `BigQuery.load_mapping_rules`) has been
deleted; do not re-seed. `PARSER_PROFILE_REGISTRY` in
`mappers/seed/profiles.py` still lists every synthetic `league_id`
(`itf_men_doubles`, `itf_women_doubles`, `Nascar`, `formulaone`; doubles now off); keep it in
step with `series.toml` until that seed code is removed.

## Coverage gate (per event)

1. **SKIP** — the ticker is already mapped by ORIGINAL (`prices_dedup_state`) OR GREG
   (`market_mapping`, non-`wsdsyn-` rows). Both require a real Optic fixture, which we
   must not duplicate. (`coverage.load_covered_tickers`.)
2. **SYNTH** — nothing maps it → mint a `wsdsyn-<event_ticker>` fixture (`status=live`,
   `start_date`=00:01Z match day) + 4 mapping rows onto it.

(A `BACKFILL` path — attach to a real Optic fixture instead of minting one — exists
behind `SyntheticSeries.allow_backfill`, default **OFF**: no-fixture events have nothing
to attach to, and a false-match — e.g. a doubles player's same-day singles fixture —
would mis-route.)

**Reconcile is scoped to our own rows only** — the delete/prune keys on
`game_id LIKE 'wsdsyn-%'`, NEVER on the ticker prefix, so it can never wipe the GREG
pipeline's real singles rows in the same table. And because it's delete-then-insert,
an event self-retires the moment GREG/Optic starts covering it (next run the gate
skips it → it isn't re-inserted → our stale row drops).

Identity is the Kalshi ticker+side (settled Kalshi-side); names are read from
`yes/no_sub_title` for display only, so same-surname collisions (`-KOF`/`-KOF2`)
are a non-problem.

## Run

```bash
# read-only, reports the gate breakdown, no writes:
GCP_PROJECT=marketmaking-test .venv/bin/python -m synthetic.run --dry-run
# live (test first) — runs every series in series.toml:
GCP_PROJECT=marketmaking-test .venv/bin/python -m synthetic.run
# smoke-test one series / a custom config:
... -m synthetic.run --only KXITFDOUBLES --dry-run   |   --config path/to/series.toml
```

`--only` **requires `--dry-run`** and refuses to write. Every reconcile step is
scoped by `wsdsyn-` game_id rather than by series, so a single-series write run is
a mass teardown of the series it did *not* run: `reconcile_mappings` blanket-deletes
all synthetic GREG rows then re-inserts only that series', `reconcile_fixtures`
flips the rest to `status=completed`, and `publish_overrides` set-diffs against the
full published set and retracts them.

Reconcile is idempotent: each run deletes our `wsdsyn-`/managed-prefix rows in the
window and re-inserts the desired set; events that left Kalshi's open set are
flipped `status=completed` (drops them off the odds screen); rows older than the
window are pruned.

## Files

- `series.toml` — the series to run on (onboard a new league/market here, no code).
- `adapters.py` — `SyntheticSeries` + `load_series()`. The Kalshi market ticker is carried
  as an opaque id, never parsed.
- `coverage.py` — `load_covered_tickers` (ORIGINAL∪GREG skip set), fixture matcher.
- `writers.py` — row builders + idempotent BQ reconcile (fixtures + mappings) +
  `publish_overrides` (mapping_override Pub/Sub publish — the pricing step).
- `run.py` — orchestrator CLI. Each pass does THREE reconciles: fixtures →
  `market_mapping` (GREG) → **`mapping_override`** publish. The override step is what
  makes the leg actually price: GREG rows are invisible to the Kalshi orderbook price
  pipeline (it reads `mapping_override` → `prices_dedup_state`), so without it legs
  fall back to 1.0. `--dry-run` reports the override count without publishing.
- `inplay_pause.py` — **run MANUALLY, never scheduled.** Pauses / unpauses in-play
  betting on a `wsdsyn-` fixture by publishing fixture-scope `market_betting_pause`
  messages to every in-play tenant (`--tenant` to narrow, `--unpause` to lift), the
  same wire shape as the retired console's Fixture Pause. Dry run unless `--apply`; refuses
  non-synthetic ids. No registration step exists any more: synthetic legs are in-play
  eligible through the tenant's `allowed_sports` like any other (Release 080, &101).
  There is deliberately **no wrapper script and no cron** — nothing switches synthetic
  in-play betting on or off by itself, and that is the intended posture.
- `publish_overrides.py` — publishes `mapping_override` messages for our synthetic
  markets so the **Kalshi orderbook price pipeline** actually prices them (it reads
  `mapping_override`/`prices_dedup_state`, NOT the GREG `market_mapping` we write —
  see `docs_workspace/synthetic_inplay_pricing.md`). Dry-run by default; `--publish`
  to send; prod prompts. **Validate in test first** (silent-drop paths in
  `docs_workspace/mapping/overrides.md`). Not yet wired into cron — run deliberately.
- Cron: `infra/run_itf_synth.sh` + `infra/cron_itf_synth.sh`; schedule in `infra/crontab`
  (`10-59/15`, i.e. :10/:25/:40/:55 — clear of both pipeline crons). Runs on the
  mmmapper VM like the other crons. Overlapping ticks are skipped (`logs/synthetic.lock`,
  non-blocking flock, exit 0) so two delete-then-append writes cannot double
  `market_mapping` keys.

## Prerequisites / caveats (before enabling)

- **IAM: no grant needed.** The mapper VMs (`market-mapping-test` /
  `market-mapping`) run as their project's default compute SA
  (`201519232184-compute@` test / `639515744749-compute@` prod), which already holds
  `roles/editor` (BQ write on all tables) + `secretmanager.secretAccessor` (the Kalshi
  keys). The only write-side change required was the code-side guard
  (`BigQuery/client.WRITABLE_DATASETS`, already updated). (Relying on broad `editor`
  isn't least-privilege, but it's the existing estate posture — same way the mapper
  already writes `market_mapping`.) We do NOT write
  `opticodds_mapping` (and need no IAM on it): the Kalshi in-play mapper reads
  `market_mapping` directly, and the scheduled `prices_state_merge.sql` (step 5)
  already folds `market_mapping` GREG rows into `opticodds_mapping` for other consumers.

- **Visibility:** no audit table — everything the job touches is queryable from the
  live tables via the `wsdsyn-` id tag (fixtures and mappings); freshness = `MAX(publish_time)` on the `wsdsyn-` fixtures. Per-run
  gate counts are in `infra/logs/synthetic.log` (+ Slack on failure). A Grafana
  dashboard can read these directly.
- **In-play RFQ service must run `use_greg=True`** (else it never sees our GREG
  rows) and have `tennis` in `ALLOWED_SPORTS`.
- **Enablement** needs no registration: a synthetic leg is in-play eligible through
  the tenant's `allowed_sports` like any other. To stop one, use `inplay_pause.py`.
- **Safety** is real-time in the pricing layer (order-book liquidity filters in
  `MMutils.handlers.fair_price_calculator` refuse a one-sided/thin/wide book), NOT
  the `status→completed` teardown, which is housekeeping only.
- Canonical `home/away/selection/side` on the mapping rows are best-effort display
  names; the load-bearing fields for in-play are `source_ids`(ticker+side) →
  `game_id`/`fixture_id`.
- Reconcile delete+insert is not atomic; the sub-second gap is below the mapper's
  30-min / odds-screen's 60-s refresh, so it's tolerable (could move to MERGE later).
