# MM-516: PX `sup_moneyline` for `POINT_SPREAD` (EPL "Spread (Regular Time)")

Linear: https://linear.app/whiteswandata/issue/MM-516

## Problem

EPL "Spread (Regular Time)" is PX-provided only as `type=sup_moneyline`,
never as `type=spread`. `classify_market` (`mappers/exchanges/px.py:431`)
raises:

    ValueError: PX market 'Spread (Regular Time)':
                sup_moneyline with no _YN variant for point_spread

`_SUP_MONEYLINE_REMAP` only covers `OVER_UNDER` player-prop → `YES_NO_LINE`
pairs. There is no `POINT_SPREAD_YN` entry, and even if there were, the
existing `_parse_sup_moneyline_line` regex (`Over|Under \d+`) would not
parse the spread display-name format.

## Data shape (verified against `data/2026-04-30/14_55/`)

All 7 EPL events: exactly one "Spread (Regular Time)" market each, all
`type=sup_moneyline`. Sample:

    {"id": 1500024137, "name": "Spread (Regular Time)",
     "type": "sup_moneyline", "line": 0,
     "selections": [
       {"display_name": "BRE -0.5", "line": 0,
        "line_id": "...", "outcome_id": 1},
       {"display_name": "WHU +0.5", "line": 0,
        "line_id": "...", "outcome_id": 2}
     ],
     "sport_event_id": 90091343}

Observed handicap values across the 7 events: ±0.5 (5 events),
±1.5 (2 events). Always one symmetric pair per event.

Invariants (across all 7):
- 2 selections, `outcome_ids == {1, 2}`, `selection.line == 0`,
  `market.line == 0`
- Handicap encoded in `display_name`; selections are NOT
  `competitor_id`-bearing
- `outcome_id == 1` is **not** consistently home or favourite
  (`WOL +0.5` is oid=1; `LEE -1.5` is also oid=1) — team identity must
  come from parsing the team code in `display_name`

## Why this is not a simple `_YN` addition

Prior `_YN` additions (e.g. `df65df8` PLAYER_ASSISTS_YN) were all
`Shape.OVER_UNDER` → `Shape.YES_NO_LINE` pairs with identical
`Over N.N` / `Under N.N` display-name format. This case differs:
- Game-scope, not player-scope
- Handicap embedded in team-bearing display_name, not
  `Over|Under N.N`
- Single line per event, not multi-line `market_lines`
- `outcome_ids {1,2}` would normally resolve to `yes`/`no` via
  `_FIXED_SIDE_LABELS`, but for matching against Optic
  `asian_handicap` we need team sides

## Design

### 1. Shape: `Shape.SPREAD`, not `Shape.YES_NO_LINE`

Existing `*_YN` types are `YES_NO_LINE` because their semantics are
genuinely yes/no. Here the two outcomes are team-vs-team. Using
`YES_NO_LINE` would force sides to yes/no and orphan the rows from
Optic merging.

`Shape.SPREAD` makes `build_rows` produce signed-per-team rows like
a regular `POINT_SPREAD`, and the existing downgrade logic (see §7)
works.

### 2. New MarketType (`mappers/market_types.py`)

    POINT_SPREAD_YN = ("point_spread_yn", Scope.GAME, Shape.SPREAD)

### 3. Remap (`mappers/exchanges/px.py`)

    _SUP_MONEYLINE_REMAP[MarketType.POINT_SPREAD] = (
        MarketType.POINT_SPREAD_YN)

### 4. Cross-check ordering in `classify_market`

`_PX_TYPE_FOR_SHAPE` says `Shape.SPREAD → "spread"`. After remap
the shape is unchanged (still `SPREAD`) but PX type is
`sup_moneyline`. The cross-check (currently after the remap)
would fire false-positive.

Move the type cross-check to run on the **pre-remap** shape — the
cross-check's purpose is "name matched X but PX type disagrees".
After `sup_moneyline` is resolved to its YN variant, the type is
by definition `sup_moneyline` and there's nothing more to check.

### 5. Parsing dispatch

Split `_parse_sup_moneyline_line` into a dispatcher that tries:

- **OU flavor** — `^(?:Over|Under)\s+([\d.]+)$` → returns one shared
  unsigned line; selections returned unchanged.
- **Spread flavor** — `^(.+?)\s+([+-][\d.]+)$` → parses signed
  handicap per selection; validates symmetry (`sum == 0`); returns
  selections with `spread_line` overridden to the parsed signed value
  and `team_abbr` populated with the captured prefix.

Falls back to `ValueError` if neither matches.

The team-code group is permissive (`.+?`) so the same parser handles
EPL's 3-char abbreviations (e.g. `"BRE -0.5"`) and the full-team-name
format used by NBA regular-spread display names (e.g.
`"Atlanta Hawks +0.5"`) if `sup_moneyline` ever ships for those
leagues. The real validation is the alias-table membership check
in §8 — a junk prefix parses successfully but fails when it can't
resolve to one of the event's two competitors, raising with a clear
"team X not in event Y" error.

### 6. Selection enrichment for team identity

**Choice: stash the *canonical* `team_abbr` on `Selection` at parse
time.**

Add an optional field:

    class Selection(NamedTuple):
        ...
        team_abbr: str | None = None

The spread-flavor parser resolves the PX team prefix from
`display_name` (e.g. `"BRE"`, or `"Atlanta Hawks"` if that format
ever arrives) against the event's competitor map and stores the
**canonical** abbreviation. A junk prefix raises at parse time
with a clear "team X not in event Y" error.

`resolve_side_label` then becomes a single discriminator per branch
— if `team_abbr` is set, the side has already been resolved:

    if sel.team_abbr is not None:
        return sel.team_abbr                  # parse-time-resolved
    if outcome_id in _TEAM_OUTCOME_IDS:
        return comp_map[competitor_id]        # existing path
    return _FIXED_SIDE_LABELS[outcome_id]     # yes/no/over/under

Rationale: `team_abbr` has one consistent meaning everywhere
(canonical, never raw); `resolve_side_label` stays narrow with no
new dependency on `team_aliases`; validation fires at the natural
origin (parse time). The cost is threading the per-event
abbrev→canonical map through `extract_market_lines` /
`classify_and_enrich`.

### 7. Downgrade behavior — Choice (a): keep distinct

When PX sends both `type=spread` (multi-line) and `type=sup_moneyline`
at the same handicap, they have **different `line_id`s** — they are
separate PX orderbooks. We treat them as distinct quotable instruments,
mirroring the player-prop precedent (`px.py:721` comment).

- If only `sup_moneyline` exists for that line: `point_spread_yn`
  downgrades to `point_spread` (matches Optic naturally).
- If both exist: `point_spread_yn` stays distinct; only the
  `point_spread` rows participate in Optic merge. Both quotes
  remain visible to downstream consumers.

The existing downgrade block (`px.py:718-737`) already implements
choice (a). One small generalization needed: the side rewrite

    _YN_TO_OU = {"yes": "over", "no": "under"}
    ...
    r.side = _YN_TO_OU[r.side]

assumes the existing side is `yes`/`no`. For `POINT_SPREAD_YN` the
side is already a team abbreviation. Change to:

    if r.side in _YN_TO_OU:
        r.side = _YN_TO_OU[r.side]

(market_type is rewritten unconditionally; side rewrite is gated.)

### 8. Validation (new function)

`_validate_sup_moneyline_spread_sels`:
- 2 selections, `outcome_ids == {1, 2}`, `sel.line == 0` for both
- After parse: signed handicaps sum to 0
- Both team codes resolve via `team_aliases` to one of the event's
  two competitors (membership check)

The team-membership check needs the event's resolved team set.
`extract_market_lines` doesn't currently take event context; this
check can either be added to `classify_and_enrich` (which has
`team_id_map`, but that's market-id-keyed — would need a
competitor-set built alongside) or to the pipeline phase that
calls it. Cheapest: build `event_team_set: dict[int, set[str]]`
in the pipeline and pass it to `classify_and_enrich`.

### 9. Optic side

No change. Optic `asian_handicap` already produces `POINT_SPREAD`
rows with team sides and signed lines (`mappers/leagues/epl.py:70`).
After §7 downgrade, PX `point_spread_yn` rows become `point_spread`
and merge with Optic by `(market_type, side, line)`.

## Files to modify

- `mappers/market_types.py` — add `POINT_SPREAD_YN`
- `mappers/exchanges/px.py`:
  - `Selection` — add `team_abbr: str | None = None`
  - `_parse_sup_moneyline_line` — split into dispatcher +
    `_parse_sup_moneyline_ou` + `_parse_sup_moneyline_spread`
  - `_validate_sup_moneyline_spread_sels` — new
  - `extract_market_lines` — sup_moneyline branch dispatches; spread
    flavor returns selections with `spread_line` and `team_abbr`
    populated
  - `_SUP_MONEYLINE_REMAP` — add `POINT_SPREAD → POINT_SPREAD_YN`
  - `classify_market` — move type cross-check ahead of remap
  - `resolve_side_label` — use `team_abbr` for `{1,2}` outcomes when
    present
  - `build_rows` — gate side rewrite on `r.side in _YN_TO_OU`
- `mappers/leagues/epl.py` — no change required;
  `"Spread (Regular Time)" → POINT_SPREAD` stays, remap takes over
- `mappers/pipeline.py` — pass per-event team-abbrev set into
  `classify_and_enrich` for the spread-flavor membership check

## Verification

1. `mise check` (pyright)
2. `mise test` (pytest, including fixture integration)
3. End-to-end: `mise map data/2026-04-30/14_55` runs to completion
   for EPL.
4. Manual check on one event (e.g. ARS/FUL ±1.5): row appears under
   `point_spread` (downgraded from `_YN` since Optic carries the
   same line).
5. Refactor-stability checksum on existing leagues
   (NBA / NCAAB / MLB) — none of them currently send
   `POINT_SPREAD` via `sup_moneyline`, so output should be
   byte-identical:

       git stash
       for d in data/nba/2026-02-*; do
           python -m mappers.run nba "$d" --json
       done | md5
       git stash pop
       for d in data/nba/2026-02-*; do
           python -m mappers.run nba "$d" --json
       done | md5

## Resolved design choices

1. **Team-code regex** — permissive: `^(.+?)\s+([+-][\d.]+)$`. The
   alias-table membership check in §8 is the real validator;
   permissiveness lets the same parser handle EPL's 3-char codes
   and any other league's `display_name` shape (e.g. NBA's
   full-team-name format) without per-league configuration.

2. **`team_abbr` field on `Selection`, resolved at parse time** —
   accepted. Stores the **canonical** abbreviation (not raw prefix),
   so `resolve_side_label` consumes it directly with one
   discriminator per branch and no new dependency on `team_aliases`.
   Per-event abbrev→canonical map is threaded through
   `extract_market_lines` / `classify_and_enrich`. Considered and
   rejected: storing raw prefix and dispatching on
   `outcome_id ∈ {1,2} ∧ team_abbr is not None` (chunky two-signal
   conjunction in a hitherto simple function); resolving to
   `competitor_id` instead (would break the "outcome_id is the
   routing key" invariant).

## Reference

- Prior `_YN` additions: `df65df8` PLAYER_ASSISTS_YN,
  `3431b95` PLAYER_REBOUNDS_YN, `2266dd2` PLAYER_STEALS_YN,
  `f8c66a7` initial PX sup_moneyline support
- EPL pipeline addition: `2aa7c2e Add EPL to pipeline`
- Existing downgrade logic & coexistence comment:
  `mappers/exchanges/px.py:718-737`
