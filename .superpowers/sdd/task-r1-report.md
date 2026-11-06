# Task R1 report: cheap-tier soccer rescue recognizers

**Status:** complete, not blocked.

Scope per the brief: the 9-form/10-recognizer "cheap tier" from
`.superpowers/sdd/wave-rescue-probe-findings.md` (sections A/C) — every form reuses an
ALREADY-SHIPPED SideMode (OVER_UNDER / YESNO_AS_OU / THREE_WAY_FIXED), so `build_rows`
(frozen) was never touched. `OpticConfig.table_types` wiring is a separate later task
(R2) — none of the 4 new `MarketType`s are hooked into any league's Optic config yet, so
this task cannot change any end-to-end pipeline output (a poly row only stamps onto an
*already-existing* optic row for the same MarketType; none exists yet for these 4 types).
`correct_score` was explicitly out of scope and not touched.

## 4 new `MarketType` constants (`mappers/market_types.py`)

```python
SECOND_HALF_TOTAL      = ("2h_total",            Scope.GAME, Shape.TOTAL)
FIRST_HALF_TEAM_TOTAL  = ("1h_team_total",       Scope.TEAM, Shape.TOTAL)
SECOND_HALF_TEAM_TOTAL = ("2h_team_total",       Scope.TEAM, Shape.TOTAL)
FIRST_TEAM_TO_SCORE    = ("first_team_to_score", Scope.GAME, Shape.THREE_WAY)
```

Reused verbatim (not redefined): `SECOND_HALF_WINNER_3WAY`, `PLAYER_ASSISTS`,
`PLAYER_SHOTS`, `PLAYER_SHOTS_ON_TARGET`, `PLAYER_GOALS_OR_ASSIST`, `TEAM_TOTAL`.

## 10 new recognizers (`mappers/exchanges/polymarket.py`) + their `SOCCER_MARKET_TYPES` keys

| recognizer | poly template | MarketType | key added |
|---|---|---|---|
| `soccer_second_half_total_rule` | `<A> vs. <B>: 2nd Half O/U N` | `SECOND_HALF_TOTAL` | `second_half_total` |
| `soccer_first_half_team_total_rule` | `<A> vs. <B>: <Team> 1st Half O/U N` | `FIRST_HALF_TEAM_TOTAL` | `first_half_team_total` |
| `soccer_second_half_team_total_rule` | `<A> vs. <B>: <Team> 2nd Half O/U N` | `SECOND_HALF_TEAM_TOTAL` | `second_half_team_total` |
| `soccer_second_half_winner_rule` | `<Team> to win the second half?` | `SECOND_HALF_WINNER_3WAY` | `second_half_winner_3way` |
| `soccer_second_half_draw_rule` | `<A> vs. <B>: Second half draw?` | `SECOND_HALF_WINNER_3WAY` | (shared key above) |
| `soccer_first_to_score_rule` | `<Team> to score first vs. <Opp>?` | `FIRST_TEAM_TO_SCORE` | `first_team_to_score` |
| `soccer_player_assists_rule` | `<Player>: N+ assists` | `PLAYER_ASSISTS` | `player_assists` |
| `soccer_player_shots_rule` | `<Player>: N+ shots` | `PLAYER_SHOTS` | `player_shots` |
| `soccer_player_shots_on_target_rule` | `<Player>: N+ shots on target` | `PLAYER_SHOTS_ON_TARGET` | `player_shots_on_target` |
| `soccer_player_goals_or_assists_rule` | `<Player>: N+ goals + assists` | `PLAYER_GOALS_OR_ASSIST` | `player_goals_or_assists` |

**Full updated `SOCCER_MARKET_TYPES` key set (18 keys, for Task R2):** `total`,
`team_total`, `spread`, `first_half_total`, `btts`, `first_half_btts`, `moneyline_3way`,
`first_half_winner_3way`, `player_goals` (pre-existing 9) + `second_half_total`,
`first_half_team_total`, `second_half_team_total`, `second_half_winner_3way`,
`first_team_to_score`, `player_assists`, `player_shots`, `player_shots_on_target`,
`player_goals_or_assists` (new 9).

`soccer_market_rules` grew from an 11-recognizer tuple to a **21-recognizer tuple**
(11 + 10 new).

### The "Neither team to score first?" leg — intentionally dropped, not mapped

Per the brief: optic's `first_team_to_score` selections are team names (+ Draw); the
poly leg `<A> vs. <B>: Neither team to score first?` has no clean THREE_WAY_FIXED
selection (`_TIE` means Draw, not "no goal scored"). No recognizer was written for it —
`soccer_first_to_score_rule`'s own anchor (`"to score first vs."` substring) is
structurally disjoint from the neither form's shape (colon-prefixed, no "vs." after
"first"), so it drops via `parse_question`'s normal None-fallthrough. Verified with a
dedicated test (`test_parse_question_neither_first_drops_via_full_tuple`) that the drop
holds against the *entire* `soccer_market_rules` tuple, not just this one rule.

`soccer_first_to_score_rule` captures **both** team names (`team_a`/`team_b`), unlike
the single-team `soccer_ml_team_win_rule`/`soccer_first_half_leader_rule` forms — the
poly question names both teams, and `pipeline._resolve_poly_markets` only defers a
`THREE_WAY_FIXED` market to Phase B (slug-key resolution) when `team_b is None`, so
setting `team_b` lets this form resolve its fixture directly in Phase A.

## Ordering decisions

`soccer_market_rules`' final order (21 entries) places, defensively (every rule is
already self-guarding via its own regex anchor, per the file's existing convention —
these orderings are belt-and-suspenders, not correctness-critical):

1. `player_goals_or_assists` / `player_shots_on_target` before the plain `player_goals`
   / `player_shots` / `player_assists` ladders (verified: the plain rules' own trailing
   anchors, e.g. `shots\s*$`, already reject the "on target"/"+ assists" suffixed forms
   regardless of order, mirroring how `player_goals` already rejected `goals + assists`
   pre-task).
2. `first_half_team_total` / `second_half_team_total` before `team_total` and before
   the game-scoped `first_half_total` / `second_half_total` (verified: the team-half
   patterns require the literal "1st/2nd Half" directly after the team-name capture,
   and the game-half patterns require it directly after the colon — the two shapes are
   structurally disjoint regardless of order, same reasoning the shipped
   `first_half_total` vs. team-total guard already documents).
3. `second_half_draw` before `second_half_winner` (mirrors the existing
   `ml_draw`-before-`ml_team_win` / `first_half_draw`-before-`first_half_leader`
   convention).
4. `first_to_score` ordered last — its anchor family is fully disjoint from every form
   above it.

All orderings are asserted in `test_soccer_market_rules_is_ordered_tuple_of_21`, and
every "must not cross-catch" claim also has a direct negative unit test calling the
rule function itself (not just the ordered tuple), per the brief's ask.

## Files changed

- `mappers/market_types.py` — 4 new `MarketType` constants (see above), each with a
  short doc comment cross-referencing the sibling type it mirrors.
- `mappers/exchanges/polymarket.py` — 9 new compiled regexes (`_Q_SOCCER_SECOND_HALF_*`,
  `_Q_SOCCER_PLAYER_*`), 10 new recognizer functions, `SOCCER_MARKET_TYPES` extended
  (9→18 keys), `soccer_market_rules` extended (11→21 entries) with an updated ordering
  comment block. `build_rows`, `optic.py`, and every `mappers/leagues/*.py` /
  `OpticConfig` were **not** touched.
- `tests/mappers/test_polymarket_soccer.py` — `ALL_SOCCER_CFG.market_types` extended
  with the 9 new keys; 30 new/renamed test functions (parse-level test per new rule,
  ordering-guard negative tests, the neither-drop test at both the single-rule and
  full-tuple level, `build_rows` integration tests for the two new THREE_WAY_FIXED
  pairs and the first-to-score form, and the ordered-tuple/`parse_question` integration
  tests renamed `..._11...` → `..._21...` and extended with the 10 new cases — no prior
  assertion was removed, only extended).

## Test counts

- `tests/mappers/test_polymarket_soccer.py`: **142 passed** (114 baseline + 28 net new;
  2 tests renamed in place — `test_soccer_market_rules_is_ordered_tuple_of_11` →
  `..._21`, `test_parse_question_all_11_soccer_forms` → `..._21` — with all prior
  assertions kept and new ones appended, not dropped).
- `tests/mappers/` full suite: **563 passed, 13 skipped** (baseline, confirmed by
  `git stash`: 535 passed, 13 skipped → net +28 passed, 0 change in skip count or any
  other file's test count — goldens unchanged, no test dropped).

## Lint

`ruff check --fix mappers/market_types.py mappers/exchanges/polymarket.py
tests/mappers/test_polymarket_soccer.py` → **all checks passed**, no findings.

## Concerns

- `mypy` isn't installed in this repo's `.venv` (`No module named mypy`), so
  `make typecheck` could not be run to confirm this diff's type-hygiene independent of
  ruff; the new code follows the exact same typing patterns (`ParsedMarket | None`,
  `cfg.market_types.get(...)`) as the pre-existing rules it mirrors, so risk is low.
- `soccer_first_to_score_rule` is the only new recognizer whose `ParsedMarket` sets both
  `team_a` and `team_b` for a `THREE_WAY_FIXED` single-affirmative form (every other
  `THREE_WAY_FIXED` rule in the file either names one team, `team_b=None`, or names both
  teams for a *draw* form). This is a deliberate deviation (documented in the function's
  own docstring) to get direct Phase-A fixture resolution instead of Phase-B slug-key
  deferral — flagged here in case Task R2 or a future reviewer expects the single-team
  pattern uniformly.
- None of the 4 new `MarketType`s are wired into any league's `OpticConfig.table_types`
  yet (that's Task R2) — until that lands, these recognizers parse real bridge
  questions into `ParsedMarket`s that will currently all drop at
  `pipeline.attach_polymarket_row`'s "no matching optic row" guard. This is expected and
  by design per the brief, not a bug.
