# Task U1: UFC (MMA) matcher v1 — report

## Slug-format verification (the task's core "does the gate design fit" question)

**Real evidence, not assumption.** Pulled `ufc_bridge_dump.json` (the probe's
raw scratch dump, 346 markets) and found the sibling markets for one real
fight (condition_id
`0xb8d1db7f6264ed8c4eae9c18f32bc213ae23048c2e013d730ef537e0a6cad208`):

```
ufc-alb10-tom15-2026-07-18                      | UFC Fight Night: Alberto Montes vs. Tommy McMillen (...)
ufc-alb10-tom15-2026-07-18-go-the-distance      | Fight to Go the Distance?
ufc-alb10-tom15-2026-07-18-mcmillen-win-by-ko-tko | Will Tommy McMillen win by KO or TKO?   (DROPPED form)
ufc-alb10-tom15-2026-07-18-montes-win-by-ko-tko   | Will Alberto Montes win by KO or TKO?   (DROPPED form)
ufc-alb10-tom15-2026-07-18-totals-0pt5          | O/U 0.5 Rounds
ufc-alb10-tom15-2026-07-18-win-by-ko-tko        | Will the fight be won by KO or TKO?
ufc-alb10-tom15-2026-07-18-win-by-submission    | Will the fight be won by submission?   (DROPPED form)
```

Ran `pipeline._poly_slug_teams`/`_poly_market_date` directly against these
real strings: all 5 non-dropped forms produce the identical key
`(('alb10','tom15'), '2026-07-18')`. **Confirmed: Phase-B resolves the
0-fighter forms**, seeded by the moneyline's Phase-A resolution. (a) yes,
the slug encodes the fighter pair + date; (b) yes, the moneyline shares that
key. Not BLOCKED.

**Second, live end-to-end confirmation** (see §Validation): ran
`_resolve_poly_markets` against the real 2026-07-25 card's 113 UFC poly
markets + 16 real Optic fixtures — 34 `total_rounds`, 10
`fight_goes_distance`, 10 `game_win_by_kotko` markets resolved via the new
Phase-B gate; 14 `moneyline` via Phase A (unchanged); the other 34 markets
are exactly the 2 dropped forms parsing to `None` (12 submission + 22
fighter-KO/TKO); 11 genuinely `no_fixture`. Zero unexpected drops.

## Design conflicts found and resolved (both purely additive, both verified byte-identical for existing leagues)

1. **Pipeline gate**: the literal instruction (`scope is Scope.GAME and
   team_a is None`) would also have swept `SideMode.SPREAD_TEAM` markets
   (mlb_spread_rule / soccer_spread_rule / tennis_set_handicap_rule — the
   only 3 existing rules that already set `team_a=None`) into Phase B,
   changing an already-working Phase-A path (outcome-label resolution) to a
   slug-key path. Added `and parsed.side_mode is not SideMode.SPREAD_TEAM` to
   the new clause. Verified: `test_resolve_poly_markets_spread_resolves_via_outcome_labels`
   (pre-existing) still passes unchanged — SPREAD_TEAM stays on Phase A.

2. **`_name_match` alias gap**: `team_name_aliases` (needed for the 2
   fighter aliases) was **never actually consulted under
   `question_style="tennis_prefix"`** — the function returned `a == b`
   before ever reaching the alias-substitution block. No tennis_prefix
   league (ATP/WTA) had ever populated the dict, so this was invisible until
   now. Reordered the alias substitution to run before the style branch.
   Byte-identical for every existing caller (ATP/WTA ship `{}`, mlb_suffix
   leagues see the same substitution in the same place). Proven live by
   `test_zaynukov_alias_without_scope_does_not_match` (fails without the
   overlay) vs `test_zaynukov_alias_resolves_fixture` (passes with it).

## (1) 3 new MarketTypes (`market_types.py`)

- `TOTAL_ROUNDS = ("total_rounds", Scope.GAME, Shape.TOTAL)`
- `FIGHT_GOES_DISTANCE = ("fight_goes_distance", Scope.GAME, Shape.YES_NO)`
- `GAME_WIN_BY_KOTKO = ("game_win_by_kotko", Scope.GAME, Shape.YES_NO)`
- Fighter moneyline reuses `MarketType.MONEYLINE` verbatim — no new constant.

## (2) Pipeline gate (`pipeline.py::_resolve_poly_markets`)

```python
zero_competitor_game_form = (
    parsed.market_type.scope is Scope.GAME
    and parsed.team_a is None
    and parsed.side_mode is not polymarket.SideMode.SPREAD_TEAM
)
if (parsed.market_type.scope is Scope.PLAYER
        or single_team_three_way
        or zero_competitor_game_form):
    deferred.append((market, parsed))
```
Purely additive to the existing `Scope.PLAYER or single_team_three_way` gate.

## (3) 4 recognizers (`polymarket.py`)

`ufc_moneyline_rule`, `ufc_total_rounds_rule`, `ufc_go_the_distance_rule`,
`ufc_game_win_by_kotko_rule` + `UFC_MARKET_TYPES` dict + `ufc_market_rules`
tuple. Moneyline regex `^UFC.*?:\s*(.+?)\s+vs\.?\s+(.+?)\s*\(` strips the
trailing `(Weightclass, Card)` parenthetical (the one thing tennis's
moneyline regex didn't anticipate).

## (4) Dropped forms (not built, by design)

- `Will the fight be won by submission?` (GAME_WIN_BY_SUBMISSION) — no clean
  optic target.
- `Will <Fighter> win by KO or TKO?` (FIGHTER_WIN_BY_KOTKO) — only clean
  optic target bundles KO/TKO+Submission+DQ ("any finish"), a broader/wrong
  proposition; the exact target needs a market_id+name-suffix bucketer that
  doesn't exist in optic.py. Neither gets a MarketType or recognizer; both
  verified via guard tests to return `None`.

## (5) `ufc.py` wiring

`OpticConfig(league_id="ufc", table_types={moneyline, total_rounds,
go_the_distance, win_by_ko_tko})`, `PolymarketConfig(slug_prefix="ufc",
optic_league_id="ufc", question_style="tennis_prefix",
market_rules=ufc_market_rules, team_name_aliases=<2 fighter aliases>)`,
`LeagueConfig(KALSHI=None, PX=None, ...)`. Registered in `run.py` `LEAGUES`.
`League.UFC`/`_LEAGUE_SPORT[League.UFC]=Sport.MMA` already existed (no
change needed). Added `League.UFC: "opticodds_access_key"` to
`fetch/optic.py`'s `LEAGUE_SECRET` (required — its import-time assert
`LEAGUE_SECRET.keys() >= SUPPORTED_LEAGUES.keys()` would otherwise fail the
instant UFC joined `LEAGUES`).

## Aliases

`normalize_player_name("Magomed Zaynukov") -> normalize_player_name("Magomed Zayunokov")`,
`normalize_player_name("Seokhyeon Ko") -> normalize_player_name("Seok Hyun Ko")`.

## Validation (real data, live card confirmed)

A card WAS in-window: `--horizon-hours 96` from 2026-07-23 surfaced 18 Optic
UFC fixtures for the 2026-07-25 card. Fetched real `fetch.optic --league ufc`
+ `fetch.polymarket` data (secret access worked directly via `gcloud secrets
versions access`, no ADC workaround needed).

**Blocker hit and worked around (validation-only, not shipped):** Optic
ships **empty abbreviations for every UFC fighter** (same gap tennis solves
via `mappers.tennis_bootstrap` + `config/atp/team_aliases.toml`, which UFC
has no equivalent of — building that bootstrap is out of task-u1's scope,
a separate follow-up). `mappers.run` failed with `ValueError: ... has an
empty abbreviation for league 'ufc'` before any of my mapping code even
runs. Worked around **for validation only** by generating a throwaway
`config/ufc/team_aliases.toml` (competitor_id -> competitor_id, guaranteed
unique) to unblock `optic.load_fixtures`; deleted before finishing (`git
status` confirms nothing untracked remains under `config/`).

With that workaround, `python -m mappers.run data/2026-07-23/13_00 --league
ufc --json` ran clean end-to-end:
```
optic: 16 fixtures loaded
polymarket [ufc]: 16 stamped, 14 dropped (optic didn't price), 11 no fixture,
                  34 non-game-line, 106 agree, 0 conflict-dropped
```
0 conflict-dropped confirms guard#4 never disagreed with Optic's own
Polymarket ingestion. Direct `_resolve_poly_markets` call against the real
113 UFC poly markets + 16 fixtures: 68 resolved (`total_rounds` 34,
`moneyline` 14, `game_win_by_kotko` 10, `fight_goes_distance` 10), 34
unparsed (100% = the 2 dropped forms: 12 submission + 22 fighter-KO/TKO,
zero unexpected unrecognized questions), 11 no_fixture. **Fighter names
resolved correctly; all 4 built forms stamp; 0 mismatches.**

Follow-up needed before this is production-ready: a UFC fighter-abbreviation
bootstrap (tennis_bootstrap-equivalent, or an `abbr_overrides` source) —
outside task-u1's scope, flagged for a separate task.

## Files changed

- `mappers/market_types.py` — 3 new MarketTypes.
- `mappers/pipeline.py` — Phase-B gate extension (docstring + condition).
- `mappers/exchanges/polymarket.py` — 4 UFC recognizers + `UFC_MARKET_TYPES`
  + `ufc_market_rules`; `_name_match` alias-ordering fix.
- `mappers/leagues/ufc.py` — new league module.
- `mappers/run.py` — `ufc` import + `LEAGUES` entry + stale-comment fix.
- `fetch/optic.py` — `LEAGUE_SECRET[League.UFC]`.
- `tests/mappers/test_polymarket_ufc.py` — new, 28 tests.

## Test counts

- New file: 28 passed.
- `tests/mappers/`: 713 passed, 19 skipped (baseline 684/17 + 28 new tests +
  1 new parametrized `test_output_order_covers_all_used_types[ufc]` + 2 new
  skipped Kalshi/PX-parametrized instances for `ufc` — all additive, zero
  existing tests moved/changed/skipped differently).
- Full `tests/`: 792 passed, 19 skipped (`GCP_PROJECT=marketmaking-test`
  needed for collection — pre-existing repo quirk, confirmed via
  `git stash` unrelated to this change).
- `ruff check` on all changed files: 0 new findings (7 pre-existing findings
  in `mappers/pipeline.py`/`mappers/run.py`/`fetch/optic.py` untouched,
  confirmed identical via `git stash` diff before/after).

## Concerns

1. UFC fighter-abbreviation bootstrap gap (see Validation) blocks real
   production runs today — needs its own follow-up task.
2. `_name_match`'s alias-ordering fix touches shared code beyond the
   letter of "don't change existing recognizers" — justified because it was
   a latent no-op bug (aliases silently ignored under tennis_prefix) that
   the task's own aliasing requirement cannot work without; verified
   byte-identical for every existing tennis_prefix/mlb_suffix caller.
3. `GAME_WIN_BY_SUBMISSION`/`FIGHTER_WIN_BY_KOTKO` remain unbuilt (33%/114
   markets of the census) — intentional v1 scope cut per the task.
