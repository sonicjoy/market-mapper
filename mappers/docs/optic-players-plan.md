# Player Market Matching — Optic-First Approach

Supersedes `players-plan.md` steps 1–4.  The key simplification:
we don't need an NBA roster download.  All three exchanges provide
player names in plain text, so we match by normalized name within
a game.

**Previous plan (`players-plan.md`)** resolved players through a
downloaded NBA roster (team + jersey for Kalshi, name for PX/Optic).
That plan assumed we needed the roster to decode Kalshi's ticker
encoding (e.g. `ORLPBANCHERO5`).  We don't — the Kalshi `title`
field has the full name: `"Paolo Banchero: 30+ points"`.


## Philosophy

Optic defines the player universe.  We only emit player rows for
markets where Optic has a priced odd.  PX and Kalshi rows merge
onto those Optic rows.  At the line level, exchanges may offer
alternate lines that don't merge — those become standalone rows,
same as game-level markets today.  But at the entity level,
every PX/Kalshi player must exist in Optic for that game +
market type (see Resolved question 3).  No NBA roster download.


## Name normalization

A shared `normalize_player_name(name: str) -> str` function that
all three sources use to produce the entity for `row_key`:

- lowercase
- strip diacritics (unicodedata NFD + drop combining chars)
- strip periods and extra whitespace
- strip suffixes: Jr., Sr., II, III, IV
- replace spaces with underscores
- e.g. `"Nikola Jokić"` → `"nikola_jokic"`
- e.g. `"Wendell Carter Jr."` → `"wendell_carter"`

Diacritic stripping is essential: PX and Kalshi preserve
diacritics (`"Jokić"`), Optic sometimes strips them in
`selection` (`"Jokic"`) and sometimes doesn't (`"Traoré"`).
Optic's `normalized_selection` field cannot be used as-is
because it drops diacritics without transliterating (e.g.
`"Traoré"` → `"traor_"` instead of `"traore"`).

This is the merge key entity.  The display name stays as-is
for human readability (grabbed from Optic's `selection`).


## Player name extraction per source

**Optic** — `odd.selection` (e.g. `"Paolo Banchero"`,
`"Nikola Jokic"`, `"Nolan Traoré"`) → `normalize_player_name`

**PX** — `extract_player(market.name, mt)` already exists (px.py:348),
returns names like `"Paolo Banchero"`

**Kalshi** — parse from `market.title`.  Pattern is always
`"{Name}: {description}"`, so split on the first colon:
```
"Paolo Banchero: 30+ points"       →  "Paolo Banchero"
"Wendell Carter Jr.: Double Double" →  "Wendell Carter Jr."
```


## Market types to match

Start with the 12 player types that map to existing `MarketType`
enum values.  The 8 Kalshi types are the three-way overlap; the
4 combo types merge PX ↔ Optic only (Kalshi doesn't offer them).

| Kalshi prefix | MarketType             | Line? | Kalshi? |
|---------------|------------------------|-------|---------|
| PTS           | player_points          | yes   | yes     |
| AST           | player_assists         | yes   | yes     |
| REB           | player_rebounds        | yes   | yes     |
| 3PT           | player_threes          | yes   | yes     |
| BLK           | player_blocks          | yes   | yes     |
| STL           | player_steals          | yes   | yes     |
| 2D            | player_double_double   | no    | yes     |
| 3D            | player_triple_double   | no    | yes     |
| —             | player_pts_ast         | yes   | no      |
| —             | player_pts_reb         | yes   | no      |
| —             | player_pts_reb_ast     | yes   | no      |
| —             | player_reb_ast         | yes   | no      |

Optic has ~80 market_id values including ~50 player types
(combos, h2h, quarter-level, first-basket, "most" markets).
Those are silently skipped for now — add later as a mechanical
expansion.

PX has all 14 player types already classified in `classify_market`
and extracted by `extract_player`.  The 2 PX types not in the 12
above (player_steals_blocks, player_turnovers) stay in
`_IGNORED_TYPES` until Kalshi or Optic data warrants adding them.


## Kalshi line conversion for player props

Current game-level rule: `line = N + 0.5` (Kalshi integer →
half-point).

Player props are the opposite: `"25+ points"` means scores 25
or more, which is over **24.5**.  So `line = N - 0.5`.

This is already documented in `matching.md:164` and
`players-plan.md:51`.

Double-double and triple-double have no line — they're yes/no
markets.


## Status: DONE

All module changes below are implemented.  Code review findings
addressed: hardened `_extract_player_name` error message, made
`entity=None` explicit in game-scoped Kalshi branches, removed
incorrect player skip in `verify_source_ids`, added per-game
diagnostic comment.

Player alias table added: `data/nba/tables/player_aliases.csv`
(exchange-specific, CSV format).  Loaded in `shared.py`, applied
after `normalize_player_name` in PX and Kalshi `build_rows`.
Missing file returns empty dict (no aliases = no remapping).


## Module changes

### `mappers/shared.py`

Add `normalize_player_name()`, `levenshtein()`,
`load_player_aliases()`.

### `mappers/kalshi.py`

Current state: recognizes all 8 player ticker types in
`_extract_ticker_type` (kalshi.py:90) but skips them — they're
not in `_TABLE_TYPES`.

Changes:
- Add the 8 player types to `_TABLE_TYPES` (or a separate
  `_PLAYER_TABLE_TYPES`)
- Add `_extract_player_name(title: str) -> str` — split on
  first colon, strip
- In `build_rows`, handle player-scoped types: extract name
  from title, use `N - 0.5` for line conversion, entity =
  normalized name
- Sides for stat markets: `kalshi_side="yes"` = over,
  `kalshi_side="no"` = under
- Sides for 2D/3D: `kalshi_side="yes"` = yes,
  `kalshi_side="no"` = no

### `mappers/optic.py`

Current state: `_TABLE_TYPES` (optic.py:66–71) has only the 4
game/team types.  `Odd` model (optic.py:25–36) already has
`player_id` field.

Changes:
- Expand `_TABLE_TYPES` to include player market types
- In `build_rows`, handle player odds: entity =
  `normalize_player_name(odd.selection)`, line = `odd.points`,
  side = `odd.selection_line` (over/under) or yes/no for DD/TD

### `mappers/px.py`

Current state: `TABLE_TYPES` has only the 4 game/team types.
Player types are classified by `classify_market` but skipped in
`build_rows`.  The 14 player types are currently in
`_IGNORED_TYPES` (added in the type-level guards commit).

Changes:
- Move the 12 target player types from `_IGNORED_TYPES` to
  `TABLE_TYPES`
- Add player scope branch to `build_rows`: entity =
  `normalize_player_name(extract_player(market.name, mt))`
- Player validation in `validate_markets` already works

### `mappers/nba.py`

No structural changes.  The merge loop already handles
merge-or-append by `row_key`.

Changes:
- Add player types to `_MARKET_TYPE_ORDER` for sort ordering
- Add `"yes"` → (0,0) and `"no"` → (0,1) cases to
  `_row_sort_key` for DD/TD side sorting
- Add entity-level subset check after row building: for each
  game + player market type, verify every PX/Kalshi entity
  exists in Optic's entity set for that game + type.  Raise
  if not — indicates a name normalization divergence.


## Merge key

Same as today: `(date, home, away, market_type, entity,
normalize_line(line), side)` — where `entity` is now the
normalized player name for player-scoped markets.


## Edge cases to handle

**Name mismatches across sources** — "Nic Claxton" vs "Nicolas
Claxton", "PJ Washington" vs "P.J. Washington".  The normalize
function handles punctuation.  Nickname variants are handled by
an exchange-specific alias table: `data/nba/tables/player_aliases.csv`.
The nba.py diagnostic (Levenshtein on orphan names) identifies
candidates; confirmed aliases are added to the CSV.

**Same last name, same game** — e.g. two brothers.  The full
normalized name (first + last) is the entity, not just last name,
so this only collides if two players have identical full names in
the same game.  Essentially impossible in the NBA.

**Optic markets with no PX/Kalshi counterpart** — these just
become Optic-only rows, same as today when Kalshi has a market PX
doesn't.  No special handling.


## Resolved questions

1. **Entity value** — All three sources run through the same
   `normalize_player_name()` function in `shared.py`, applied
   to Optic's `selection`, PX's extracted name, and Kalshi's
   extracted name.  Using a single code path avoids divergence.

   We cannot use Optic's `normalized_selection` as-is because
   it handles diacritics inconsistently: `"Nikola Jokic"` →
   `"nikola_jokic"` (correct, diacritic already stripped in
   `selection`), but `"Nolan Traoré"` → `"nolan_traor_"`
   (broken — the `é` was dropped, not transliterated).

   The normalize function: lowercase, strip diacritics
   (unicodedata NFD + drop combining chars), strip periods,
   strip suffixes (Jr./Sr./II/III/IV), collapse whitespace,
   replace spaces with underscores.  E.g.:
   - `"Nikola Jokić"` → `"nikola_jokic"`
   - `"Nolan Traoré"` → `"nolan_traore"`
   - `"Wendell Carter Jr."` → `"wendell_carter"`

2. **Which Optic player types to include** — Start with the 12
   that map to existing `MarketType` enum values (the 8 Kalshi
   types plus 4 combo types: pts+ast, pts+reb, pts+reb+ast,
   reb+ast).  The remaining ~40 Optic player `market_id` values
   (h2h, combo/each/either parlays, quarter-level, first-basket,
   "most" markets) would need new enum values and have no
   PX/Kalshi counterparts — add them later as a mechanical
   expansion.  Importantly, this gap is safe: the "Optic is
   canon" validation (see below) ensures that if PX or Kalshi
   ever introduces a type we don't handle, we get a clear error.

3. **Verification** — Optic's `source_ids` are sparse for player
   odds (~1.7% have PX refs), so `verify_source_ids` won't catch
   much for players.  Instead, enforce the Optic-is-canon
   principle at the entity level: after building all rows, for
   each game + player market type, every PX/Kalshi player entity
   must also appear as an Optic entity (at some line).  If PX
   has `nikola_jokic` for `player_points` in a game but Optic
   has no `player_points` rows for `nikola_jokic`, raise — that
   means our name normalization diverged.  This catches name
   normalization bugs cleanly without fuzzy matching: it's a
   simple set-subset check.  ~10 lines in `nba.py`.


## Player matching truth table

For a given Optic player odd (e.g. `player_made_threes` for
`andrew_nembhard` at 3.5 over), what can happen for each of
PX and Kalshi:

| # | Exchange has market? | Our matching             | Outcome                      | Caught by         |
|---|----------------------|--------------------------|------------------------------|-------------------|
| 1 | Yes                  | Name + type correct, lines match   | Merge — correct    | —                 |
| 2 | Yes                  | Name normalization diverges        | Two orphan rows    | Entity subset check |
| 3 | Yes                  | Type misclassified                 | Two orphan rows    | **Not caught**    |
| 4 | Yes                  | Name + type correct, lines differ  | Separate rows      | Correct (alt lines) |
| 5 | No                   | —                                  | Optic-only row     | Correct           |

Scenario 2 is the main risk — a diacritic or suffix mismatch
producing two orphan rows that look plausible.  The entity
subset check (Resolved question 3) catches this: a PX/Kalshi
entity with no Optic counterpart for that game + market type
raises immediately.

Scenario 3 (type misclassification) can't easily be caught at
runtime.  If `classify_market` maps a "Made Threes" market to
`player_points`, the entity (`andrew_nembhard`) legitimately
exists in Optic under `player_points` too — so the entity
check passes.  In practice this is low risk: `classify_market`
is suffix-based and deterministic, so a misclassification would
affect all markets with that suffix, not one player, and would
show up immediately in development.


## Optic-is-canon validation

**Principle:** Optic defines the canonical market universe.

- **Optic** silently skips market_id values not in `_TABLE_TYPES`.
  This is fine — Optic is allowed to offer markets we don't
  handle yet (and it has ~80+ market_id values, a moveable feast).
- **PX and Kalshi** must not silently skip.  If a classified
  market type is not in `TABLE_TYPES`, it must be in an explicit
  `_IGNORED_TYPES` set or raise.  This documents "we know about
  these, we'll add them later" and ensures genuinely new types
  produce a clear error instead of vanishing silently.

Row-level enforcement (requiring every PX/Kalshi row to merge
onto an Optic row) is too strict — exchanges naturally offer
different alternate lines for the same market type, so line-level
coverage differs.  Type-level enforcement is the right
granularity.

**Implementation (already done, see commit):**

- `mappers/px.py`: `_IGNORED_TYPES` set + raise in `build_rows`
- `mappers/kalshi.py`: `_IGNORED_TICKER_TYPES` set + raise in
  `parse_event_ticker` *(superseded 2026-09: tip overlay owns ignore;
  unknown types return `None`)*


## Key file references

| File | What's there | Line refs |
|------|-------------|-----------|
| `mappers/nba.py` | Orchestrator, merge loop, sort key | 80–114, 282–353 |
| `mappers/px.py` | `extract_player`, `_PLAYER_SUFFIX`, player classify/validate | 252–266, 270–275, 348–363, 546–561 |
| `mappers/kalshi.py` | Ticker type recognition, player encoding comment | 12–18, 90 |
| `mappers/optic.py` | `Odd` model with `player_id`, `_TABLE_TYPES` | 25–36, 66–71 |
| `mappers/shared.py` | `CanonicalRow`, `normalize_line`, `row_key` used in nba.py | — |
| `mappers/market_types.py` | All 14 `PLAYER_*` MarketType values | — |
| `mappers/docs/matching.md` | Kalshi line convention, player resolution TODO | 159–165, 198–213 |
| `mappers/docs/players-plan.md` | Previous roster-based plan (superseded) | all |
| `market_mapping/nba/players.py` | Old roster code (no longer needed for matching, but `normalize_name` logic may be useful) | — |

## Data references

Kalshi player ticker examples (from `data/nba/2026-02-26/`):
```
ticker: KXNBA2D-26FEB26HOUORL-ORLPBANCHERO5
title:  "Paolo Banchero: Double Double"

ticker: KXNBAPTS-26FEB26HOUORL-ORLWCARTER34-25
title:  "Wendell Carter Jr.: 25+ points"
```

Optic player odd fields (from `data/nba/2026-02-26/`):
```
selection: "Paolo Banchero"
player_id: "F44DA1008FAF60EA"
market_id: "player_points"
selection_line: "over"
points: 24.5
team_id: null
```
