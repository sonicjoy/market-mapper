# Wave 5, Task 3 — basketball wiring report (NBA/NCAAB parity + WNBA expansion)

## WNBA module summary

New `mappers/leagues/wnba.py`, cloned from `mls.py`'s poly-only template
(KALSHI=None, PX=None, CRYPTO=None, RUNSHOP=None):

- `OPTIC = OpticConfig(league_id="wnba", table_types={...})` — exactly the 6
  poly-confirmed families (`moneyline`, `point_spread`, `total_points`,
  `player_points`, `player_rebounds`, `player_assists`). Deliberately leaner
  than NBA/NCAAB's table_types (no `team_total`/half/quarter types), per the
  probe's "Impact on Tasks 2+" recommendation — poly genuinely never asks
  for those on WNBA (0/1,624 bridge rows), so padding would just be inert
  noise rather than harmless dead weight worth carrying.
- `POLYMARKET = PolymarketConfig(slug_prefix="wnba", optic_league_id="wnba",
  market_types=BASKETBALL_MARKET_TYPES, question_style="mlb_suffix",
  market_rules=basketball_market_rules, team_name_aliases=
  {"portlandfire": "portland fire"})` — reuses the wave-5/Task 2 recognizer
  surface verbatim, no new recognizer code.
- `LEAGUE = LeagueConfig(league=League.WNBA, KALSHI=None, PX=None,
  OPTIC=OPTIC, POLYMARKET=POLYMARKET, ...)`.
- Registered `League.WNBA: wnba.LEAGUE` in `mappers/run.py`'s `LEAGUES` dict
  (module import + dict entry) — this is what makes WNBA automatically
  appear in `fetch/optic.py`'s derived `SUPPORTED_LEAGUES`.
- `OUTPUT_ORDER` covers exactly the 6 types in `OPTIC.table_types`
  (auto-verified by the existing parametrized
  `tests/mappers/test_table_completeness.py::test_output_order_covers_all_used_types[wnba]`,
  which now runs for wnba and passed with no edits needed to that test file).

## NBA/NCAAB `POLYMARKET` config — best-guess-slug caveat

Both leagues already ship a real `OpticConfig` (`league_id="nba"`/`"ncaab"`,
live-confirmed by prior waves); this task only *adds* a `PolymarketConfig`:

```python
POLYMARKET = PolymarketConfig(
    slug_prefix="nba",       # or "ncaab"
    optic_league_id=OPTIC.league_id,
    market_types=BASKETBALL_MARKET_TYPES,
    question_style="mlb_suffix",
    market_rules=basketball_market_rules,
)
```

**UNVALIDATED, flagged prominently in-code**: both NBA and NCAAB are
off-season as of 2026-07-23 — NBA is absent from *both* the July poly
position↔token bridge *and* Optic's own `leagues/active` listing; NCAAB has
0 rows in the July bridge. Neither `slug_prefix` could be confirmed against
live bridge data the way `"wnba"` was (wave-5-probe-findings.md section A).
`"nba"`/`"ncaab"` are best-guesses by naming-convention parity with Kalshi
prefix / Optic `league_id` / WNBA's own bare-lowercase pattern. If wrong,
the pipeline's `market.slug.startswith(pcfg.slug_prefix + "-")` filter
simply matches zero markets — a harmless silent no-op (no rows, no
mis-mapping), not a mis-price. **Re-validate both prefixes against a live
bridge snapshot once the 2026-27 season repopulates the bridge** — the
in-code comments in both modules say this explicitly.

Also unconfirmed: whether NBA/NCAAB's own poly question-form menu matches
WNBA's 6-form menu exactly, or additionally asks `team_total`/half-winner/the
fuller player-prop set (threes/blocks/steals/turnovers/DD/TD) their Kalshi
ticker types imply — reusing `BASKETBALL_MARKET_TYPES`/`basketball_market_rules`
verbatim is a forward bet on parity, not a confirmed fact.

No `team_name_aliases` for NBA/NCAAB (left `{}` — unprobed; both franchise
rosters are stable/incumbent so a WNBA-style alias need is plausible but
unconfirmed).

One factual correction versus the task brief: NCAAB's existing
`OpticConfig.table_types` **does** carry `player_points`/`player_assists`/
`player_rebounds` (it's only NCAAB's *Kalshi* `table_types` that lacks player
props) — so poly player-prop legs for NCAAB will find an Optic counterpart
and stamp normally, they will not drop. Corrected the in-code comment in
`ncaab.py` accordingly and added a regression test
(`test_ncaab_optic_table_types_has_no_player_types`, name kept for brief
traceability, body asserts the actual — opposite — reality) so a future edit
that removes that coverage is caught.

Both leagues keep their existing `KALSHI`/`PX` (NBA also keeps `CRYPTO`)
unchanged — `POLYMARKET` is purely additive on the `LeagueConfig`.

## `LEAGUE_SECRET` guard approach

`fetch/optic.py`:
1. Added `League.WNBA: "opticodds_access_key"` to `LEAGUE_SECRET` (same
   secret as every other non-tennis league).
2. Added a module-level invariant right after both dicts are defined:
   ```python
   assert LEAGUE_SECRET.keys() >= SUPPORTED_LEAGUES.keys(), (
       "LEAGUE_SECRET is missing an entry for: "
       f"{SUPPORTED_LEAGUES.keys() - LEAGUE_SECRET.keys()}"
   )
   ```
   Chose the module-level `assert` (over a standalone test-only check)
   because `SUPPORTED_LEAGUES` is itself derived at import time from
   `mappers.run.LEAGUES` — a future league wired into the pipeline registry
   but missing its `LEAGUE_SECRET` entry now fails at **import** time (any
   test collection, `python -m fetch.optic`, etc.), not just when a
   dedicated test happens to run. Backed by a regression test in
   `tests/fetch/test_optic_supported_leagues.py`
   (`test_league_secret_covers_every_supported_league` +
   `test_wnba_is_fetchable_and_has_a_secret_mapping`) so the invariant itself
   is also covered directly, not just incidentally via import succeeding.

## Files changed

- `mappers/leagues/wnba.py` — new
- `mappers/leagues/nba.py` — added `POLYMARKET` config + import
- `mappers/leagues/ncaab.py` — added `POLYMARKET` config + import
- `mappers/run.py` — import `wnba`, register `League.WNBA: wnba.LEAGUE`,
  updated a stale comment (`phase-4+ members (wnba/ufc)` → `phase-5+
  members (ufc)`)
- `fetch/optic.py` — `LEAGUE_SECRET[League.WNBA]` entry + the
  `LEAGUE_SECRET.keys() >= SUPPORTED_LEAGUES.keys()` invariant assertion
- `tests/mappers/test_wnba_wiring.py` — new (19 tests: WNBA wiring/alias +
  NBA/NCAAB `POLYMARKET` wiring/parse-through)
- `tests/fetch/test_optic_supported_leagues.py` — 2 new tests for the
  `LEAGUE_SECRET` guard

Not touched: `build_rows`, the recognizers, `basketball_market_rules`,
`BASKETBALL_MARKET_TYPES` (all frozen per brief), MLB/soccer league modules.

## Test counts

- New tests alone: `tests/mappers/test_wnba_wiring.py` +
  `tests/fetch/test_optic_supported_leagues.py` → **25 passed** (`-x -q`).
- Full suite: `GCP_PROJECT=marketmaking-test .venv/bin/python -m pytest
  tests/mappers/ tests/fetch/ -q` → **569 passed, 13 skipped**
  (mappers: 535 passed/13 skipped; fetch: 34 passed/0 skipped).
  - Baseline was mappers 515/11 + fetch 32 (558 mappers+fetch total, 547
    passed/11 skipped/no fetch-skips). New total is +22 mappers tests, +2
    fetch tests, net +24 tests, no test dropped.
  - Mappers breakdown of the +22: 19 new tests in `test_wnba_wiring.py`,
    plus **+2 auto-param skips** from the existing parametrized
    `test_table_completeness.py` (`test_kalshi_*`/`test_px_*`-style tests
    parametrize over `LEAGUES`; WNBA's new `KALSHI=None`/`PX=None` entries
    each produce one `pytest.skip`, exactly as the brief anticipated),
    plus **+1 auto-pass** (`test_output_order_covers_all_used_types[wnba]`,
    which is not gated on KALSHI/PX and ran for real, confirming WNBA's
    `OUTPUT_ORDER` is complete).
  - Golden-integration regression check: `test_nba_integration.py` and
    `test_ncaab_integration.py` (subprocess `mappers.run --json` vs. a
    byte-compared snapshot) both still pass unchanged — adding
    `POLYMARKET` to NBA/NCAAB's `LeagueConfig` is a no-op on those fixture
    dirs since neither ships a `polymarket_markets.jsonl` (pipeline's
    `lines_if_exists` guard short-circuits to zero poly rows).

## Lint

`ruff check --fix` on the 6 changed/new files initially also "fixed" 3
**pre-existing, unrelated** issues in `fetch/optic.py` (a `datetime.UTC`
alias rewrite and an `if/elif` merge in `clean_odds`, both outside anything
this task touched) and left 2 pre-existing errors untouched elsewhere
(`E402`/`B011` in `fetch/optic.py`, `E501` in `mappers/run.py`'s docstring —
confirmed present on the pre-task commit via `git stash`). Reverted the two
unrelated auto-fixes to keep the diff scoped to this task; final
`ruff check` on the changed files reports **zero errors on any line this
task touched** (only the one pre-existing `E501` in `mappers/run.py`'s
untouched docstring line remains, verified present before this task began).

## Concerns

- NBA/NCAAB `slug_prefix` values are genuine guesses, not confirmed —
  flagged in-code and here per the brief; functionally safe (fail-closed
  no-op) if wrong, but should be revisited once the 2026-27 season bridge
  populates.
- NBA/NCAAB's actual poly question-form menu (team_total? half-winner? the
  fuller player-prop set?) is unconfirmed; wiring the WNBA-derived
  `basketball_market_rules` for them is a parity bet, not a probed fact.
- The task brief's NCAAB player-prop-drop claim doesn't match the actual
  `ncaab.py` `OpticConfig` (which does carry player_points/assists/rebounds)
  — corrected in the in-code comment and called out above so it doesn't
  propagate into later waves' assumptions.
