# Task TN3 report — 4 surname-only tennis forms (Tier 2 of the tennis rescue)

Scope: the 4 SURNAME-only tennis forms that CONSUME the TN2 name-granularity
mechanism, + their MarketTypes + atp/wta OpticConfig wiring. All reuse
existing Shapes/SideModes — no `build_rows`/dispatch changes, no
`name_granularity` mechanism changes, no OVER_UNDER logic changes, no new
leagues, no best-of-5 3rd/4th-set forms.

## 1. 6 new MarketTypes (`mappers/market_types.py`)

```python
MATCH_TOTAL_GAMES       = ("match_total_games",     Scope.GAME, Shape.TOTAL)
FIRST_SET_TOTAL_GAMES   = ("1st_set_total_games",   Scope.GAME, Shape.TOTAL)
SECOND_SET_TOTAL_GAMES  = ("2nd_set_total_games",   Scope.GAME, Shape.TOTAL)
SET_HANDICAP            = ("set_handicap",          Scope.GAME, Shape.SPREAD)
FIRST_SET_WINNER        = ("1st_set_winner",        Scope.GAME, Shape.MONEYLINE)
SECOND_SET_WINNER       = ("2nd_set_winner",        Scope.GAME, Shape.MONEYLINE)
```

Added to the Game-scoped block, immediately after `TOTAL_SETS`.

## 2. 4 recognizers + optic market_id wiring (`mappers/exchanges/polymarket.py`)

All 4 set `name_granularity="surname"` on the returned `ParsedMarket` (poly
labels/names in these forms are the last whitespace token of the full name,
per probe section B.2/B.4/B.5/B.6).

| Recognizer | Poly template | Optic market_id → MarketType | SideMode | Scope |
|---|---|---|---|---|
| `tennis_match_total_games_rule` | `<A> vs. <B>: Match O/U <N>` | `total_games` → `MATCH_TOTAL_GAMES` | `OVER_UNDER` | GAME |
| `tennis_set_games_rule` | `<A> vs. <B>: Set <K> Games O/U <N>` | `1st_set_total_games`/`2nd_set_total_games` → `FIRST_SET_TOTAL_GAMES`/`SECOND_SET_TOTAL_GAMES` (K∈{3,4} → `None`) | `OVER_UNDER` | GAME |
| `tennis_set_handicap_rule` | `Set Handicap: <A> (-N) vs <B> (+N)` | `set_handicap` → `SET_HANDICAP` | `SPREAD_TEAM` | GAME |
| `tennis_set_winner_rule` | `Set <K> Winner: <A> vs <B>` | `1st_set_moneyline`/`2nd_set_moneyline` → `FIRST_SET_WINNER`/`SECOND_SET_WINNER` (K∈{3,4} → `None`) | `TEAM_LABEL` (2-way, no Draw) | GAME |

Anchoring (mutual exclusivity, no dispatch ambiguity): `Match O/U` (literal,
distinct from `Total Sets O/U` and `Set K Games O/U`, all three sharing the
`O/U` substring but differing on the preceding word), `Set K Games O/U`
(K captured as a group, `{3,4}` returns `None` — best-of-5 tail, deferred),
`Set Handicap:` (fixed literal prefix, not a tournament name — distinct from
every `A vs B: ...` suffix form), `Set K Winner:` (fixed literal prefix, same
K∈{3,4} deferral as set_games).

`tennis_set_handicap_rule` mirrors `mlb_spread_rule`'s one-team convention:
only the FIRST (named, negative-signed in every live sample) team + its own
signed line is captured into `entity`/`line`; `team_a`/`team_b` stay `None` so
the pipeline resolves the fixture from the two outcome labels (both surnames
per B.5), exactly like `mlb_spread_rule`. `build_rows`'s existing `SPREAD_TEAM`
branch (unmodified, from TN2) then binds `line` to the named side and `-line`
to the other — verified end-to-end by
`test_set_handicap_end_to_end_binds_signed_line_to_named_side` (Gojo −1.5,
Bu +1.5).

`tennis_match_total_games_rule`/`tennis_set_games_rule` (OVER_UNDER, GAME
scope) don't touch `build_rows`'s entity resolution at all (`_resolve_entity`
returns `(True, None)` unconditionally for GAME scope, per TN2's own concern
note) — their `name_granularity="surname"` is consumed exclusively by
`pipeline._match_poly_fixture` for fixture resolution, not by `build_rows`.

### Full updated `TENNIS_MARKET_TYPES` key set

```python
{
    "moneyline": MONEYLINE,
    "total_sets": TOTAL_SETS,
    "match_total_games": MATCH_TOTAL_GAMES,
    "1st_set_total_games": FIRST_SET_TOTAL_GAMES,
    "2nd_set_total_games": SECOND_SET_TOTAL_GAMES,
    "set_handicap": SET_HANDICAP,
    "1st_set_winner": FIRST_SET_WINNER,
    "2nd_set_winner": SECOND_SET_WINNER,
}
```

`tennis_market_rules` order: `tennis_total_sets_rule`, `tennis_set_handicap_rule`,
`tennis_set_winner_rule`, `tennis_match_total_games_rule`, `tennis_set_games_rule`,
`tennis_moneyline_rule` — the two fixed-prefix forms before the two
`A vs B: ...` suffix forms, all four before the bare-`A vs B` moneyline
catch-all (which already self-guards against `\bsets?\b`/`games`/`o/u` via its
own regex, so ordering isn't correctness-critical, just convention-consistent
with every other league).

## 3. atp.py / wta.py wiring

Both `OpticConfig.table_types` gained the 6 entries (`total_games`→
`MATCH_TOTAL_GAMES`, `1st_set_total_games`→`FIRST_SET_TOTAL_GAMES`,
`2nd_set_total_games`→`SECOND_SET_TOTAL_GAMES`, `set_handicap`→
`SET_HANDICAP`, `1st_set_moneyline`→`FIRST_SET_WINNER`, `2nd_set_moneyline`→
`SECOND_SET_WINNER`), and both `OUTPUT_ORDER` tuples now include all 6 new
MarketTypes. `PolymarketConfig` for both leagues already referenced the
shared `TENNIS_MARKET_TYPES`/`tennis_market_rules` (no per-league edit needed
there beyond the dict/tuple growing).

## Best-of-5 deferral — confirmed

`tennis_set_games_rule` and `tennis_set_winner_rule` both return `None` for
K∈{3,4} (the Grand-Slam-only, low-volume tail per probe sections B.4/B.6/C) —
tested explicitly (`test_tennis_set_games_rule_set_3_and_4_return_none`,
`test_tennis_set_winner_rule_set_3_and_4_return_none`). No `3rd_set_*`/
`4th_set_*` MarketType, recognizer, or config entry was added.

## Files changed

- `mappers/market_types.py` — 6 new MarketType members.
- `mappers/exchanges/polymarket.py` — 4 new regexes + 4 new recognizer
  functions; `TENNIS_MARKET_TYPES` grown to 8 keys; `tennis_market_rules`
  grown to 6 rules.
- `mappers/leagues/atp.py` — `OPTIC.table_types` + `OUTPUT_ORDER` grown.
- `mappers/leagues/wta.py` — `OPTIC.table_types` + `OUTPUT_ORDER` grown.
- `tests/mappers/test_polymarket_tennis.py` — 16 new tests (parse-level per
  rule, disjointness, K=3/4→None, atp/wta wiring).
- `tests/mappers/test_polymarket_tennis_integration.py` — 5 new tests
  (`build_rows`/`_match_poly_fixture` end-to-end per form against synthetic
  FULL-name fixtures, set_handicap sign binding, within-fixture surname
  collision drop) + 1 existing test (`test_atp_wta_polymarket_config`)
  updated for the grown `market_types` dict (exact-equality assertion, had to
  be extended rather than left alone).

## Tests

New: **21/21 passed** (`-x -q`, both files together: `tests/mappers/test_polymarket_tennis.py tests/mappers/test_polymarket_tennis_integration.py` → 34 passed, 13 pre-existing + 21 new).

Full suite: `tests/mappers/ -q` → **651 passed, 13 skipped** (baseline before
this task: 630 passed, 13 skipped — exactly `630 + 21 new = 651`; skip count
unchanged, no existing test moved pass↔fail).

## Lint

`ruff check --fix` on all 6 changed files: **all checks passed**, 0 findings.

## Concerns

- `tennis_set_handicap_rule`'s regex captures only the first team's signed
  line (mirroring `mlb_spread_rule`); it does not independently verify the
  second team's parenthesized number is the exact negation of the first (it
  only requires the same shape `(<sign><digits>)`) — this matches
  `mlb_spread_rule`'s existing precedent (which also never cross-checks) and
  `build_rows`'s `SPREAD_TEAM` branch derives the complementary side's line by
  negation anyway, so a mismatched literal second number in the question
  would be silently ignored, not a new risk introduced here.
- `_Q_TENNIS_SET_HANDICAP`/`_Q_TENNIS_SET_WINNER`'s "vs" separator uses the
  same generic `vs\.?` (optional period) as every other rule in this file;
  probe samples for these two forms only show unpunctuated `vs`, but the
  optional-period regex accepts `vs.` too if it ever appears, consistent with
  the rest of the file's convention.
- No new ITF wiring (out of scope per the task and the probe's own collision
  data — ITF isn't onboarded as a league at all yet).
