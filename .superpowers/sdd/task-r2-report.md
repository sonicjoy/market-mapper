# Task R2 report: wire rescue-tier soccer MarketTypes into OpticConfig.table_types

**Status:** complete, not blocked.

Scope per the brief: extend `OpticConfig.table_types` in all 5 soccer league modules
(`world_cup.py`, `mls.py`, `liga_mx.py`, `ucl.py`, `epl.py`) with the 9 rescue-tier
optic `market_id` → `MarketType` entries from `wave-rescue-probe-findings.md` section
B, so Task R1's recognizers' `ParsedMarket`s find a matching optic row to stamp onto.
`correct_score` (out of scope, needs a new `Shape`/`SideMode`) was not touched. `build_
rows`, `optic.py`, `market_types.py`, and the recognizers/`soccer_market_rules`/
`SOCCER_MARKET_TYPES` were not touched.

## Per-league `table_types` additions (identical set, all 5 leagues)

```python
"2nd_half_moneyline":     MarketType.SECOND_HALF_WINNER_3WAY,
"first_team_to_score":    MarketType.FIRST_TEAM_TO_SCORE,
"2nd_half_total_goals":   MarketType.SECOND_HALF_TOTAL,
"1st_half_team_total":    MarketType.FIRST_HALF_TEAM_TOTAL,
"2nd_half_team_total":    MarketType.SECOND_HALF_TEAM_TOTAL,
"player_assists":         MarketType.PLAYER_ASSISTS,
"player_shots":           MarketType.PLAYER_SHOTS,
"player_shots_on_target": MarketType.PLAYER_SHOTS_ON_TARGET,
"player_goals_+_assists": MarketType.PLAYER_GOALS_OR_ASSIST,
```

`2nd_half_moneyline` confirmed (probe section B.2) as the plain, already-3-way id —
no separate `-3-way` suffix variant exists (0 rows on the probed fixture), same
convention as the existing full-game/1st-half moneyline series. No pre-existing key
in any of the 5 leagues collided with these 9 (World Cup already had `player_goals`
under `OPTIC`, but not `player_assists`/`player_shots`/`player_shots_on_target`/
`player_goals_+_assists` — those live only in World Cup's separate `CRYPTO.
prop_contract_types`, a different exchange config, no key-space overlap).

No existing `table_types` entry was removed or altered in any of the 5 files —
verified by a dedicated regression test per league (see below) plus the full-suite
diff (0 removed assertions, 0 changed pass/fail on any pre-existing test).

## `OUTPUT_ORDER` — required companion edit (not explicitly asked, but load-bearing)

`tests/mappers/test_table_completeness.py::test_output_order_covers_all_used_types`
asserts every `MarketType` used in a league's `OPTIC.table_types` (or Kalshi/PX) is
present in that league's `OUTPUT_ORDER` tuple. Extending `table_types` without also
extending `OUTPUT_ORDER` would have broken this pre-existing global invariant test
for all 5 leagues, so `OUTPUT_ORDER` in each of the 5 files was extended with exactly
the `MarketType`s newly introduced there (World Cup already carried `PLAYER_ASSISTS`
/ `PLAYER_SHOTS` / `PLAYER_SHOTS_ON_TARGET` / `PLAYER_GOALS_OR_ASSIST` in its
`OUTPUT_ORDER` via the crypto.com FIFA player-prop wiring, so only 5 new entries were
needed there — `SECOND_HALF_TOTAL`, `FIRST_HALF_TEAM_TOTAL`, `SECOND_HALF_TEAM_TOTAL`,
`SECOND_HALF_WINNER_3WAY`, `FIRST_TEAM_TO_SCORE`; the other 4 leagues needed all 9).
This is display-sort-order only (`mappers/pipeline.py` line 649), not correctness —
no golden output changed because of it (see below). `build_rows`/`optic.py`/
`market_types.py`/recognizers remain untouched; only the two per-league constants
(`OPTIC.table_types`, `OUTPUT_ORDER`) in the 5 already-in-scope league files changed.

## Whether any golden changed

**No golden fixture changed.** Checked every `expected_output.jsonl`-backed
integration test in the repo:

- `tests/mappers/fixtures/2026-06-09/15_00` (world_cup, `test_wc_crypto_integration.py`)
  — the only golden fixture that targets a soccer league (`--league world_cup`).
  Its `optic_fixtures_odds.jsonl` contains exactly 2 distinct `market_id`s
  (`moneyline`, `player_goals`), verified by direct inspection — none of the 9
  rescue-tier `market_id`s appear in this fixture, so extending World Cup's
  `table_types` has zero effect on this snapshot. Ran and confirmed byte-identical:
  `test_output_matches_snapshot` still passes.
- `tests/mappers/fixtures/{nba,ncaab,2026-02-25,2026-03-07,2026-06-04}` — all NBA/
  NCAAB fixtures (`--league nba`/`--league ncaab`), unrelated sport, unaffected by
  construction.
- No `expected_output.jsonl`/golden fixture exists for MLS/Liga MX/UCL/EPL at all
  (grepped for polymarket-bearing fixture files repo-wide: none found) — these 4
  leagues have no golden to move.

Confirmed via `git stash` baseline: 563 passed / 13 skipped before this change,
579 passed / 13 skipped after — net +16 passed, 0 skip-count change, 0 test removed
or altered, matching exactly the 16 new tests added (no incidental golden drift).

## Files changed

- `mappers/leagues/world_cup.py` — 9 `OPTIC.table_types` additions + 5 `OUTPUT_ORDER`
  additions + doc-comment updates (both the new dict block and the stale "ALL 11
  soccer forms" docstring paragraph, corrected to note Task R1/R2's extension without
  rewriting the historical Task-6 record).
- `mappers/leagues/mls.py` — 9 `OPTIC.table_types` additions + 9 `OUTPUT_ORDER`
  additions + doc comment.
- `mappers/leagues/liga_mx.py` — same shape as mls.py.
- `mappers/leagues/ucl.py` — same shape as mls.py.
- `mappers/leagues/epl.py` — 9 `OPTIC.table_types` additions + 9 `OUTPUT_ORDER`
  additions + updated the stale "only 3 of 9 are priced" docstring paragraph to
  note Task R2's extension (still accurate: only 3 of the *original* 9 form types
  are Kalshi-parity-priced; the 9 rescue types are additional, EPL-only-via-Optic,
  no Kalshi counterpart).
- `tests/mappers/test_polymarket_soccer.py` — new "Task R2" section (5 test
  functions, parametrized over the 5 leagues where applicable = 16 test cases
  total): `test_rescue_tier_optic_table_types_wired` (all 9 keys present, correct
  value, per league), `test_rescue_tier_wiring_keeps_preexisting_keys` (regression:
  every pre-existing key/value pair untouched, with an EPL-specific branch asserting
  its narrower original set wasn't accidentally widened), `test_rescue_tier_table_
  types_no_collision_with_existing_values` (the 9 new `MarketType`s don't alias onto
  any value already used by a pre-existing key), `test_rescue_tier_output_order_
  covers_new_types_per_league` (pins the `OUTPUT_ORDER` companion edit specifically,
  narrower than the global completeness test).

## Test counts

- `tests/mappers/test_polymarket_soccer.py -k rescue_tier`: **16 passed** (new).
- `tests/mappers/test_polymarket_soccer.py` (whole file): **158 passed** (142
  baseline from Task R1 + 16 net new, 0 removed/renamed).
- `tests/mappers/` full suite: **579 passed, 13 skipped** (baseline via `git stash`:
  563 passed, 13 skipped → net +16 passed, 0 change in skip count, confirming no
  golden moved and no pre-existing test was altered).

## Lint

`ruff check --fix mappers/leagues/world_cup.py mappers/leagues/mls.py
mappers/leagues/liga_mx.py mappers/leagues/ucl.py mappers/leagues/epl.py
tests/mappers/test_polymarket_soccer.py` → **all checks passed**, no findings.

## Concerns

- `mypy` isn't installed in this repo's `.venv` (`No module named mypy`), consistent
  with Task R1's report — could not run `make typecheck`. This task only adds dict
  literal entries and tuple entries of already-existing types, so type-hygiene risk
  is effectively nil.
- The "Neither team to score first?" poly form remains permanently unmapped (Task
  R1's deliberate scope decision, not touched here) — `first_team_to_score`'s optic
  selections are Team/Team/Draw only, no clean THREE_WAY_FIXED slot for "neither."
- `correct_score`/`exact_score` (the single largest rescue-tier form by volume,
  ~53% of all rescue-tier rows per the probe) remains entirely out of scope — it
  needs a new `Shape.CORRECT_SCORE` + `SideMode` + `build_rows` branches on both
  exchange modules, explicitly called out in the probe findings as its own
  follow-up wave, not a config-only wire-up like this task's 9 forms.
- EPL's `slug_prefix="epl"` is still "BEST-GUESS, UNVALIDATED" per the pre-existing
  Task-6 comment (EPL off-season, 0 live poly bridge rows at probe time) — this
  task's EPL `table_types` additions inherit that same unvalidated-prefix caveat;
  they're inert until EPL's bridge prefix is confirmed live regardless.
