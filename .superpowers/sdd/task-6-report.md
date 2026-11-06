### Task 6 report: Wire parity soccer leagues — EPL + WORLD_CUP

**Status:** complete, not blocked.

**Shared `market_types` dict (deliverable #1):** added
`SOCCER_MARKET_TYPES: dict[str, MarketType]` in `mappers/exchanges/polymarket.py`,
directly above `soccer_market_rules`, with the exact 9-key set from the
Task-5 report (`total`, `team_total`, `spread`, `first_half_total`, `btts`,
`first_half_btts`, `moneyline_3way`, `first_half_winner_3way`,
`player_goals`). Both league configs below reference this ONE constant —
no per-league copy. Task 5 had not created it yet (only inlined the same
dict in the test file's `ALL_SOCCER_CFG` fixture, left untouched).

**Wiring:**
- `mappers/leagues/world_cup.py` — `POLYMARKET = PolymarketConfig(slug_prefix="fifwc", optic_league_id="fifa_-_world_cup", market_types=SOCCER_MARKET_TYPES, question_style="mlb_suffix", market_rules=soccer_market_rules)`; wired into `LEAGUE = LeagueConfig(...)` as `POLYMARKET=POLYMARKET`.
- `mappers/leagues/epl.py` — same shape, `slug_prefix="epl"`; wired into `LEAGUE` the same way.

**EPL slug-prefix caveat (flagged per brief):** `slug_prefix="epl"` is
**BEST-GUESS, UNVALIDATED**. EPL is off-season as of 2026-07-22 (0 rows in
the July poly position↔token bridge), so the actual bridge slug could not
be confirmed against live data the way `"fifwc"` was for World Cup. `"epl"`
mirrors the Kalshi `KXEPL` / PX / Optic naming convention. If wrong, it is a
harmless silent no-op: `mappers/pipeline.py`'s
`market.slug.startswith(pcfg.slug_prefix + "-")` filter (line ~1571) simply
matches zero bridge rows — no false mapping, just zero EPL poly coverage
until corrected. Flagged in-code with a prominent comment above
`epl.py`'s `POLYMARKET` block. Re-validate against a live bridge snapshot
when the EPL 2026-27 season opens (~Aug 2026).

**Map-vs-drop cross-check against each league's existing `OpticConfig.table_types`**
(the reviewer's concern — a `MarketType` optic never priced for that league
has no existing optic row for `pipeline.attach_polymarket_row` to stamp
onto, so the poly row is dropped there, "dropped_no_optic", never invented
standalone; `market_types.get()` itself no longer gates this since it's now
a shared dict with every key always present):

- **WORLD_CUP — maps ALL 9 MarketTypes / all 11 rules.** Confirmed every
  key resolves against `world_cup.OPTIC.table_types`:
  `moneyline`→`MONEYLINE_3WAY`, `asian_handicap`→`POINT_SPREAD`,
  `total_goals`→`GAME_TOTAL`, `team_total`→`TEAM_TOTAL`,
  `player_goals`→`PLAYER_GOALS`, `1st_half_moneyline`→`FIRST_HALF_WINNER_3WAY`,
  `1st_half_total_goals`→`FIRST_HALF_TOTAL`,
  `both_teams_to_score`→`BTTS`, `1st_half_both_teams_to_score`→`FIRST_HALF_BTTS`.
  Every one of the 9 keys is present — nothing drops for optic-coverage
  reasons (a market can still drop per-fixture if optic simply hasn't
  priced that specific game/line, but no *form* is structurally excluded).

- **EPL — maps 3 of 9 MarketTypes / 5 of 11 rules (Kalshi-parity set).**
  `epl.OPTIC.table_types` only has `moneyline`→`MONEYLINE_3WAY`,
  `asian_handicap`→`POINT_SPREAD`, `total_goals`→`GAME_TOTAL`. So:
  - **MAP:** `soccer_total_rule` (GAME_TOTAL), `soccer_spread_rule`
    (POINT_SPREAD), `soccer_ml_team_win_rule` + `soccer_ml_draw_rule`
    (both MONEYLINE_3WAY) — 4 rules / 3 MarketTypes live.
  - **DROP** (parse fine, no optic row to stamp onto):
    `soccer_team_total_rule` (TEAM_TOTAL), `soccer_first_half_total_rule`
    (FIRST_HALF_TOTAL), `soccer_btts_rule` (BTTS),
    `soccer_first_half_btts_rule` (FIRST_HALF_BTTS),
    `soccer_first_half_leader_rule` + `soccer_first_half_draw_rule`
    (FIRST_HALF_WINNER_3WAY), `soccer_player_goals_rule` (PLAYER_GOALS) —
    7 rules / 6 MarketTypes dropped, by design (optic doesn't price these
    forms for EPL yet — dropping unpriced forms is intended behavior, not a
    bug; do NOT edit `OpticConfig.table_types` per the brief, that's a later
    wave).

  Rule-count check: 4 live (`ml_team_win`+`ml_draw` both count toward the
  MONEYLINE_3WAY pair) + 7 dropped (`first_half_leader`+`first_half_draw`
  both count toward the FIRST_HALF_WINNER_3WAY pair) = 11 rules total,
  consistent with `soccer_market_rules`' fixed length.

**Do-NOT-touch constraints honored:** `build_rows`, the soccer recognizers,
and both `OpticConfig.table_types` (EPL's and World Cup's) are untouched —
only `PolymarketConfig` additions + the new shared constant + imports/wiring
in the two league modules, plus new tests.

**Files changed:**
- `mappers/exchanges/polymarket.py` — added `SOCCER_MARKET_TYPES` constant
  (9 keys) directly above `soccer_market_rules`; updated the "Task 7 wires"
  comment to "Tasks 6/7 wire" (Task 6 now wires two of the five soccer
  leagues). No changes to any rule, `build_rows`, or `parse_question`.
- `mappers/leagues/world_cup.py` — new `POLYMARKET` config + import +
  `LEAGUE=LeagueConfig(..., POLYMARKET=POLYMARKET)`.
- `mappers/leagues/epl.py` — new `POLYMARKET` config (with the
  best-guess-prefix comment) + import + `LEAGUE=LeagueConfig(..., POLYMARKET=POLYMARKET)`.
- `tests/mappers/test_polymarket_soccer.py` — added imports
  (`League, world_cup` from `mappers.leagues`; `LEAGUES` from `mappers.run`);
  5 new tests: `LEAGUES[League.WORLD_CUP].POLYMARKET`/`LEAGUES[League.EPL].POLYMARKET`
  presence + field checks (including `market_types is pm.SOCCER_MARKET_TYPES`
  identity, proving the DRY-shared-dict wiring); a WC player-goals question
  and a WC BTTS question parsed via `LEAGUES[League.WORLD_CUP].POLYMARKET`
  through `parse_question`; a `.value`-based membership check that
  `MONEYLINE_3WAY` and `FIRST_HALF_WINNER_3WAY` are both present in
  `world_cup.OPTIC.table_types.values()`.

**Test commands + counts:**
- `.venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q`
  → `55 passed` (50 pre-existing + 5 new).
- `.venv/bin/python -m pytest tests/mappers/ -q` → `428 passed, 5 skipped`
  (baseline 423 passed/5 skipped + 5 new; same 5 skips as baseline — no
  test dropped).

**Goldens unchanged (structural argument, not just incidental):**
`gold_row()` (pipeline.py) extracts only 12 non-polymarket fields
(`start_date, home, away, market_type, entity, line, side, grouping_key,
optic_id, px_line_id, kalshi_ticker, kalshi_side`). The only effect of
`league.POLYMARKET is not None` turning on is `_update_polymarket_stamp`
writing `polymarket_clob_token_id/condition_id/position_id/slug/question`
onto an *already-existing* optic row (`attach_polymarket_row`) — none of
those five fields are in `gold_row()`'s extraction set, so even a live run
against real bridge data cannot change a golden row's identity or content.
Did not run `scripts/check_gold.py` against real data directories (no
`data/` fetch present in this environment for EPL/WC bridge data, and doing
so wasn't in the task's listed verify commands) — the above is a
by-construction guarantee, not an executed golden diff.

**Lint:** `.venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py mappers/leagues/epl.py mappers/leagues/world_cup.py tests/mappers/test_polymarket_soccer.py`
→ 2 auto-fixes (import-order/isort on the two league modules' new
polymarket import line), then `All checks passed!` on re-run.

**Concerns:**
- EPL `slug_prefix="epl"` is unvalidated (see caveat above) — calendar
  item for ~Aug 2026, not a blocker now (harmless no-op if wrong).
- Did not execute `scripts/check_gold.py` against live data (see goldens
  note above); the structural argument from `gold_row()`'s field set is
  solid but is a code-reading argument, not a data-driven diff. Flagging
  in case a reviewer wants the live check run once EPL/WC bridge data is
  available.
- Task 7 (MLS/LIGA_MX/UCL) will reuse the same `SOCCER_MARKET_TYPES` +
  `soccer_market_rules` pair — no further changes needed to
  `polymarket.py` for that task, only new `PolymarketConfig` blocks in
  those three league modules (per wave-4 probe, `player_goals` is
  confirmed dead code for mls/mex/ucl — 0/8,330 rows — but the shared key
  stays declared per Task 5's note; harmless, same as any other
  optic-doesn't-price-this-form drop).
