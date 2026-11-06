# Matching Engine

How we match PX, Kalshi, and Optic markets to canonical betting
sides within a game.

The code lives in `mappers/nba.py`, which:
- anchors all three exchanges to the NBA schedule (game-level matching)
- classifies every PX market into a `MarketType`
- extracts team/player/line data into `wsd`
- parses Kalshi tickers and converts integer lines to half-points
- builds flat `CanonicalRow`s per exchange, then merges by key
- verifies Optic `source_ids` against our PX/Kalshi matching


## Canonical market domain

Four levels identify an outcome you can bet on:

```
Game → Market → Line → Side
```

**Game** — a scheduled NBA game.
`(date, home, away)` e.g. `2026-02-27 HOU @ ORL`

**Market** — a question about that game.
`MarketType + entity` where entity depends on scope:
- GAME-scoped: nothing extra — `(moneyline,)`
- TEAM-scoped: which team — `(team_total, HOU)`
- PLAYER-scoped: which player — `(player_points, player_id)`

One market per unique question per game.

**Line** — a numeric threshold (optional).
The value at which the bet is struck — can be whole (107) or
half-point (107.5).  Moneyline and double/triple-double have
no line.  Spread, total, and player stat markets have one or
more alternate lines.  Kalshi only offers half-point lines;
PX offers both.  Cross-exchange matches occur only at
half-point lines.

**Side** — one position on a line.  Always exactly two per line:
- team-identified markets: one per team (home / away)
- over/under markets: over / under
- yes/no markets: yes / no

A Side is the atomic unit — "an outcome you can bet on".
Each exchange assigns its own identifier at this level:
- PX: `line_id` (globally unique string)
- Kalshi: `ticker` + `yes`/`no`
- Optic: `odd.id`

**Example path:**

```
Game:    2026-02-27 HOU @ ORL
Market:  team_total + HOU
Line:    107.5
Side:    under
  → PX line_id: "a3f9c2..."
  → Kalshi: KXNBATEAMTOTAL-26FEB27HOUORL-HOU107, no
  → Optic: odd.id "xyz123..."
```

The matching engine's job: given a Side on one exchange, find
the same Side on the others.  Everything above Side (Game,
Market, Line) narrows the search; the Side is where pairing
happens.


## Three-source merge

The merge strategy in `main()`:

1. Build PX `CanonicalRow`s from classified markets
   (`build_px_rows`), index by `row_key`.
2. Build Kalshi `CanonicalRow`s from parsed tickers
   (`build_kalshi_rows`).  For each, look up `row_key` in the
   index — if found, stamp Kalshi fields onto the existing PX
   row; otherwise append as Kalshi-only.
3. Build Optic `CanonicalRow`s from `OpticGame.odds`
   (`build_optic_rows`).  Same merge-or-append by `row_key`.
4. Verify Optic `source_ids` agree with our PX/Kalshi matching
   (`verify_optic_source_ids`).

The merge key (`row_key`) is:
```
(date, home, away, market_type, entity, normalize_line(line), side)
```

Covers 16 market types: 4 game/team-scoped (moneyline,
point_spread, game_total, team_total) and 12 player-scoped
(see `optic-players-plan.md` for details).


## What each source provides per game

**PX** — markets grouped by `MarketType` via `wsd`:

```
moneyline:      1 market, 1 wsd.market_line, 2 selections (outcome_id 4/5, competitor_id)
spread:         1 market, N wsd.market_lines, 2 selections each (outcome_id 1714/1715, competitor_id, signed line)
game_total:     1 market, N wsd.market_lines, 2 selections each (outcome_id 12/13)
team_total:     2 markets (home + away, identified by wsd.team_abbrev), N lines each
player_points:  M markets (one per player, identified by wsd.player), N lines each
...
```

**Kalshi** — flat list of tickers like:

```
KXNBAGAME-26FEB26CHAIND-IND           → moneyline, team=IND
KXNBASPREAD-26FEB26CHAIND-IND3        → point_spread, team=IND, integer_line=3
KXNBATOTAL-26FEB26CHAIND-245          → game_total, integer_line=245
KXNBATEAMTOTAL-26FEB26CHAIND-IND98    → team_total, team=IND, integer_line=98
KXNBAPTS-26FEB26CHAIND-CHACWHITE3-25  → player points (not yet matched)
KXNBA2D-26FEB26CHAIND-CHACWHITE3      → double-double (not yet matched)
```

**Optic** — `OpticGame.odds` array with pre-computed half-point
lines, signed spreads, and team_id/player_id references.
Market types keyed by `market_id` string (e.g. "moneyline",
"point_spread", "total_points", "team_total").


## Kalshi ticker parsing

Implemented in `parse_kalshi_event_ticker`.

The event_ticker gives us the game (via `try_parse_game_ticker`).
The market ticker appends a suffix after `{event_ticker}-` that
encodes the bet specifics.  The game's home/away teams
disambiguate `{TEAM}{N}` suffixes (is `IND3` team=IND line=3,
or team=IN line=D3?).

All 16 game-scoped Kalshi ticker types are recognized by
`_extract_ticker_type`, but only 4 produce canonical rows
(`_KALSHI_TABLE_TYPES`):

| Prefix    | MarketType   | Suffix pattern   | Status     |
|-----------|--------------|------------------|------------|
| GAME      | moneyline    | `{TEAM}`         | matched    |
| SPREAD    | point_spread | `{TEAM}{N}`      | matched    |
| TOTAL     | game_total   | `{N}`            | matched    |
| TEAMTOTAL | team_total   | `{TEAM}{N}`      | matched    |
| 1HWINNER  | 1h_winner_3way | `{TEAM}` or `TIE` | skipped |
| 2HWINNER  | 2h_winner_3way | `{TEAM}` or `TIE` | skipped |
| 1HSPREAD  | 1h_point_spread | `{TEAM}{N}`   | skipped    |
| 1HTOTAL   | 1h_total     | `{N}`            | skipped    |
| PTS       | player_points | `{PLAYER}-{N}`  | matched    |
| AST       | player_assists | `{PLAYER}-{N}` | matched    |
| REB       | player_rebounds | `{PLAYER}-{N}` | matched   |
| 3PT       | player_threes | `{PLAYER}-{N}`  | matched    |
| BLK       | player_blocks | `{PLAYER}-{N}`  | matched    |
| STL       | player_steals | `{PLAYER}-{N}`  | matched    |
| 2D        | player_double_double | `{PLAYER}` | matched  |
| 3D        | player_triple_double | `{PLAYER}` | matched  |


## Kalshi line conversion

Game-level types: `line = N + 0.5` (e.g. TOTAL-...-228 →
228.5).  Player stat types: `line = N - 0.5` (e.g. "25+
points" → over 24.5).  Double-double and triple-double have
no line (yes/no markets).


## Spread matching

Kalshi `SPREAD-...-IND3` means "IND wins by 3.5+".  The
canonical convention: the asked-about team gets the negative
line (favored), the opponent gets the positive line (underdog).

`build_kalshi_rows` emits two rows per spread ticker:
- `side=team_abbr, line=-parsed.line, kalshi_side="yes"`
- `side=opponent, line=+parsed.line, kalshi_side="no"`

PX spread selections carry a signed `spread_line` per selection
(negative = favored).  The merge key includes the signed line,
so matching is on (line value, direction) not just `abs(line)`.


## PX side-label resolution

`resolve_px_side_label` maps each PX selection to its semantic
side label using `outcome_id`:

| outcome_id | Pattern          | Side label                        |
|------------|------------------|-----------------------------------|
| 4, 5       | team (moneyline) | team abbrev via `competitor_id`   |
| 1714, 1715 | team (spread)    | team abbrev via `competitor_id`   |
| 12         | over/under       | "over"                            |
| 13         | over/under       | "under"                           |
| 1          | yes/no           | "yes"                             |
| 2          | yes/no           | "no"                              |


## Not yet built

### Half-time types

5 half-time/half-winner types remain in `_IGNORED_TYPES`
(PX) and tip `ignore` / overlayed `ignored_ticker_types` (Kalshi):
- `1h_moneyline`, `1h_point_spread`, `1h_total`
- `1h_winner_3way`, `2h_winner_3way`

Optic doesn't offer these, so there's no cross-exchange
merge target.  Kalshi recognizes the ticker types; PX
classifies the first three.  The 3-way types include a
tie outcome which doesn't fit our two-sided canonical model.

### Niche player types

2 player types remain in PX `_IGNORED_TYPES`:
- `player_steals_blocks` — PX only, no Kalshi or Optic
- `player_turnovers` — PX only, not observed in Optic data


## TODO — potential refactors

Ideas drawn from `market_mapping/nba/prophetx.py` and
`nba/verify/verify_moneyline.py`.

### Separate classification from validation

Currently `classify_px_market` and the extract functions mix
"what is this market?" with "is it well-formed?".  Separating
them (classify then validate) makes each easier to test and
reason about.  See the `classify_prophetx_market` /
`validate_prophetx_market` split in
`market_mapping/nba/prophetx.py`.

### Richer Optic verification

Our `verify_optic_source_ids` is binary: IDs match or raise
ValueError.  The earlier `nba/verify/verify_moneyline.py`
classifies each game into a spectrum — Perfect (both), Perfect
(PX only), Perfect (KX only), Partial (IDs agree on overlap but
coverage differs), Mismatch, Disjoint — giving a summary
distribution instead of a hard stop.  It also detects date drift
(same team pair on different dates across sources due to UTC→ET
edge cases).  See `nba/verify/verify_moneyline.py` lines 85-168
and 186-199.
