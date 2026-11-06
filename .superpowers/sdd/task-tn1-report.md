# Task TN1 report — tennis rescue Tier 1 (total_sets) + GOTCHA-1 build_rows fix

Scope: `total_sets` full-name form + the one backward-compatible `build_rows`
OVER_UNDER fix the whole tennis rescue needs. Surname-only forms
(match_total_games/set_handicap/set_games/set_winner) explicitly NOT touched
(separate later task, per `.superpowers/sdd/wave-tennis-probe-findings.md`
section C.2).

## (1) GOTCHA-1 — build_rows OVER_UNDER fix

File: `mappers/exchanges/polymarket.py`, `build_rows`'s `OVER_UNDER`/`YESNO_AS_OU`
branch (loop over `outcomes`).

**Before:**
```python
if lab == over_lab:
    side = "over"
elif lab == under_lab:
    side = "under"
else:
    return []  # must be the two complementary labels -> else drop
```

**After:**
```python
if lab == over_lab or lab.startswith(over_lab + " "):
    side = "over"
elif lab == under_lab or lab.startswith(under_lab + " "):
    side = "under"
else:
    return []  # must be the two complementary labels -> else drop
```

**Why backward-compatible (`_normalize` evidence, pinned in
`test_normalize_over_2_5_and_overtime_evidence`):**

| input | `_normalize` output | `== "over"` | `.startswith("over ")` |
|---|---|---|---|
| `"Over"` (every existing MLB/soccer/basketball/tennis-moneyline-adjacent form) | `"over"` | **True** (unchanged path) | — (short-circuited by `or`) |
| `"Over 2.5"` (tennis `total_sets`, new) | `"over 2 5"` | False | **True** |
| `"Overtime"` (hypothetical adversarial label) | `"overtime"` | False | **False** (no space after "over") |

Every pre-existing bare-label form still hits the `==` arm exactly as before
(the `or` short-circuits, so no new code path is exercised for them) — the
change is strictly additive. The `startswith(over_lab + " ")` guard (not a
bare `startswith(over_lab)`) is what keeps `"overtime"`-shaped labels from
falsely matching, since there's no space at that position.

## (2)-(3) New MarketType + recognizer

- `mappers/market_types.py`: `MarketType.TOTAL_SETS = ("total_sets", Scope.GAME, Shape.TOTAL)`.
- `mappers/exchanges/polymarket.py`:
  - `_Q_TENNIS_TOTAL_SETS` regex: `^(.+?)\s+vs\.?\s+(.+?):\s*total sets\s+o/u\s*([\d.]+)\s*$`
  - `tennis_total_sets_rule(question, cfg)` — mirrors `soccer_total_rule`'s
    structure (no team-total/half variant to guard against). FULL names on
    both sides via `_norm_name(..., cfg.question_style)` (same as moneyline —
    no surname truncation). → `MarketType.TOTAL_SETS`, `SideMode.OVER_UNDER`,
    `line=<N>` (float, parsed generically — not hardcoded to 2.5 even though
    the probe found it's always 2.5 in practice).
  - `TENNIS_MARKET_TYPES: dict[str, MarketType]` = `{"moneyline": MONEYLINE,
    "total_sets": TOTAL_SETS}` — new shared dict (atp.py/wta.py previously
    inlined `{"moneyline": MarketType.MONEYLINE}` separately; consolidated
    following the `SOCCER_MARKET_TYPES`/`BASKETBALL_MARKET_TYPES` convention).
  - `tennis_market_rules: tuple[MarketRule, ...] = (tennis_total_sets_rule,
    tennis_moneyline_rule)` — new shared tuple (previously inlined
    `(tennis_moneyline_rule,)` per league). Order is defensive, not
    correctness-critical: `tennis_moneyline_rule` already self-guards against
    `o/u|total|sets|games` in its own regex, and `tennis_total_sets_rule`'s
    anchor requires the literal "Total Sets O/U", so the two forms are
    disjoint by construction.

## (4) Wiring

- `mappers/leagues/atp.py` / `wta.py`:
  - `OPTIC.table_types["total_sets"] = MarketType.TOTAL_SETS` (added, alongside
    the existing `"moneyline"` entry).
  - `POLYMARKET.market_types = TENNIS_MARKET_TYPES`, `market_rules =
    tennis_market_rules` (replacing the per-league inline dict/tuple).
  - `OUTPUT_ORDER` — appended `MarketType.TOTAL_SETS` (required by
    `test_table_completeness.py::test_output_order_covers_all_used_types`,
    which asserts every `MarketType` referenced by `OPTIC.table_types` is
    present in `OUTPUT_ORDER`).

## Files changed

- `mappers/market_types.py` — new `MarketType.TOTAL_SETS`.
- `mappers/exchanges/polymarket.py` — GOTCHA-1 fix; `_Q_TENNIS_TOTAL_SETS` +
  `tennis_total_sets_rule`; `TENNIS_MARKET_TYPES`; `tennis_market_rules`.
- `mappers/leagues/atp.py`, `mappers/leagues/wta.py` — wired per (4) above.
- `tests/mappers/test_polymarket_tennis_integration.py` — updated the one
  pre-existing assertion (`POLYMARKET.market_types == {"moneyline": ...}`)
  that this task's wiring change intentionally supersedes (it now includes
  `total_sets` too); nothing else in that file touched.
- `tests/mappers/test_polymarket_tennis.py` — new, 11 tests.

## Tests

New file: 11/11 passed (`tennis_total_sets_rule` parsing + dispatch-ordering,
atp/wta wiring, GOTCHA-1 regression test — fails without the fix, would
otherwise return `rows == []` — plus the bare-label backward-compat test and
the `"Overtime"`-rejection tight-guard test, plus a `_normalize` evidence pin).

Full suite: `tests/mappers/ -q` → **608 passed, 13 skipped** (same skip count
as pre-change; no test moved from pass→fail or vice versa other than the one
intentionally-updated assertion above). All existing OVER_UNDER
goldens/tests across MLB/soccer/basketball (`test_polymarket.py`,
`test_polymarket_soccer.py`, `test_polymarket_basketball.py`,
`test_polymarket_mlb_integration.py`) pass unchanged — confirms the fix is
byte-identical for every pre-existing form.

`tests/fetch/test_optic_dedup.py` fails to COLLECT (`KeyError: 'GCP_PROJECT'`)
on this checkout — pre-existing environment issue (missing env var),
unrelated to this task, not touched by these changes; not part of the
`tests/mappers/` target this task specifies.

## Lint

`ruff check --fix` on all 6 changed/new files → 3 auto-fixes (import
ordering/isort in atp.py/wta.py, a blank-line nit in the new test file), 0
remaining. `ruff check` (no `--fix`) on the same files afterward: all checks
passed.

## Concerns

- None outstanding. The one genuinely risky piece (the shared `build_rows`
  branch) is provably backward-compatible per the `_normalize` truth table
  above and is covered by an explicit regression + backward-compat + tight-guard
  test trio.
- `TENNIS_MARKET_TYPES`/`tennis_market_rules` are new shared constants (not
  requested verbatim by name in the task, but the task explicitly said
  "create one if atp/wta inline — match the shipped pattern"); they mirror
  `SOCCER_MARKET_TYPES`/`soccer_market_rules` and
  `BASKETBALL_MARKET_TYPES`/`basketball_market_rules` byte-for-byte in
  structure and placement. `tennis_moneyline_rule` itself is untouched and
  still importable/usable standalone (existing tests
  `test_polymarket_pipeline.py`/`test_polymarket.py` construct their own
  ad-hoc configs referencing it directly and are unaffected).
