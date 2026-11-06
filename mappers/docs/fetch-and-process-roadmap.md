# Fetch-and-Process Roadmap

## Context

Up to now Nick has zipped and sent data files manually.  We need to
fetch, store, and process them ourselves — and push mapped output to
BigQuery instead of emitting JSON to stdout.

## Current state

### Data layout (legacy)

The pipeline currently expects a flat directory per game-date with
four files under `data/<league>/<game-date>/`.  This will change —
see Phase 1 below.

### Fetch scripts (Nick's originals)

Three independent fetches, each hitting a different exchange API:

1. **Optic** — `scripts/fetch_optic.py` (ours).  Fetches fixtures
   starting within N days, strips volatile fields (price, timestamp,
   limits, order_book).  Currently writes per-league to
   `DATA_DIR/<league>/<date>/<HH_MM>/`.

2. **Prophet X** — `scripts/nick/market_mapping_prophetx.py`.  Uses
   internal `MMProphetx` package.  Fetches events by tournament ID,
   then markets per event, strips price fields from selections.

3. **Kalshi** — `scripts/nick/market_mapping_kalshi.py`.  Uses
   internal `MMkalshi` package.  Fetches markets by series ticker,
   strips to structural keys.

### Pipeline

`python -m mappers.run <league> <data_dir> [--json | --table]` merges
all three sources into canonical rows.  The natural dedup key is:

    (date, home, away, market_type, entity, line, side)

## What changes between fetches?

The pipeline strips prices, so what remains is structural:

- **New markets/selections appear** — exchanges add lines as game day
  approaches, especially player props.
- **Lines can move** — e.g. a spread shifts from −3.5 to −4.5.  This
  produces a new row (different `line` value), not an update.
- **Markets can close/disappear** — less common pre-game.
- **The mapping itself** (which PX line = which Kalshi ticker = which
  Optic odd) is stable — it's based on game + market type + entity +
  line + side, not on prices.

Fetching more often primarily captures new markets.  Existing mappings
don't change.

## Plan

### Phase 1: Run locally (short term)

#### Architecture

An **orchestrator** calls three exchange-specific fetchers as
subprocesses.  All live under `fetch/` at the repo root, runnable
via `python -m`:

    fetch/__main__.py             # orchestrator
    fetch/optic.py                # sync, requests
    fetch/kalshi.py               # sync, requests (RSA-PSS auth)
    fetch/px.py                   # sync, requests (Bearer token auth)

#### Directory layout

All exchanges write to a single timestamped directory.  All leagues
are mixed into one file per exchange:

    data/<date>/<HH_MM>/
      optic_fixtures_odds.jsonl
      kalshi_markets.jsonl
      prophetx_events.jsonl
      prophetx_markets.jsonl

The date/time reflect when the fetch happened, not game dates.
The orchestrator creates the directory and dies if it already
exists (no overwriting).

#### Orchestrator (`fetch/__main__.py`) — DONE

    python -m fetch --league nba ncaab --out-dir data
    python -m fetch --league nba --out-dir data --minimal

- Takes `--out-dir` (required) as the top-level data directory
  and creates a timestamped `<out-dir>/<date>/<HH_MM>/` subdir.
  Dies if the subdir already exists.
- Passes `--league` and `--out-dir` through to each fetcher —
  exchange-specific knowledge (series tickers, tournament IDs)
  stays in the individual fetch scripts, derived from mapper
  config.
- `--minimal` passes `--max-items 3` to each fetcher for
  smoke testing.  Each fetcher also accepts `--max-items N`
  directly for standalone use.
- Reports failures and exits non-zero if any fetcher fails.

#### `fetch/kalshi.py` — DONE

    python -m fetch.kalshi --league ncaab nba --out-dir <path>

- **Does not use `MMkalshi`.**  That package logs every request
  to prod GCP Pub/Sub and pulls in heavy dependencies (aiohttp,
  GCP handlers).  Instead we implement Kalshi's RSA-PSS auth
  directly (~15 lines using `cryptography`) and use `requests`.
  Credentials come from GCP Secret Manager via `gcloud` CLI.
- **Series opt-in from overlayed config.**  `series_tickers()` keeps
  discovered series whose root is in overlayed `table_types` (Python
  factory + tip `map` pins), plus `extra_series`, plus conference
  tournament series when `is_tournament_series()` applies.  Tip
  `ignore` pins still skip.  Unmapped suffixes (awards, sibling
  prefixes) stay unfetched until the tip maps or ignores them.
- One `GET /markets?series_ticker=X&status=open` call per
  series; paginates via cursor (max_pages=1000 safety cap,
  matching MMkalshi).
- Rate-limited: 100ms sleep after every API call in
  `kalshi_get()`, applied universally.
- Strips each market to 14 structural keys (matching Nick's
  original output): event_ticker, ticker, title, subtitle,
  yes_sub_title, no_sub_title, market_type, status,
  created_time, open_time, close_time,
  expected_expiration_time, rules_primary, rules_secondary.
  Guards against missing keys — dumps the full record to stderr
  and raises `KeyError` naming the missing fields.
- Writes all markets to a single `kalshi_markets.jsonl`.

##### Design decisions and learnings

- **Dynamic discovery rejected.**  `GET /series?category=Sports
  &tags=Basketball` returns all basketball series (~247), but
  prefix filtering (`KXNBA*`) matches ~106 including futures,
  drafts, awards — far more than the mapper needs.  Deriving
  from `table_types` is simpler and stays in sync automatically.
- **NCAAB old prefix (`KXNCAAB*`).**  Kalshi has series under
  both `KXNCAAB` (older) and `KXNCAAMB` (current) prefixes.
  The mapper config uses `KXNCAAMB` only, so we only fetch
  those.  If old-prefix markets are needed, add their ticker
  types to the NCAAB `KalshiConfig.table_types`.
- **Market availability varies by timing.**  Some market types
  (1H spread/total, player blocks/steals) show 0 open markets
  well before game time.  Kalshi publishes these closer to
  tip-off.  This is expected — fetching more frequently (or
  closer to game time) captures them.

#### `fetch/optic.py` — DONE

    python -m fetch.optic --league nba ncaab --out-dir <path>

- Credentials from GCP Secret Manager via `gcloud` CLI (same
  pattern as Kalshi and PX — no `MMutils` dependency).
- Accepts `--out-dir` (required) from the orchestrator.
- Writes all leagues to a single `optic_fixtures_odds.jsonl`.
- `--days` controls the fixture window (default 1 = 24 hours).
- Volatile field stripping uses `.pop(field, None)` — tolerates
  fields being absent (API changes don't crash the fetch).
- Pagination: supports both `has_more` (new) and `total_pages`
  (old) — cutover scheduled for March 10 at 5pm ET.

#### `fetch/px.py` — DONE

    python -m fetch.px --league nba ncaab --out-dir <path>

- **Does not use `MMProphetx`.**  Same rationale as Kalshi: the
  package logs every HTTP request to prod GCP Pub/Sub via its
  base `HTTPClient`, and pulls in heavy dependencies (aiohttp,
  google-cloud-pubsub, google-cloud-logging, fastapi, uvicorn).
  Instead we use `requests` with simple Bearer token auth.
  Credentials come from GCP Secret Manager via `gcloud` CLI.
- **Auth:** `POST /partner/auth/login` with access_key +
  secret_key, returns a Bearer token used on all subsequent
  requests.  Simpler than Kalshi's RSA-PSS — no token refresh
  needed for a short-lived fetch script.
- **Tournament IDs from mapper config.**  `PxConfig.tournament_id`
  is the single source of truth (NBA=132, NCAAB=648).  This
  replaced the previous `sport`/`tournament` string fields —
  `parse_event` now filters on the integer ID directly.
- **No pagination needed.**  The PX `get_sport_events` and
  `get_markets` endpoints return full results (confirmed by
  inspecting `MMProphetx` source — only `get_wager_histories`
  uses cursor pagination).
- Fetches events per tournament, then markets per event.
- **Injects `sport_event_id`** onto each market record (matching
  Nick's MMProphetx client) — the PX API doesn't include it in
  market responses, but it's needed to join markets to events.
- **Retries with backoff.**  `px_get` retries up to 3 times with
  exponential backoff (1s, 2s) on transient HTTP failures.
- **API-level error handling.**  If `get_sport_events` or
  `get_markets` returns a response with an `"error"` field,
  logs a warning and returns `[]` — skips that item rather than
  crashing the run.  Matches Nick's client behaviour.
- PX API has no status or date filters; returns all events for
  the tournament, including completed ones.
- Strips 5 volatile fields from each selection (display_odds,
  odds, stake, value, updated_at), matching Nick's original
  `market_mapping_prophetx.py` output.
- Writes `prophetx_events.jsonl` and `prophetx_markets.jsonl`.

#### Schedule

Run on a local schedule (cron / launchd), every 4 hours (settable),
for games in the next 24 hours.  Pipeline reads from `data/` and
pushes mapped output to BigQuery.

### Phase 2: BigQuery output

Replace `--json` / `--table` stdout output with BigQuery writes.

Proposed flat table schema:

| Column             | Type      | Key? |
|--------------------|-----------|------|
| `date`             | DATE      | yes  |
| `home`             | STRING    | yes  |
| `away`             | STRING    | yes  |
| `market_type`      | STRING    | yes  |
| `entity`           | STRING    | yes  |
| `line`             | FLOAT64   | yes  |
| `side`             | STRING    | yes  |
| `px_line_id`       | STRING    |      |
| `kalshi_ticker`    | STRING    |      |
| `kalshi_side`      | STRING    |      |
| `kalshi_title`     | STRING    |      |
| `px_market_name`   | STRING    |      |
| `px_selection`     | STRING    |      |
| `optic_id`         | STRING    |      |
| `optic_fixture_id` | STRING    |      |
| `optic_game_id`    | STRING    |      |
| `optic_market_id`  | STRING    |      |
| `optic_selection`  | STRING    |      |
| `fetched_at`       | TIMESTAMP |      |

Each fetch-and-map cycle inserts all rows with the current timestamp.
Downstream consumers dedup on the 7-column key, taking the latest
`fetched_at`.

### Phase 3: Cloud Run (medium term)

- **Compute:** Cloud Run Job triggered by Cloud Scheduler every 4h.
  Container runs the unified fetch + pipeline, exits when done.
  Zero cost when idle.
- **Raw file storage:** GCS bucket mounted via Cloud Storage FUSE.
  Code sees a normal filesystem path (`/mnt/data/nba/2026-03-06/...`).
  Works well for our access pattern (write a few JSONL files, read
  them back).  No code changes vs local — only the data directory
  path differs.
- **Mapped output:** Straight to BigQuery as in Phase 2.

Keeping raw files in GCS lets us re-run the pipeline on historical
fetches as we iterate on the mapping logic.

## Open questions

1. **Kalshi API: markets filtering and series list.**  RESOLVED.
   `GET /markets` can only filter by `series_ticker`.  We
   explored dynamic discovery via `GET /series?category=Sports
   &tags=Basketball` but rejected it — returns ~247 series,
   most irrelevant.  Instead we derive series from the mapper's
   `KalshiConfig.table_types`, which is the single source of
   truth for which ticker types we process.

2. **Kalshi API: pagination.**  RESOLVED AND IMPLEMENTED.
   Cursor-based pagination in `fetch_markets()`, max_pages=1000
   safety cap (matching MMkalshi).  API default page size is 200.

3. **Fetch window.**  RESOLVED.  Optic's `--days=1` gets active
   fixtures starting within 24 hours.  Kalshi filters to open
   markets only (`status=open`); we tried `max_close_ts` (now +
   1 day) but Kalshi's close times are settlement deadlines
   (~2 weeks out), not game times, so no markets matched.
   Reverted to status-only filtering.  PX API has no status or
   date filters — returns all events for the tournament.

4. **PX tournament IDs.**  Now in `PxConfig.tournament_id`
   (NBA=132, NCAAB=648).  Are these stable season to season?

5. **Downstream dedup strategy.**  Inserting full snapshots every 4h
   means the BQ table grows fast.  Options: (a) `MERGE` / upsert on
   the 7-column key so the table only holds the latest mapping,
   (b) append-only with a view that deduplicates, (c) partition by
   `fetched_at` date and let consumers filter.  Depends on query
   patterns.

6. **Game lifecycle.**  When does a game's mapping become "final"?
   After tip-off?  After the game ends?  Should we stop fetching
   for in-progress games, or let the pipeline handle it naturally?

7. **Error handling / alerting.**  If a fetch fails (API down, auth
   expired), what should happen?  Retry?  Alert?  Skip and try next
   cycle?

8. **Optic source_ids.**  The pipeline currently collects
   `source_ids` from Optic odds (which embed Kalshi and PX IDs when
   available).  These provide a cross-check on our mapping.  Should
   we store these in BQ for validation, or are they only useful
   during development?

## Next steps

1. Set up cron/launchd schedule.
2. Integrate pipeline to read from the new directory layout.
3. BigQuery output (Phase 2).
