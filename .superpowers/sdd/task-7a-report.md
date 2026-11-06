### Task 7a report: wire MLS (poly-only, KALSHI=None) + the poly team-name alias overlay

**Status:** complete, not blocked. (Liga MX/UCL NOT touched — out of scope for this turn per the assignment.)

**Alias-overlay design (deliverable #1):**

- **Field:** `PolymarketConfig.team_name_aliases: dict[str, str] = field(default_factory=dict)`
  (`mappers/exchanges/polymarket.py`) — maps a `_norm_name`'d poly team name →
  the `_norm_name`'d optic name it should be treated as equivalent to. Empty
  by default; every pre-Task-7 league is unaffected.
- **Where it plugs in:** NOT threaded through as a new parameter, because
  `build_rows` (frozen) calls `_name_match` directly with no `PolymarketConfig`
  in reach at several sites — `THREE_WAY_FIXED`'s `fixed_side_team` check and
  `SPREAD_TEAM`'s per-outcome label check both need the alias too (moneyline
  and spread are exactly the forms most of the 5 mismatched MLS franchises
  hit), and there's no way to pass a 4th argument into those call sites
  without editing `build_rows` itself. So the mechanism is an **ambient scope**
  instead:
  - `polymarket._active_team_aliases: dict[str, str] = {}` (module-level) +
    `polymarket.team_alias_scope(aliases)` (a `contextlib.contextmanager` that
    sets/restores it).
  - `_name_match(a, b, style)` — unchanged signature — now does
    `if _active_team_aliases: a = ...get(a, a); b = ...get(b, b)` before the
    plain `a == b or a in b or b in a` containment check. Empty dict (no open
    scope) is a byte-identical no-op.
  - `mappers/pipeline.py`'s Polymarket pass wraps its existing
    `_resolve_poly_markets(...)` + `build_rows(...)` loop in
    `with polymarket.team_alias_scope(pcfg.team_name_aliases):` — one `with`
    per league, so `_match_poly_fixture` (fixture resolution) AND every
    `build_rows`-internal `_name_match` call (entity/label resolution) see the
    same alias table for that league's whole pass.
- **How Liga MX/UCL will reuse it:** declare their own `TEAM_NAME_ALIASES: dict[str, str]`
  in `liga_mx.py`/`ucl.py` (same `_norm_name(poly_name, "mlb_suffix")` →
  `_norm_name(optic_name, "mlb_suffix")` shape as MLS's) and pass it as
  `PolymarketConfig(..., team_name_aliases=TEAM_NAME_ALIASES)`. No further
  changes to `polymarket.py` or `pipeline.py` needed — the scope is opened
  generically off `pcfg.team_name_aliases` for whichever league is running.
- **Nothing touched:** `build_rows`, `soccer_market_rules`, the soccer
  recognizer functions — only `_name_match`'s body (not its signature) and a
  new `PolymarketConfig` field + context manager gained code.

**MLS league module (deliverable #2):** new `mappers/leagues/mls.py`.
- `OPTIC = OpticConfig(league_id="usa_-_major_league_soccer", table_types={...})`
  — the exact 9-key soccer subset mirroring `world_cup.py` (`moneyline`→MONEYLINE_3WAY,
  `asian_handicap`→POINT_SPREAD, `total_goals`→GAME_TOTAL, `team_total`→TEAM_TOTAL,
  `1st_half_moneyline`→FIRST_HALF_WINNER_3WAY, `1st_half_total_goals`→FIRST_HALF_TOTAL,
  `both_teams_to_score`→BTTS, `1st_half_both_teams_to_score`→FIRST_HALF_BTTS,
  `player_goals`→PLAYER_GOALS). All 9 optic market_ids confirmed present on the
  probed MLS fixture (wave-4 probe section A); `player_goals` is dead weight on
  the poly side specifically (poly never asks MLS's "N+ goals" ladder — 0/8,330
  bridge rows, section C) but harmless per the established over-include-is-
  fail-safe principle.
- `POLYMARKET = PolymarketConfig(slug_prefix="mls", optic_league_id="usa_-_major_league_soccer", market_types=SOCCER_MARKET_TYPES, question_style="mlb_suffix", market_rules=soccer_market_rules, team_name_aliases=TEAM_NAME_ALIASES)`
  — `slug_prefix`/`optic_league_id` confirmed against live data (section A/C),
  unlike EPL's flagged best-guess.
- `TEAM_NAME_ALIASES`: the 5 entries from wave-4-probe-findings.md section D
  (CF Montréal↔Club de Foot Montréal, Los Angeles Galaxy↔LA Galaxy, New York
  City FC↔New York City Football Club, D.C. United SC↔DC United, Inter Miami
  CF↔Club Internacional de Fútbol Miami), each side run through
  `_norm_name(name, "mlb_suffix")`.
- `LEAGUE = LeagueConfig(league=League.MLS, KALSHI=None, PX=None, OPTIC=OPTIC, OUTPUT_ORDER=OUTPUT_ORDER, MarketType=MarketType, POLYMARKET=POLYMARKET)`
  — CRYPTO/RUNSHOP omitted (dataclass defaults already `None`); `OUTPUT_ORDER`
  covers exactly the 9 `OpticConfig.table_types` values (required by
  `test_table_completeness.py::test_output_order_covers_all_used_types`, which
  auto-parametrizes over the `LEAGUES` registry).

**Registration (deliverable #3):** `LEAGUES` (defined in `mappers/run.py`, not
`mappers/leagues/__init__.py` — that file only holds the `League`/`Sport`
enums) now has `League.MLS: mls.LEAGUE`; import line updated to include `mls`.
`--league mls` confirmed as a valid argparse choice (`python -m mappers.run --help`).

**KALSHI=None safety (deliverable #4):** MLS is the first `KALSHI=None`
league (`PX=None` already existed for atp/nfl/nhl/world_cup/wta, so that half
of the ledger item was pre-covered). Audited every `.KALSHI.` access:
- `scripts/list_aliases.py:326-328` — was `kalshi_prefix: str = league_cfg.KALSHI.prefix`
  (unguarded, would crash for MLS). Fixed: `kalshi_prefix: str | None = (league_cfg.KALSHI.prefix if league_cfg.KALSHI is not None else None)`,
  and `kalshi_names = _load_kalshi_names(args.dirs, kalshi_prefix) if kalshi_prefix is not None else {}`
  — mirrors `probe_kalshi_catalog.py:29`'s `if cfg.KALSHI is not None` guard;
  the rest of `main()` only ever does `code in kalshi_names` membership checks,
  so an empty dict degrades cleanly (prints `kalshi: —` for every canonical,
  same as a league with genuinely no Kalshi data in the fetched dir).
- `scripts/probe_kalshi_catalog.py:29` — already guarded (`if cfg.KALSHI is not None`); no change needed.
- `mappers/pipeline.py:955` (`kalshi_cfg = league.KALSHI` then gated `if kalshi_cfg is not None:`)
  and `:1476`/`:1609` (same `kalshi_cfg`/`if kalshi_cfg is not None:` gates) —
  confirmed already properly guarded, no change needed.
- `tests/mappers/test_table_completeness.py:31-34,60-61` — already
  parametrized-and-skip / `if league.KALSHI is not None:` guarded; adding MLS
  to `LEAGUES` produces 2 new *skipped* rows there (Kalshi-disjoint check,
  PX-suffix-order check) rather than failures.
- **Not touched (pre-existing, out of scope):** `scripts/list_aliases.py:326`
  (`league_cfg.PX.tournament_id`), `scripts/check_px_drift.py:98`, and
  `scripts/audit_px_aliases.py:125` are ALSO unguarded on `.PX.`, but that gap
  predates this task (`PX=None` already exists for 5 leagues) and the brief
  only asked to guard the `KALSHI` ledger item — flagging as a pre-existing gap,
  not fixing it here (scope creep on an unrelated bug).

**Files changed:**
- `mappers/exchanges/polymarket.py` — `team_name_aliases` field on
  `PolymarketConfig`; `_active_team_aliases` + `team_alias_scope` +
  `_name_match` alias consult; `field`/`contextlib` imports added.
- `mappers/pipeline.py` — wrapped the per-league Polymarket
  resolve+build_rows loop in `with polymarket.team_alias_scope(pcfg.team_name_aliases):`.
- `mappers/leagues/mls.py` — new file (league module, per above).
- `mappers/run.py` — `mls` import + `League.MLS: mls.LEAGUE` in `LEAGUES`.
- `scripts/list_aliases.py` — KALSHI=None guard (see above).
- `tests/mappers/test_polymarket_soccer.py` — `_match_poly_fixture` import;
  12 new tests (registry: `test_mls_in_leagues`, `test_mls_kalshi_is_none`,
  `test_mls_polymarket_config_present`,
  `test_mls_optic_table_types_covers_9_soccer_market_types`; alias overlay:
  one resolving test per each of the 5 franchises
  (`test_mls_alias_resolves_{cf_montreal,la_galaxy,nycfc,dc_united,inter_miami}_fixture`),
  `test_mls_alias_without_scope_does_not_match` (proves the overlay, not
  incidental normalization, is what bridges the gap),
  `test_mls_alias_regression_normal_franchise_still_matches` (Austin FC↔Austin
  FC, plain containment, scope active but inert),
  `test_mls_alias_genuinely_absent_team_still_drops` (Toronto FC/Charlotte FC
  vs a fixture that's neither — must still return `None`)).

**Test counts:**
- `.venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q` → `67 passed` (55 pre-existing + 12 new).
- `.venv/bin/python -m pytest tests/mappers/ -q` → `441 passed, 7 skipped`
  (baseline 428 passed/5 skipped + 12 new explicit tests + 1 new auto-parametrized
  `test_output_order_covers_all_used_types[mls]` pass + 2 new auto-parametrized
  skips (`test_kalshi_table_types_and_ignored_disjoint[mls]`,
  `test_px_suffix_longest_first[mls]`) = 441/7; no pre-existing test dropped
  or newly failing).

**Goldens unchanged (structural argument):** identical reasoning to Task 6 —
`gold_row()` extracts only the 12 non-polymarket fields; `attach_polymarket_row`
only ever stamps polymarket_* fields onto an *already-existing* optic row, none
of which are in `gold_row()`'s set. Additionally here: `_active_team_aliases`
defaults to `{}` for every league whose `PolymarketConfig.team_name_aliases`
is the default empty dict (i.e. every league except MLS), so `_name_match`'s
new alias-lookup branch (`if _active_team_aliases:`) never executes for
EPL/WORLD_CUP/MLB/ATP/WTA — behavior for those leagues is unchanged by
construction, not merely by absence of a live-data run. No `data/` fetch
directory was present in this environment to run `scripts/check_gold.py`
against real MLS bridge rows (same limitation noted in the Task 6 report).

**Lint:** `.venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py mappers/pipeline.py mappers/run.py mappers/leagues/mls.py scripts/list_aliases.py tests/mappers/test_polymarket_soccer.py`
→ 2 auto-fixes (import-order on `run.py`'s `LEAGUES` import line and a blank-line
nit in `list_aliases.py`), then clean re-run except 2 **pre-existing** findings
untouched by this diff (`pipeline.py:153` SIM108, `pipeline.py:1222` UP014,
`run.py:4` E501 in the module's original usage-line docstring) — none on
lines this task changed (confirmed via `git diff` line ranges); ruff config
itself is documented "warn-only... legacy backlog" at `pyproject.toml:20`.
`pyright` on all 5 changed files: `0 errors, 0 warnings, 0 informations`.

**Concerns:**
- `player_goals` in MLS's `OPTIC.table_types` is confirmed dead code on the
  poly side (0/8,330 mls/mex/ucl bridge rows ask the "N+ goals" ladder per
  section C) — kept per the brief's explicit instruction to mirror world_cup's
  9-key set; harmless, same as any other optic-prices-it-poly-doesn't-ask gap.
- The pre-existing unguarded `.PX.tournament_id` sites (`list_aliases.py:326`,
  `check_px_drift.py:98`, `audit_px_aliases.py:125`) are a real gap for any of
  the 5 existing `PX=None` leagues too, not introduced by this task — flagging
  in case a follow-up wants it swept in one pass with the Kalshi ledger item.
- Liga MX/UCL are NOT wired (per the brief's explicit "MLS portion only" scope
  for this turn) — `team_name_aliases` and the rest of `mls.py`'s pattern are
  designed to be copy-shaped for both, per the reuse note above.
