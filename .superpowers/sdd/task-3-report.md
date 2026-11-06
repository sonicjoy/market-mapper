# Task 3 report — Soccer BTTS + 1st-half-BTTS recognizers (first live YESNO)

> Note: this path previously held a report from a different, earlier "Task 3"
> (the MLB full-taxonomy `market_rules` wave, branch `feat/polymarket-optic-matcher`).
> Overwritten per this task's explicit instruction to write to this exact path —
> the dir is gitignored scratch space so nothing tracked was lost, but flagging
> the overwrite for the record in case that old content was still wanted.

Branch: `feat/polymarket-parity-expansion`. Baseline before this task = `acc0ce9`
("feat(poly/soccer): total, team-total, spread, 1st-half-total recognizers" —
Task 2), `tests/mappers/` 385 passed / 5 skipped.

## Files changed

- `mappers/exchanges/polymarket.py` — added 2 regex constants
  (`_Q_SOCCER_BTTS`, `_Q_SOCCER_FIRST_HALF_BTTS`) and 2 recognizer functions
  (`soccer_btts_rule`, `soccer_first_half_btts_rule`), inserted after
  `soccer_first_half_total_rule` and before `parse_question`. `build_rows` was
  NOT touched (read-only, per the frozen constraint) — this is its first live
  exercise of the `SideMode.YESNO` branch.
- `tests/mappers/test_polymarket_soccer.py` — extended `SOCCER_CFG` with
  `"btts"`/`"first_half_btts"` `market_types` entries and the two new rules
  appended to `market_rules`; added 8 new tests (parse ×2, ordering guards ×2,
  missing-kind-config ×1, `parse_question` dispatch ×2, and the required
  `build_rows` YESNO integration test ×1).

## Design notes

- Mirrors Task 2's style exactly: `cfg.market_types.get("btts")` /
  `.get("first_half_btts")` resolve the canonical `MarketType` (config stays
  the source of truth), `team_a`/`team_b` go through
  `_norm_name(name, cfg.question_style)`, `side_mode=SideMode.YESNO`. No
  `entity` set (GAME scope, defaults to `None`), matching `MarketType.BTTS`
  / `FIRST_HALF_BTTS`'s `(Scope.GAME, Shape.YES_NO)` declaration already in
  `mappers/market_types.py`.
- **Ordering guard is pure anchoring**, same mechanism as `soccer_total_rule`
  (Task 2's "full-total guard"): `_Q_SOCCER_BTTS` requires `both teams to
  score` to be followed only by `\s*$`. The 1st-half variant's trailing
  `" in first half"` can't satisfy that tail, so `soccer_btts_rule` rejects it
  with no extra code — verified by `test_btts_first_half_not_captured_by_plain_btts`
  calling `soccer_btts_rule` directly (not through `parse_question` ordering).
  Symmetric guard added on `soccer_first_half_btts_rule` (rejects the plain
  BTTS question, no `in first half` tail) though not required by the brief —
  cheap and consistent with Task 2's spirit of a rule never accidentally
  matching an adjacent form's shape.
- Exact question templates and outcome labels (Yes/No) taken byte-exact from
  `.superpowers/sdd/wave-4-probe-findings.md` section C (BTTS / 1st-half BTTS
  rows).

## First-live-YESNO integration test

`test_build_rows_btts_yesno_binds_side_to_label` feeds `soccer_btts_rule`'s
real `ParsedMarket` output (not hand-built) plus a synthetic 2-outcome
`PolyMarket` into `build_rows` directly, mirroring the dormant
`test_build_rows_yesno_btts_game_scope` call pattern in
`tests/mappers/test_polymarket.py`. Deliberately puts `"No"` at
`outcome_index=0` and `"Yes"` at `outcome_index=1` (inverted from natural
order) so the assertion — `cY.side == "yes"`, `cN.side == "no"` — actually
exercises label-binding, not index-luck (flip-safety).

## Commands run + output

### Step 2 — verify fail (before implementation)

```
$ .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q
AttributeError: module 'mappers.exchanges.polymarket' has no attribute 'soccer_btts_rule'
1 error in 0.14s
```

### Step 4 — verify pass (after implementation)

```
$ .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q
........................                                                 [100%]
24 passed in 0.09s
```
(16 pre-existing Task-2 tests + 8 new BTTS tests.)

### Step 5 — full suite + lint

```
$ .venv/bin/python -m pytest tests/mappers/ -q
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 54%]
........................................................................ [ 72%]
.......................................................s....ssss........ [ 90%]
......................................                                   [100%]
393 passed, 5 skipped in 2.19s
```

Baseline (re-checked via `git stash` on the same tree before committing):
`385 passed, 5 skipped` — same 5 skips, +8 passed = exactly the 8 new tests.
Goldens unchanged; nothing dropped.

```
$ .venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py tests/mappers/test_polymarket_soccer.py
All checks passed!
```

Note: `ruff format --check` reports both files "would reformat" — confirmed via
`git stash` that this is **pre-existing** (true on baseline HEAD before any of
my edits too), not introduced by this change. The task's specified lint gate
(`ruff check --fix`) is clean; `ruff format` was not part of the given command
and was left untouched to avoid an unrelated reformat diff.

## Concerns

None blocking. Both regexes are pure-anchoring guards (no extra `re.search`
content check needed, unlike Task 2's team-total rule) — the BTTS/1st-half-BTTS
question pair has no shared-prefix ambiguity the team-total/team-half-total
pair had.
