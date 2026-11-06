### Task 4 report: Soccer 3-way moneyline recognizers (first live THREE_WAY_FIXED)

**Status:** complete, not blocked.

**Verification result — the `team_b=None` question (per brief's "CRITICAL — verify, don't guess"):**

Read `build_rows`' `THREE_WAY_FIXED` branch (`mappers/exchanges/polymarket.py:661-675`) closely: it
reads only `parsed.fixed_side_team` (compared via `_name_match` against the
caller-supplied `home_name`/`away_name`) and the caller-supplied
`home`/`away`/`outcomes` — **it never reads `parsed.team_a`/`parsed.team_b` at
all**. So the branch does not "require both teams"; it requires neither. The
dormant tests in `tests/mappers/test_polymarket.py` (`test_build_rows_three_way_fixed_*`)
happen to set both `team_a`/`team_b` on their `ParsedMarket`, but that's
incidental (copy-paste from the MLB fixture), not a requirement the branch
enforces. Confirmed by mirroring the pattern with `team_b=None` in this
task's own `build_rows` integration tests (`test_build_rows_soccer_ml_team_win_binds_named_team`,
`test_build_rows_soccer_first_half_leader_binds_named_team`) — both pass,
emitting exactly one affirmative row bound to the correct team abbrev.

So: **`THREE_WAY_FIXED` can emit fine with `team_b=None`** — the compound
BLOCKED condition in the brief ("genuinely cannot emit with `team_b=None`
AND the slug path does not cover it") is not met, because the first half of
that condition is false. No STOP required; implemented as specified
(`team_a=<Team>`, `team_b=None` for the single-team forms).

**Concern flagged for a later task (not a blocker here, out of this task's file
scope):** `mappers/pipeline.py::_resolve_poly_markets` only defers
`Scope.PLAYER` markets to the slug-keyed Phase B (`fixture_by_slug_key`);
`MONEYLINE_3WAY`/`FIRST_HALF_WINNER_3WAY` are `Scope.GAME` (confirmed in
`mappers/market_types.py`), so they go through Phase A's
`_match_poly_game_fixture` → `_match_poly_fixture`, which requires **both**
`team_a` and `team_b` to name-match a fixture side (`_name_match` returns
`False` whenever either string is empty). Unlike `SPREAD_TEAM` (which
`_match_poly_game_fixture` special-cases by pulling both team names from the
market's outcome LABELS before matching), `THREE_WAY_FIXED`'s outcome labels
are Yes/No — no second team name is recoverable from them. So, as currently
wired, the two single-team recognizers (`soccer_ml_team_win_rule`,
`soccer_first_half_leader_rule`) would produce a `ParsedMarket` that
`_resolve_poly_markets` can never fixture-resolve end-to-end (Phase A fails
for lack of `team_b`; Phase B doesn't run because scope isn't `PLAYER`) —
this is a real integration gap, but it's in `pipeline.py`, which is outside
this task's file scope (`mappers/exchanges/polymarket.py` + test file only;
the brief's plan document does not assign a pipeline.py fix to any task in
this wave). Flagging for whoever wires the leagues (Task 6/7) or runs Task 8's
local validation — the draw forms (`soccer_ml_draw_rule`,
`soccer_first_half_draw_rule`) are unaffected since both name both teams and
resolve via the existing Phase A path.

**Files changed:**
- `mappers/exchanges/polymarket.py` — added 4 anchored question regexes
  (`_Q_SOCCER_ML_TEAM_WIN`, `_Q_SOCCER_ML_DRAW`, `_Q_SOCCER_FIRST_HALF_LEADER`,
  `_Q_SOCCER_FIRST_HALF_DRAW`) + 4 recognizer functions
  (`soccer_ml_team_win_rule`, `soccer_ml_draw_rule`,
  `soccer_first_half_leader_rule`, `soccer_first_half_draw_rule`), inserted
  before `parse_question`. No changes to `build_rows`, `ParsedMarket`,
  `SideMode`, or `parse_question` itself.
- `tests/mappers/test_polymarket_soccer.py` — added `TIE_SIDE` import;
  extended `SOCCER_CFG.market_types` with `"moneyline_3way"` and
  `"first_half_winner_3way"` keys (mirrors how Task 2/3 extended the same
  dict; `market_rules` tuple untouched — assembling it is Task 5's job); 17
  new tests (parse-level ×12 incl. ordering/flip-safety/missing-config
  guards for all 4 rules, `build_rows` integration ×5 incl. one flip-safety
  drop test).

**Test commands + counts:**
- `.venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q`
  → `41 passed` (24 pre-existing + 17 new).
- `.venv/bin/python -m pytest tests/mappers/ -q` → `410 passed, 5 skipped`
  (baseline 393 passed/5 skipped + 17 new; goldens unchanged, no test
  dropped).

**Lint:** `.venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py tests/mappers/test_polymarket_soccer.py`
→ `All checks passed!`

**Design notes:**
- `market_types` keys chosen: `"moneyline_3way"` (shared by team-win + draw,
  both map to optic's `moneyline` 3-way market) and
  `"first_half_winner_3way"` (shared by first-half-leader + first-half-draw,
  both map to optic's `1st_half_moneyline`) — matches the plan table's
  1:1 MarketType pairing (team-win and draw are the SAME `MarketType`, just
  different `fixed_side_team`).
- Question regexes are anchored on the literal trailing `?` (byte-exact
  templates from the probe) and on form-unique literal substrings (`" win on
  "` vs. `" end in a draw?"` vs. `"leading at halftime?"` vs. `": draw at
  halftime?"`), so each of the 4 rules matches only its own shape —
  cross-rejection verified by an explicit test per rule (e.g.
  `test_soccer_ml_team_win_rejects_draw_form`), independent of any ordering
  in a future `market_rules` tuple.
- Flip-safety: `fixed_side_team` is always the question-named, normalized
  team (or `None` → `_TIE` for the draw forms), never an index; verified by
  `test_build_rows_soccer_ml_team_win_drops_when_named_team_absent` (a named
  team that resolves to neither fixture side drops the whole market).

**Concerns:** the pipeline.py fixture-resolution gap described above for the
two single-team forms — real, but out of this task's scope; needs a
follow-up (extend `_resolve_poly_markets`'s Phase B slug-map to cover
`Scope.GAME` markets with `team_b is None`, or an equivalent mechanism)
before those two forms will produce end-to-end stamps in Task 8's local
validation run.
