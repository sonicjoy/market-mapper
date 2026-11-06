### Task 4b report: pipeline fix — single-team GAME-scope THREE_WAY_FIXED resolution

**Status:** complete, not blocked.

**Diagnosis confirmed (matches the flagged gap in `task-4-report.md`, "Concerns"):**

`_resolve_poly_markets` (`mappers/pipeline.py`) is a two-phase resolver. Phase A
(`_match_poly_game_fixture` → `_match_poly_fixture`) matches a market to a
fixture by team NAME and requires both `team_a` and `team_b` (`_name_match`
returns `False` when either operand is empty). Phase B is a fallback keyed on
`(frozenset(_poly_slug_teams(slug)), date)`, seeded by any Phase-A market that
resolved for the same fixture; before this fix it was entered only for
`parsed.market_type.scope is Scope.PLAYER`.

`soccer_ml_team_win_rule` ("Will `<Team>` win on `<DATE>`?") and
`soccer_first_half_leader_rule` ("`<Team>` leading at halftime?") emit
GAME-scope `THREE_WAY_FIXED` `ParsedMarket`s with `team_b=None` (only one team
is ever named; outcome labels are Yes/No, so `SPREAD_TEAM`'s label-rescue path
in `_match_poly_game_fixture` doesn't apply either). Result: Phase A's
`_name_match` fails on the empty `team_b`, the market drops as `no_fixture`,
and Phase B never runs for it (wrong scope gate) — so these two recognizers
produced correct `ParsedMarket`s that never resolved a fixture end-to-end,
silently emitting **zero stamps**. Verified by writing a failing test first
(`test_resolve_poly_markets_three_way_team_win_resolves_via_seeded_draw`)
against the unmodified code — it failed with `KeyError` (market absent from
`resolved`), confirming the drop.

The DRAW sub-markets (`soccer_ml_draw_rule`, `soccer_first_half_draw_rule`)
name BOTH teams, so they resolve in Phase A and seed `fixture_by_slug_key` for
the fixture — meaning seeding is guaranteed whenever the draw market is present
in the same run, exactly as the brief describes.

**The fix:** extended the Phase-B deferral condition in `_resolve_poly_markets`
to also defer single-team `THREE_WAY_FIXED` markets:

```python
single_team_three_way = (
    parsed.side_mode is polymarket.SideMode.THREE_WAY_FIXED and parsed.team_b is None
)
if parsed.market_type.scope is Scope.PLAYER or single_team_three_way:
    deferred.append((market, parsed))  # Phase B (needs the full map)
    continue
```

(previously: `if parsed.market_type.scope is Scope.PLAYER:`). Nothing else in
the two-phase structure changed — Phase B still resolves via the same
`(frozenset(_poly_slug_teams(slug)), date)` slug-token key already used for
player props, keying purely on slug-token equality (never team-identity
interpretation), so flip-safety is preserved. The DRAW forms (`team_b` set)
are untouched — `single_team_three_way` is `False` for them, so they stay on
the Phase A path exactly as before.

**Files changed:**
- `mappers/pipeline.py` — `_resolve_poly_markets`: extended the Phase-B
  deferral condition (as above) + updated the function's docstring to
  describe the new deferral case. No changes to `build_rows`,
  `_match_poly_game_fixture`, `_match_poly_fixture`, `_poly_slug_teams`, or any
  recognizer in `mappers/exchanges/polymarket.py`.
- `tests/mappers/test_polymarket_pipeline.py` — added a `_soccer_ml_cfg()`
  helper (wires only `soccer_ml_team_win_rule` + `soccer_ml_draw_rule`; no
  league is wired yet) and 4 new tests under a `Task 4b` section:
  1. `test_resolve_poly_markets_three_way_team_win_resolves_via_seeded_draw` —
     the single-team team-win market resolves in Phase B when the draw
     sub-market seeds `fixture_by_slug_key` (RED before the fix — `KeyError`;
     GREEN after).
  2. `test_resolve_poly_markets_three_way_team_win_drops_when_unseeded` —
     same market with nothing to seed its slug key drops gracefully, counted
     `no_fixture` (already passed pre-fix, via a different code path — same
     outcome, correct either way).
  3. `test_resolve_poly_markets_three_way_draw_still_resolves_via_phase_a` —
     regression: the DRAW form (both teams named) keeps resolving via Phase A
     unchanged.
  4. `test_resolve_poly_markets_player_scope_still_defers_regression` —
     regression: a PLAYER-scope market (MLB prop) still defers to Phase B as
     before.

**Test commands + counts:**
- New tests only: `.venv/bin/python -m pytest tests/mappers/test_polymarket_pipeline.py -x -q`
  → `18 passed` (14 pre-existing + 4 new).
- Full suite: `.venv/bin/python -m pytest tests/mappers/ -q`
  → `414 passed, 5 skipped` (baseline 410 passed/5 skipped + 4 new; goldens
  unchanged, no test dropped).

**Lint:** `.venv/bin/python -m ruff check --fix mappers/pipeline.py tests/mappers/test_polymarket_pipeline.py`
→ 2 pre-existing findings unrelated to this change (`SIM108` at line 153,
`UP014` `MarmadMatch` NamedTuple at line ~1222 — both present identically on
the pre-fix commit, verified via `git stash`/ruff/`git stash pop`). The test
file and all lines touched by this fix are clean (`ruff check` on the test
file alone → `All checks passed!`).

**Concerns:** none new. The pre-existing ruff findings above are out of scope
(unrelated lines, unrelated to the two-phase resolver). This closes the gap
flagged in `task-4-report.md`; `soccer_ml_team_win_rule` and
`soccer_first_half_leader_rule` will now produce end-to-end stamps whenever
their fixture's draw (or any other same-fixture Phase-A market) market is
present in the same poly pull to seed the slug key — consistent with the
existing player-prop dependency on a sibling game market.
