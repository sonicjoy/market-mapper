# Plan: Add Player Market Matching (roster-based)

**Superseded by `optic-players-plan.md`** — the Optic-first approach
(normalize names, no roster download) was implemented instead.
Kept for future reference; the roster-based resolution described
here may be useful if we ever need to decode Kalshi's team+jersey
ticker encodings directly.

## How to use this plan

This is a high-level roadmap, not an execute-now checklist.  Each step
below should be planned in detail in its own conversation before
writing code.

## Prerequisite: extract exchange modules

All three done.  Each exchange gets its own module with standardized
names (`Market`/`Game`, `parse_market`/`parse_game`, `build_rows`,
`TABLE_TYPES`).  `nba.py` stays as the orchestrator (~380 lines).

**Completed:**
- `mappers/kalshi.py` — all Kalshi parsing, ticker extraction, and row
  building.  `CanonicalRow` and `opponent()` moved to `shared.py` to
  avoid circular imports.
- `mappers/px.py` — all PX parsing, classification, validation, side-label
  resolution, and row building.  Standardized names: `Event`, `Market`,
  `parse_event`, `build_rows`, `TABLE_TYPES`.
- `mappers/optic.py` — models, row building, and source_ids verification.
  Standardized names: `Game`, `Odd`, `parse_game`, `build_rows`,
  `verify_source_ids`.


## Context

The NBA mapper (`mappers/nba.py`) matches markets across PX, Kalshi, and
Optic for 4 game/team-scoped types: moneyline, point_spread, game_total,
team_total.  All the infrastructure for player markets is partially in
place — PX classification, MarketType enum, Kalshi ticker recognition —
but no player rows flow into the canonical pipeline.

This adds matching for 14 player-scoped market types by:
- Bringing in the roster module from the old implementation
- Resolving PX names and Kalshi encodings to canonical player identities
- Extending all three exchange pipelines (PX, Kalshi, Optic)


## Key design decisions

**Entity = player full_name from roster.**  All three exchanges resolve
through the NBA roster, so the roster's `full_name` is the canonical
entity.  Human-readable in output, deterministic for merge keys.

**DD/TD canonical model:** `line=None, side="yes"/"no"`.  PX uses
outcome_ids {1,2}→yes/no.  Kalshi 2D/3D has no line.  Optic uses
over/under 0.5, mapped to yes/no so merge keys align.

**Kalshi player line = N - 0.5** (not N + 0.5 like game-level).
"25+ points" = over 24.5.  Verified against real ticker titles.

**Keep parsing pure:** `parse_kalshi_event_ticker` stores raw
`player_encoding` string; resolution to a name happens in
`build_kalshi_rows`.  No roster dependency in the parser.


## Steps

### 1. Add player roster module

Create `mappers/players.py` adapted from `market_mapping/nba/players.py`.

**What to copy verbatim:** `Player`, `PlayerLookup`, `GameRoster`,
`normalize_name`, `parse_kalshi_player_encoding`, `_GENERATIONAL`,
`_KALSHI_PLAYER_RE`.

**What to change:** Replace `from .teams import REFERENCE_DIR` with
direct path: `PLAYERS_DIR = Path(__file__).resolve().parent.parent / "reference" / "nba" / "players"`

**Don't copy:** `strip_stat_suffix` and `STAT_SUFFIXES` — this logic
already exists in `px.py` as `extract_player` + `_PLAYER_SUFFIX`.

**Tests:** Create `tests/mappers/test_players.py` adapted from
`tests/nba/test_players.py` (change imports, drop `strip_stat_suffix`
tests).  Copy fixture `tests/nba/fixtures/players.json` →
`tests/mappers/fixtures/players.json`.

**Files:**
- Create `mappers/players.py`
- Create `tests/mappers/test_players.py`
- Create `tests/mappers/fixtures/players.json`


### 2. Extend PX pipeline for player markets

Open the gate and wire in roster resolution.

**`px.TABLE_TYPES`**: Add all 14 `MarketType.PLAYER_*` values.

**`_MARKET_TYPE_ORDER`** in `nba.py`: Add sort positions 4–17 for player
types in sportsbook order: points, assists, rebounds, threes, blocks,
steals, turnovers, steals_blocks, pts_ast, pts_reb, pts_reb_ast,
reb_ast, double_double, triple_double.

**`_row_sort_key`** in `nba.py`: Add `"yes"` → (0,0) and `"no"` → (0,1)
cases after the `"under"` case, for DD/TD side sorting.

**`px.build_rows`**: Extend entity logic:
```python
if mt.scope == Scope.TEAM:
    entity = market.wsd.team_abbrev
elif mt.scope == Scope.PLAYER:
    entity = market.wsd.player
else:
    entity = None
```
(Side/line logic already works — totals use outcome_ids {12,13} →
over/under; DD/TD use {1,2} → yes/no with line=None.)

**`main()`**: After loading schedule, load roster:
```python
from mappers.players import PlayerLookup, PLAYERS_DIR
roster_files = sorted(PLAYERS_DIR.glob("*.json"))
player_lookup = PlayerLookup(roster_files[-1]) if roster_files else None
```
In the PX row building loop, resolve player names through roster before
building rows:
```python
if player_lookup is not None:
    game_roster = player_lookup.game_roster(home, away)
    for market in e.px_event.markets:
        if market.wsd.market_type.scope == Scope.PLAYER:
            player = game_roster.require(market.wsd.player, ...)
            market.wsd.player = player.full_name
```


### 3. Extend Kalshi pipeline for player markets

All changes in `mappers/kalshi.py` (standardized names).

**`TABLE_TYPES`**: Add 8 entries mapping ticker types to MarketTypes
(PTS→PLAYER_POINTS, AST→PLAYER_ASSISTS, REB→PLAYER_REBOUNDS,
3PT→PLAYER_THREES, BLK→PLAYER_BLOCKS, STL→PLAYER_STEALS,
2D→PLAYER_DOUBLE_DOUBLE, 3D→PLAYER_TRIPLE_DOUBLE).

**`ParsedTicker`**: Add `player_encoding: str | None = None`.

**`parse_event_ticker`**: Add two new branches:
- Stat types: split suffix on last `-` → player_encoding + integer N,
  line = N - 0.5.
- Binary types: entire suffix is player_encoding, line = None.

**`build_rows`**: Add `player_lookup` parameter.  New branch for
`mt.scope == Scope.PLAYER`:
- Parse encoding via `parse_kalshi_player_encoding`
- Resolve via `player_lookup.require_by_team_jersey(team, jersey, ...)`
- Stat totals: 2 rows (over/under yes/no)
- DD/TD: 2 rows (yes/no yes/no)

**`main()`** in `nba.py`: Pass `player_lookup` to `kalshi.build_rows`.


### 4. Extend Optic pipeline for player markets

**`_TABLE_TYPES`** in `optic.py`: Add 14 entries (verified from data):
```
"player_points"                      → PLAYER_POINTS
"player_assists"                     → PLAYER_ASSISTS
"player_rebounds"                    → PLAYER_REBOUNDS
"player_made_threes"                 → PLAYER_THREES
"player_blocks"                      → PLAYER_BLOCKS
"player_steals"                      → PLAYER_STEALS
"player_turnovers"                   → PLAYER_TURNOVERS
"player_steals_+_blocks"             → PLAYER_STEALS_BLOCKS
"player_points_+_assists"            → PLAYER_PTS_AST
"player_points_+_rebounds"           → PLAYER_PTS_REB
"player_points_+_rebounds_+_assists" → PLAYER_PTS_REB_AST
"player_rebounds_+_assists"          → PLAYER_REB_AST
"player_double_double"               → PLAYER_DOUBLE_DOUBLE
"player_triple_double"               → PLAYER_TRIPLE_DOUBLE
```
(`player_turnovers` not yet observed in Optic data but included for
completeness.)

**`optic.build_rows`**: Add `game_roster: GameRoster | None` parameter.
New branch for `mt.scope == Scope.PLAYER`:
- Resolve player name from `odd.selection` via `game_roster.require()`
- Entity = player.full_name
- Stat totals: side = odd.selection_line, line = abs(odd.points)
- DD/TD: side = "yes" if selection_line=="over" else "no", line = None

**`main()`**: Build `GameRoster` per game and pass to `optic.build_rows`.


## Verification

### Golden file diffing (for refactors)

Pure refactors (PX and Optic extraction) must produce identical output.
Baseline "before" files already exist in `/tmp/mapper-diff/before/`
(generated before the Kalshi extraction).  After each refactor,
regenerate "after" and diff:

```bash
for d in 2026-02-19 2026-02-21 2026-02-25 2026-02-26; do
  python -m mappers.nba "data/nba/$d" --json 2>/dev/null \
    > "/tmp/mapper-diff/after/${d}.json"
  python -m mappers.nba "data/nba/$d" --table 2>/dev/null \
    > "/tmp/mapper-diff/after/${d}.table"
done

diff -r /tmp/mapper-diff/before /tmp/mapper-diff/after
```

### After player market steps

```
python -m mappers.nba data/nba/2026-02-26 --json | wc -l
python -m mappers.nba data/nba/2026-02-26 --table | head -40
pytest tests/mappers/
```
- After step 1: output identical to before (roster module unused yet)
- After step 2: PX player rows appear; row count jumps significantly
- After step 3: Kalshi player rows merge onto PX rows (matched rows
  gain kalshi_ticker); Kalshi-only player rows also appear
- After step 4: Optic player rows merge; optic_id populated on
  matched rows; `verify_optic_source_ids` validates cross-references
