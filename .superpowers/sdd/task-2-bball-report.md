### Task 2 report: Basketball recognizer surface (WNBA/NBA/NCAAB parity, Wave 5)

**Status:** complete, not blocked.

**Reuse decision.** Per `wave-5-probe-findings.md` sections B/C, WNBA's poly
menu is exactly 6 forms and the game-line 3 (moneyline/total/spread) are
byte-identical in shape to MLB's own question templates, with no
sport-specific ambiguity to guard against (unlike soccer's team-total/half
variants, which forced new soccer-specific regexes). So this task reuses
`mlb_moneyline_rule`, `mlb_total_rule`, `mlb_spread_rule` **directly** in
`basketball_market_rules` — no `basketball_moneyline_rule`/`basketball_total_rule`/
`basketball_spread_rule` duplicates were created. These three rules are
config-driven pure functions (`cfg.market_types.get(...)` resolves the
`MarketType`; `cfg.question_style` drives name normalization); basketball's
own `BASKETBALL_MARKET_TYPES` dict supplies the `MarketType` values, so
reuse costs nothing and avoids duplicated regex/logic that would drift out
of sync with the MLB originals.

Only the 3 player-prop forms are new (`basketball_player_points_rule`,
`basketball_player_rebounds_rule`, `basketball_player_assists_rule`), each a
thin wrapper around the existing `_player_prop_rule` helper with its own
stat regex (mirroring `_Q_HOME_RUNS`'s shape: named `player` group + numeric
group, anchored on the exact stat word so Points/Rebounds/Assists never
cross-match). The **one required deviation** from the MLB template: each
passes `side_mode=SideMode.YESNO_AS_OU` explicitly, not the helper's
`OVER_UNDER` default — WNBA player props use Yes/No outcome labels (probe:
100% across 962 rows), and defaulting to `OVER_UNDER` would silently drop
every one of them (`build_rows`' `OVER_UNDER` branch expects literal
`Over`/`Under` labels it will never see for these markets).

**`BASKETBALL_MARKET_TYPES` key set** (exactly the 6 keys the 6 rules look
up via `cfg.market_types.get(...)`):

```
moneyline        -> MarketType.MONEYLINE       (read by reused mlb_moneyline_rule)
total            -> MarketType.GAME_TOTAL      (read by reused mlb_total_rule)
spread           -> MarketType.POINT_SPREAD    (read by reused mlb_spread_rule)
player_points    -> MarketType.PLAYER_POINTS   (read by new basketball_player_points_rule)
player_rebounds  -> MarketType.PLAYER_REBOUNDS (read by new basketball_player_rebounds_rule)
player_assists   -> MarketType.PLAYER_ASSISTS  (read by new basketball_player_assists_rule)
```

The `moneyline`/`total`/`spread` keys were determined by reading the reused
rules' own `cfg.market_types.get("moneyline"|"total"|"spread")` calls in
`mappers/exchanges/polymarket.py` (not guessed) — they match the keys
already used by `MLB_CFG`/`MLB_FULL_CFG` in `tests/mappers/test_polymarket.py`,
confirming byte-identical reuse. All 6 `MarketType` members
(`MONEYLINE`, `POINT_SPREAD`, `GAME_TOTAL`, `PLAYER_POINTS`, `PLAYER_REBOUNDS`,
`PLAYER_ASSISTS`) were confirmed to exist in `mappers/market_types.py` before
use.

**`basketball_market_rules` ordering.** `(mlb_total_rule, mlb_spread_rule,
basketball_player_points_rule, basketball_player_rebounds_rule,
basketball_player_assists_rule, mlb_moneyline_rule)` — the bare
`"<A> vs. <B>"` moneyline catch-all (colon-guarded: drops anything
containing `:`) is ordered last, mirroring `MLB_FULL_CFG`'s convention in
`test_polymarket.py`, so it can never shadow the colon-bearing total/spread/
player-prop forms above it. Verified mutually exclusive per the brief: total
requires `" vs "` + a trailing `: O/U N`; spread requires the exact
`"Spread:"` prefix; the 3 player props require a bare stat word right after
`"<Player>: "` with no `" vs "` anywhere; moneyline is the bare, colon-free
`"<A> vs. <B>"`. Every rule is also self-guarding via its own regex anchor
(pre-existing for the 3 reused rules; the 3 new stat regexes are individually
anchored on their own stat literal), so the ordering is belt-and-suspenders,
not load-bearing.

**Files changed:**
- `mappers/exchanges/polymarket.py` — added 3 stat regexes
  (`_Q_BB_POINTS`/`_Q_BB_REBOUNDS`/`_Q_BB_ASSISTS`), 3 new rule functions
  (`basketball_player_points_rule`/`basketball_player_rebounds_rule`/
  `basketball_player_assists_rule`), `BASKETBALL_MARKET_TYPES` dict, and
  `basketball_market_rules` tuple. Pure addition — `build_rows`, the MLB/
  soccer rule functions, and every other existing symbol are untouched
  (confirmed via `git diff --stat`: 98 insertions, 0 deletions).
- `tests/mappers/test_polymarket_basketball.py` — new file, 19 tests.

**Test counts:**
- `tests/mappers/test_polymarket_basketball.py`: **19 passed** (parse tests
  for all 6 forms incl. cross-rejection guards; the YESNO_AS_OU
  `build_rows` integration test incl. an index-swapped inversion-safety
  variant; the ordered-tuple-of-6 check; the full-6-form `parse_question`
  dispatch check via `BB_CFG`; 4 disjointness/ordering tests;
  `BASKETBALL_MARKET_TYPES` key-set check).
- Full suite, `tests/mappers/` (TDD red confirmed first: collection failed
  with `AttributeError: module 'mappers.exchanges.polymarket' has no
  attribute 'BASKETBALL_MARKET_TYPES'` before implementation):
  **before: 496 passed, 11 skipped** → **after: 515 passed, 11 skipped**
  (515 = 496 + 19 new; zero existing tests dropped or changed — goldens
  unchanged). Note: the task brief quoted a baseline of "573 passed/11
  skipped" — this checkout's actual pre-change baseline was 496/11; treating
  the brief's number as stale/copied from a different task context rather
  than a discrepancy to chase, since what matters (no drop, +19 exact) holds.

**Lint:** `.venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py
tests/mappers/test_polymarket_basketball.py` → `All checks passed!`.

**Concerns:**
- Per the probe (section A), the 3 player-prop `table_types`
  (`player_points`/`player_assists`/`player_rebounds`) were **not** observed
  live on Optic's side yet (all posted WNBA fixtures were 5+ days out;
  every other sportsbook board for these props hadn't opened). This task
  only builds the poly-side recognizer surface — it does not assert Optic
  coverage — so it's unaffected, but whoever wires WNBA's `OpticConfig`/
  `POLYMARKET` config next (the brief's "wired next task") should do the
  probe's recommended same-day-of-game reconfirmation before shipping live.
- `nbasl` (NBA Summer League) and NBA/NCAAB's fuller Kalshi-parity prop menu
  (threes/blocks/steals/turnovers/DD/TD) are explicitly out of scope per the
  probe (0% Optic coverage / unconfirmed poly demand respectively) — no
  recognizer was built for either, matching the brief's "do NOT build a
  matcher for it" instruction for `nbasl`.
- No league wiring (`mappers/leagues/*`), no `build_rows` changes — both
  explicitly out of scope for this task and left untouched.
