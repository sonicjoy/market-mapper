# STX (Ontario exchange) in the mapping tick

STX lists typed markets and carries no Optic ids, so STX maps the DKEX / Underdog way: the typed fields decide, the
Optic row supplies the ids, nothing is parsed. The offline profile (`mappers/exchanges/stx*.py`) decides every side
of every market; this page is what runs it in the tick and what a maker reads.

## Where it runs

| Step | Where | Gate |
|---|---|---|
| Fetch `stx_markets.jsonl`, `stx_event_players.jsonl` | `fetch/stx.py`, spawned by `python -m fetch` (`fetch/__main__.py`) in the 15-minute tick on the mapper VM (`infra/cron_pipeline.sh` -> `run_pipeline.sh`) | `STX_ENV` in the VM's `.env`: `infra/ensure_env.sh` sets `demo` on `marketmaking-test`, nothing on `rs-marketmaking` (no STX fetch on prod) and the league list must hold an STX run-set league |
| Key | Secret Manager in `GCP_PROJECT`: `stx-api-key-id`, `stx-private-key`; the VM's compute service account has the project-wide accessor role on both projects. PEM goes to the SDK in memory, never printed or written | `stx-python==0.8.0` in `requirements.txt` |
| Map | per league in `mappers/pipeline.py` (`stx_attach.run_league`), after the Underdog pass | a failure prints `stx [league]: FAILED` and skips STX rows only |
| Load | `BigQuery/load_mappings.py` -> `markets_us.market_mapping`, sportsbook `STX` | the same MERGE, key and cleanups as every book |
| Snapshot for the gate | `BigQuery/load_exchange_fetch.py` -> `raw_ingestion_us.stx_fetch_raw`, `stx_players_fetch_raw` (CREATE_NEVER, Terraform-owned; skipped while missing) | `regression/materialize.py` reads them as optional tables |

Run-set leagues that STX feeds: the competitions in `stx_leagues.COMPETITIONS` with a `slug` (NFL, NCAAF, NBA, NHL,
Serie A, MLB held). A league with no run-set entry (ISL, AFC, cricket) maps nothing. NHL must exist as a league in the
tip / `LEAGUES` before its STX rows can land.

## What lands

One row per side (YES and NO) of every STX market whose canonical bet an Optic row prices:
`sportsbook = 'STX'`, the Optic `fixture_id`, `market_id`, `selection`, `selection_line`, `points`, `game_id`,
`grouping_key` of that row, and

```
source_ids = {"market_id": <STX market_id>, "selection_id": "yes" | "no", "event_id": <STX event_id>,
              "tie_pays_half": true | false}
```

Two STX markets can be one canonical bet (YES `home_winner` and NO `away_winner` are both the home team), so STX is
keyed `market_id|selection_id` like Kalshi, DKEX and Underdog (`_source_identity_sql`, `_TICKER_KEYED_BOOKS`); the second
one is a satellite (`stx_satellite`) that load emits alone. A market whose specifier or fixture changes re-keys the
row; `stale_book_rows.relabeled_ticker_where` deletes the old row so a `(market_id, selection_id)` never resolves twice.

## What the maker does

Look up by `(market_id, selection_id)`, the Underdog contract (`mm-underdogrfq/.../mmmapper_source.py`):

```sql
SELECT JSON_VALUE(source_ids, '$.market_id') AS stx_market_id, JSON_VALUE(source_ids, '$.selection_id') AS side,
       JSON_VALUE(source_ids, '$.tie_pays_half') AS tie_pays_half,
       fixture_id, market_id, selection, selection_line, points, line, side AS canonical_side, market_type
FROM `<project>.markets_us.market_mapping`
WHERE start_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR) AND start_date < TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND sportsbook = 'STX' AND fixture_id IS NOT NULL AND market_id IS NOT NULL
```

No row is an unmapped leg (never map in the maker). **`tie_pays_half` is `'true'` -> refuse the leg**; a row where the key
is absent is not one this mapper wrote -> refuse as well. Until the pricer prices P(win) + 0.5 * P(tie) the maker
refuses every flagged leg.

## Legs that can settle at half

Only the 2-way winner (`home_winner` / `away_winner`) can: STX settles it `push` at `max_price / 2` when the game ends
level (`docs/stx/_captures/docs-pages/concepts__market-shape.md:266-268`). Totals and handicaps are half-number lines,
"a totals or handicap market cannot end level and there are no pushes on them" (`:346-347`); a 3-way pays the draw as
its own market. Per mapped competition (rules templates in `docs/stx/data_samples/2026-10-28-mapping-trial/
description_templates.json`):

| Competition | `tie_pays_half` | Why |
|---|---|---|
| NFL | true | "If the game ends in a tie, the market will resolve to $X for each team" |
| NBA | true | a second basketball template says "In case of a draw we result into a push"; an NBA game cannot end level, flagged until STX answers |
| NCAAF | false | "A college football game is played to a winner, so this market cannot end in a tie" |
| NHL | false | "including overtime and any shootout" |

Every STX leg, flagged or not, can also settle at a fair price when the game does not conclude or a player does not
play (`description_templates.json`: "the market will resolve to a fair market price"). That is not a row property; the
maker's caps and the settlement reporter own it.

## Counts

Each league prints one line: `stx [nfl]: 16/16 events joined; stamped N, satellite N, dropped_no_optic N; unmapped by
reason: family_held N, event_started N, ...`. `stx_unmapped.<league>.jsonl` in the tick's data dir lists every refused
side with its reason (the dir is pruned after a day). Markets whose competition has no run-set league are not seen by
any league pass.

## First live run (marketmaking-test, 2026-10-29, Ontario demo)

`python -m fetch` with `STX_ENV=demo` -> 9,289 open markets and 74 rosters in 30 s (1 of 75 prop events answered
`event not found` on its roster: skipped, its props map as `no_roster`) -> `mappers.run` on nfl / ncaaf / nba /
italy_serie_a -> `load_mappings`: 3,619 rows in `markets_us.market_mapping`, 3,619 distinct `(market_id, selection_id)`.
Per league the tick line reads, e.g. `stx [nfl]: 13/14 events joined; stamped 2982, satellite 26, dropped_no_optic 914`.
NHL is not in the test run set, so no NHL row can land there.

## Prod: Ontario proxy

STX production accepts Ontario source IPs only; the mapper VM (`market-mapping`, us-east4) is not one. Set
`STX_HTTPS_PROXY=http://<Toronto Squid>:3128` in the VM `.env` next to `STX_ENV=prod`: `fetch/stx.py` passes it to
`AsyncSTX(transport=httpx.AsyncHTTPTransport(proxy=...))` (`_proxy_kwargs`), so only the STX REST calls use it. Never
set `HTTPS_PROXY` on the VM: Squid refuses everything except `.stxapp.ca:443`. Unset = direct (demo on test).
`infra/ensure_env.sh` leaves both keys alone on prod (it rewrites only the keys it names).
