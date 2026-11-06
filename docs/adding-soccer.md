# Adding Soccer Support

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

This file is the historical EPL/soccer wiring diary (2026-03). The
`mappers/leagues/`, `config/<league>/team_aliases.toml` and ticker-regex
steps below are gone. Today: soccer market vocab is
`mappers/vocab/soccer_markets.py`, parser profiles are
`mappers/profiles/soccer.py`, Kalshi market type comes from the typed
scope in `mappers/vocab/kalshi_scopes.py` and sides from `custom_strike`
(`strike_side` in `mappers/exchanges/kalshi.py`). Ship by MR with a test
in `tests/mappers/` and the `regression:mapping-gate` row delta.

The fetch pipeline is league-pluggable. Each fetcher dispatches through
per-league config objects (`KalshiConfig`, `PxConfig`, `OpticConfig`)
defined in `mappers/leagues/`. Adding soccer means creating a new league
config and wiring it in.

Kalshi's `_disambiguate_teams()` already handles 3-way moneylines
(win/loss/draw with TIE suffix filtering), so the hardest structural
problem is already solved.

## 1. Discover source IDs — DONE (EPL)

Discovered 2026-03-19.

### Optic

League ID: `england_-_premier_league`

133 market types on a single fixture.  Key ones for initial scope
(moneyline / spread / game total):

- `moneyline` — 3-way match result (27 odds entries)
- `total_goals` — game total (143 entries)
- `team_total` — per-team total (124 entries)

No `point_spread` in the NBA sense — soccer uses `asian_handicap`
(165 entries) and `goal_spread_3-way` (15 entries).

Rich player prop coverage: `player_goals`, `player_assists`,
`player_shots`, `player_shots_on_target`, `anytime_goal_scorer`,
`first_goal_scorer`, etc. — available for future expansion.

### Kalshi

Prefix: `KXEPL` — 13 series, ~200 open markets total (vs ~3,500
for NBA).

Per-game series and their ticker types:

| Ticker type | Title                          | Open  |
|-------------|--------------------------------|-------|
| GAME        | EPL Game (3-way moneyline)     | 24    |
| SPREAD      | EPL Spread                     | 32    |
| TOTAL       | EPL Total Goals                | 32    |
| 1H          | First Half Winner              | 24    |
| BTTS        | Both Teams to Score            | 8     |
| ANYGOAL     | Anytime Goalscorer             | 0     |
| FIRSTGOAL   | 1st Goalscorer                 | 0     |
| GOAL        | Goalscorer                     | 0     |

Season-long / non-game series (to be ignored at fetch time):

| Ticker type | Title                          | Open  |
|-------------|--------------------------------|-------|
| POY         | Player of the Year             | 0     |
| RELEGATION  | Relegation                     | 20    |
| TOP2        | Top 2 Finishers                | 20    |
| TOP4        | Top 4                          | 20    |
| TOP6        | Top 6 Finishers                | 20    |

### PX

**Not available.**  PX currently lists only Brazilian Serie A
(tournament_id=37) and Europa League (679) for soccer.  No EPL.
EPL will be a 2-source league (Optic + Kalshi).

## 2. Make PX optional in the pipeline — DONE

`League.PX` is now `PxConfig | None`.  The PX parse/classify block
in `pipeline.run()` is wrapped in `if px_cfg is not None:` with
`events` and `event_by_id` initialised as empty above the guard.
Downstream code already handles empty structures: the PX-schedule
matching loop iterates `events` (empty list = no-op), and row
building checks `e.px_event is not None`.

## 3. Create the league config — DONE

Added `mappers/leagues/epl.py` following the pattern in `nba.py`.

Soccer moneyline is 3-way (win/draw/loss), so `GAME` maps to
a new `MONEYLINE_3WAY` market type (`Shape.THREE_WAY`), not
`MONEYLINE`.  The existing `ThreeWayTicker` / TIE-suffix
handling in `kalshi.py` covers this.

Working assumptions (based on a small sample — verify as we go):

- **`game_ticker_re`**: EPL team codes appear to be 3 characters
  (LFC, TOT, CRY), matching NBA's fixed-width pattern.  One
  confirmed ticker: `KXEPLSPREAD-26MAR15LFCTOT-TOT2`.  Use the
  same 5-group regex as NBA until counterexamples surface.
- **`asian_handicap` → `POINT_SPREAD`**: Functionally equivalent
  (directional bet on winning margin, signed lines).  Existing
  `Shape.SPREAD` handling in `build_rows()` works as-is.
- **Kalshi SPREAD ↔ Optic `asian_handicap`**: One BQ record links
  `KXEPLSPREAD-…` to Optic `asian_handicap`.  The other candidate,
  `goal_spread_3-way`, is a different 3-way market.

## 4. Wire it up — DONE

- `fetch/__main__.py` — `epl` added to `--league` choices
- `fetch/kalshi.py` — `"epl": EPL_KALSHI` in `LEAGUES`
- `fetch/optic.py` — `"epl": "england_-_premier_league"` in
  `SUPPORTED_LEAGUES`
- `fetch/px.py` — now skips leagues without PX coverage instead
  of failing
- `mappers/run.py` — `"epl": epl.LEAGUE` in `LEAGUES`
- `infra/run_pipeline.sh` — `epl` added to cron fetch
- `mise.toml` — `epl` added to fetch task

## 5. Team aliases — DONE (empty)

Created `config/epl/team_aliases.toml` and
`config/epl/player_aliases.toml` (empty stubs).  Populate as
mismatches surface — no player props in initial scope.

## 6. Verify — DONE

Smoke-tested 2026-03-19 against one live fixture (BOU v MUN,
2026-03-20).  All three market types produced rows:

- `moneyline_3way`: 3 rows (BOU, MUN, _TIE), Kalshi matched
- `point_spread`: Optic asian_handicap lines from 0 to ±4,
  Kalshi SPREAD matched at half-point lines (±1.5, ±2.5)
- `game_total`: lines from 0.5 to 8.5, Kalshi TOTAL matched
  at half-point lines

19 Optic→Kalshi reconciliations agreed, 0 novel.  134 existing
tests pass.

## 7. Thread `sport_id` and `league_id` into BQ

The TF schema (`mm-infrastructure` commit 22c7c50) added
`sport_id` and `league_id` as REQUIRED canon key columns.
Both come from the Optic fixture data (`sport.id` and
`league.id`), e.g. `"soccer"` / `"england_-_premier_league"`.

Need to:
- Thread them from Optic fixture parsing through the pipeline
  into `CanonicalRow` (or the JSON serialization path)
- Add them to `flatten_rows()` in `BigQuery/load_mappings.py`
- Add them to `KEY_COLUMNS` in the MERGE key
- Update the sandbox staging table schema to match
