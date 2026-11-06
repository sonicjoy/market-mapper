### Task 5 report: Player-goals recognizer + shared `soccer_market_rules` tuple

**Status:** complete, not blocked.

**`market_types` key set the 11 soccer rules reference (critical for Tasks 6/7):**

```python
{
    "total":                   MarketType.GAME_TOTAL,
    "team_total":               MarketType.TEAM_TOTAL,
    "spread":                   MarketType.POINT_SPREAD,
    "first_half_total":         MarketType.FIRST_HALF_TOTAL,
    "btts":                     MarketType.BTTS,
    "first_half_btts":          MarketType.FIRST_HALF_BTTS,
    "moneyline_3way":           MarketType.MONEYLINE_3WAY,        # shared by ml_team_win + ml_draw
    "first_half_winner_3way":   MarketType.FIRST_HALF_WINNER_3WAY, # shared by first_half_leader + first_half_draw
    "player_goals":             MarketType.PLAYER_GOALS,
}
```

9 distinct keys back the 11 rules (`moneyline_3way` and `first_half_winner_3way`
are each shared by two rules — team-win/leader vs. their draw sibling, same
`MarketType`, differing only in `fixed_side_team`). A league config missing
any of these 9 keys will silently drop that form's questions (rule returns
`None` via `cfg.market_types.get(...)` — no exception, no log). Per the
wave-4 probe (section C), `player_goals` will never actually fire for
mls/mex/ucl (poly doesn't ask the `N+ goals` ladder there — confirmed
0/8,330 rows) — harmless dead code path for those three leagues, but the key
still needs to be in `market_types` for World Cup/EPL (Task 6) since a
missing key is a silent drop, not an error, and Task 6's config should
declare it explicitly rather than relying on absence-is-fine.

**Implementation notes:**

- `soccer_player_goals_rule` reuses `_player_prop_rule` (Phase 3 helper,
  previously only called by `mlb_home_runs_rule`/`mlb_strikeouts_rule`).
  Extended its signature with two keyword-only params — `side_mode:
  SideMode = SideMode.OVER_UNDER` and `line_transform: Callable[[float],
  float] | None = None` — both defaulting to the original MLB behavior, so
  the two existing callers are unaffected (verified: full suite green,
  no diff in their test outcomes). `soccer_player_goals_rule` passes
  `side_mode=SideMode.YESNO_AS_OU` and `line_transform=lambda n: n - 0.5`.
- New anchored regex `_Q_SOCCER_PLAYER_GOALS` = `^(?P<player>.+?):\s*(?P<n>\d+)\+\s*goals\s*$`
  (case-insensitive). The trailing `\s*$` right after the literal `goals` is
  what rejects `"<Player>: 1+ goals + assists"` — it has the substring
  `"goals"` but is followed by `" + assists"`, not just whitespace, so the
  anchor fails and the rule returns `None`. `"1+ assists"` / `"1+ shots"`
  never match at all (no `"goals"` literal present).
- `soccer_market_rules: tuple[MarketRule, ...]` assembled with all 11
  recognizers, most-specific-first (full ordering rationale is a 14-line
  comment directly above the tuple in `polymarket.py`): `player_goals` →
  `team_total` → `first_half_total` → `total` → `spread` →
  `first_half_btts` → `btts` → `ml_draw` → `ml_team_win` →
  `first_half_draw` → `first_half_leader`. Every rule is already
  self-guarding via its own regex anchor (verified individually in Tasks
  2-4's tests), so this ordering is defensive belt-and-suspenders, not a
  correctness requirement — but it fails safe (falls through to a more
  general rule) rather than mis-classifying if an anchor ever regresses.
- `build_rows` and `parse_question` untouched (confirmed via `git diff`
  hunk boundaries — all edits are inside `_player_prop_rule`, the new
  regex block, and the new function/tuple; `PLAYER_GOALS` is
  `Scope.PLAYER`/`Shape.OVER_UNDER` in `market_types.py`, and build_rows'
  existing `(SideMode.OVER_UNDER, SideMode.YESNO_AS_OU)` combined branch
  already handles `Scope.PLAYER` entity resolution generically — no
  dispatch changes needed).

**Files changed:**
- `mappers/exchanges/polymarket.py` — generalized `_player_prop_rule` (2 new
  kwarg-only params, backward compatible); added `_Q_SOCCER_PLAYER_GOALS`
  regex + `soccer_player_goals_rule`; added `soccer_market_rules` ordered
  11-tuple with rationale comment. No changes to `build_rows`, `ParsedMarket`,
  `SideMode`, `parse_question`, or any `mappers/leagues/*` module.
- `tests/mappers/test_polymarket_soccer.py` — added `normalize_player_name`
  import; 9 new tests: player-goals ladder (`1+`→0.5, `2+`→1.5) + 3 rejection
  tests (assists/shots/goals+assists) + missing-config guard; a
  `soccer_market_rules` shape/ordering test (11 members, ordering asserts for
  the 5 defensive pairs called out above); an `ALL_SOCCER_CFG` wiring
  `market_rules=pm.soccer_market_rules` + all 9 `market_types` keys, with one
  integration test asserting the team-total-vs-full-total ordering and one
  covering all 11 exact section-C question forms → correct `MarketType`
  end to end via `parse_question`.

**Test commands + counts:**
- `.venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q`
  → `50 passed` (41 pre-existing + 9 new).
- `.venv/bin/python -m pytest tests/mappers/ -q` → `423 passed, 5 skipped`
  (baseline 414 passed/5 skipped + 9 new; goldens unchanged, no test dropped).

**Lint:** `.venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py tests/mappers/test_polymarket_soccer.py`
→ `All checks passed!`

**Concerns:**
- None new for this task's own scope. Two carried-forward notes for Tasks
  6/7 (not blockers here): (1) the `market_types` key set above must be
  copied in full into each league's `PolymarketConfig` — a missing key drops
  that form silently, no error; (2) `task-4b-report.md`'s pipeline fix
  (`_resolve_poly_markets` Phase-B deferral for single-team `THREE_WAY_FIXED`)
  is already merged (commit history shows `d9f9b71` ahead of this task's
  base), so the two single-team 3-way forms (`ml_team_win`,
  `first_half_leader`) resolve fixtures correctly when wired — verified only
  that this task didn't regress it (full suite still green), did not
  re-verify the pipeline fix itself (out of this task's file scope).
