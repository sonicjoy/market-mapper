# Multi-Sport Roadmap

Extending the NBA-only pipeline to cover NCAAB (and eventually
other sports).  This document captures the architectural audit and
open questions — it is a roadmap, not a final design.


## Background

The pipeline maps markets from three exchanges (ProphetX, Kalshi,
Optic) onto a canonical schedule.  Optic fixtures define the game
universe; PX and Kalshi markets are matched onto it by
`MatchKey(date, home, away)`.  Rows from all three sources merge
by a 7-tuple key `(date, home, away, market_type, entity, line,
side)`.

Today the code is NBA-only.  NCAAB data already exists under
`data/ncaab/` in the same four-file format (optic_fixtures_odds,
prophetx_events, prophetx_markets, kalshi_markets).  The goal is a
single `run.py` entry point that dispatches on sport/tournament,
rather than separate scripts per sport.


## NCAAB data characteristics

Sampled from `data/ncaab/2026-02-21/` and `data/ncaab/2026-02-25/`.

### Kalshi

Prefix is `KXNCAAMB` (vs `KXNBA` for NBA).  Six game-level ticker
types observed:

    GAME, SPREAD, TOTAL, 1HSPREAD, 1HTOTAL, 1HWINNER

No TEAMTOTAL, no 2HWINNER, and **no player prop markets at all**.

Two non-game ticker types observed (tip `mapping_market_rules`
`ignore`, not Python factory catalogs): `NAISMITH` (season award)
and `UNDEFEATED` (novelty).

Team abbreviations in tickers are 2–7 characters (vs NBA's fixed
3), so the NBA regex `([A-Z]{3})([A-Z]{3})` won't work.  The
ticker suffix structure (e.g. `{TEAM}{N}` for spreads) is
otherwise identical.

### ProphetX

- `sport_name` = `"Basketball"` (same as NBA)
- `tournament_name` = `"College Basketball"` (NBA uses `"NBA"`)
- `tournament_id` = `648` for all NCAAB events

Market name strings are identical to NBA: `"Moneyline"`,
`"Spread"`, `"Total Points"`, `"First Half Moneyline"`,
`"{Player} Points"`, `"{ABBR}: Team Total Points"`, etc.
The classification tables (`_EXACT`, `_SUFFIX`) work unchanged.

Player props are present (points, rebounds, assists, threes,
combos).  Team totals are present.

Team abbreviations are longer and more varied (2–7 chars, ~350+
teams).  PX alias mappings (e.g. `GS→GSW`) will differ from NBA;
the initial set is unknown.

### Optic

- `league.id` = `"ncaab"`, `league.name` = `"NCAAB"`
- Same `market_id` strings as NBA (`player_points`, `moneyline`,
  `point_spread`, etc.)
- Same odds structure, same signed half-point conventions
- Player markets are present

No code changes needed in `optic.py` — it has no sport-specific
constants and parses whatever file it's given.


## Audit: what is NBA-specific vs generic

### shared.py

**NBA-specific (5 items):**
- `CANONICAL_ABBRS` — frozenset of 30 NBA teams
- `PX_ALIASES` — 5 PX→canonical mappings (`GS→GSW`, etc.)
- `check_abbr()` — validates against `CANONICAL_ABBRS`
- `normalize_px_abbr()` — applies `PX_ALIASES` then `check_abbr`
- Module docstring

**Already generic:** `MatchKey`, `CanonicalRow`, `TIE_SIDE`, `ET`,
`normalize_line`, `normalize_player_name`, `levenshtein`,
`load_player_aliases`, `lines`, `to_et_str`, `to_date_str`,
`opponent`

### kalshi.py

**NBA-specific:**
- `_GAME_TICKER_RE` — hardcodes `KXNBA` prefix and
  `([A-Z]{3})([A-Z]{3})` for 3-char team abbrevs
- `_extract_ticker_type()` — hardcodes `"KXNBA"`, offset 5
- `try_parse_game_ticker()` — uses the regex, calls `check_abbr`
- `_TICKER_TYPES` — 16 NBA types including 8 player types
- `TABLE_TYPES` — maps those 16 to `MarketType`
- `_PLAYER_STAT_TYPES` — 6 player ticker types (NCAAB has none)
- `_IGNORED_TICKER_TYPES` — historical; factories now ship empty
  and tip overlay owns map/ignore (`NAISMITH`, `UNDEFEATED` on NCAAB)

**Already generic:** `Market` model, `parse_market`,
`ParsedTicker`, `_require_team`, `_parse_team_line`, `_parse_int`,
`_extract_player_name`, `parse_event_ticker` (dispatch logic),
`build_rows` (row construction)

### px.py

**NBA-specific (3 items):**
- `parse_event()` — checks `tournament_name != "NBA"`
- `_sides()` — calls `normalize_px_abbr()` (NBA alias+validation)
- `build_comp_map()` — calls `normalize_px_abbr()`

**Already generic:** classification tables (`_EXACT`, `_SUFFIX`),
`_EXPECTED_TYPE`, `_PLAYER_SUFFIX`, `classify_market`,
`extract_team`, `extract_player`, `extract_market_lines`, all
validation, `resolve_side_label`, `build_rows`, `group_markets`,
`validate_markets`, `TABLE_TYPES`, `_IGNORED_TYPES`

### optic.py

**NBA-specific: essentially nothing.**  No sport filtering, no
hardcoded abbreviations.  `_TABLE_TYPES` maps Optic `market_id`
strings to `MarketType` — NCAAB uses the same strings.
`load_fixtures()` parses whatever file you give it.

### market_types.py

**NBA-specific: just the docstring.**  The 23 `MarketType` values
form a shared universe.  NCAAB uses a subset.  Per-sport coverage
is expressed through the `TABLE_TYPES`/`_IGNORED_TYPES` sets in
the exchange modules, not by having separate enums.

### nba.py (the pipeline)

**Generic pipeline logic (reusable as-is):**
- `ScheduleEntry` class
- `match_event()`
- `_row_sort_key()`
- `canonical_row_to_json()`
- The entire merge-by-row-key loop (PX → Kalshi → Optic)
- Player name normalization diagnostic
- `verify_source_ids()` call
- Output handling (JSON / table)

**NBA-specific:**
- `_OUTPUT_ORDER` — the 23 types in sportsbook display order;
  NCAAB would have a different/smaller tuple
- PX event parsing calls `normalize_px_abbr` indirectly
- Kalshi `try_parse_game_ticker` — NBA prefix/regex


## The sport-specific surface (summary)

Five things differ per sport:

| # | What                    | NBA                          | NCAAB                             |
|---|-------------------------|------------------------------|-----------------------------------|
| 1 | Team abbrev validation  | `check_abbr` vs 30-team set  | None (deliberate — see below)     |
| 2 | PX abbrev normalization | `PX_ALIASES` (5 mappings)    | TBD (probably different, or none) |
| 3 | PX tournament filter    | `"NBA"`                      | `"College Basketball"`            |
| 4 | Kalshi prefix + regex   | `KXNBA`, 3-char teams        | `KXNCAAMB`, 2–7-char teams        |
| 5 | Kalshi ticker type sets | 16 types (8 game + 8 player) | ~6 types (game-level only)        |

Plus a per-sport `_OUTPUT_ORDER` for display sorting.  Kalshi
map/ignore beyond `table_types` is tip `mapping_market_rules` (Python
factories ship empty `ignored_ticker_types`).


## Design decisions

### Team abbreviation validation for NCAAB

Deliberate choice: **drop team validation for NCAAB.**  NBA has 30
known abbreviations validated via `check_abbr`; NCAAB has ~350+
teams with ad-hoc abbreviation schemes and we cannot reasonably
maintain a static set.  Mismatches will surface at the merge step
— if a PX or Kalshi market doesn't merge onto an Optic fixture,
we'll see it in the unmatched counts.

### Single entry point

There will be one script to run (`run.py`), not one per sport.
It dispatches on a maintained set of supported sports/tournaments,
similar to how we maintain explicit `TABLE_TYPES` for market types.


## Open question: sport-specific config shape

How should the sport-specific configuration be structured?  One
candidate: a module per sport (e.g. `mappers/sports/nba.py`,
`mappers/sports/ncaab.py`) that each export the five items above,
with the pipeline in a shared `run.py` that imports the right one
based on a CLI argument.  But there may be cleaner alternatives —
a dataclass, a dict, or some other mechanism.  This needs to be
settled before implementation begins.
