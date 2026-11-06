# Markets Roadmap

What we handle, what we intend to handle, and what's out of scope.


## Coverage policy

We only add a market type once PX or Kalshi offers it.  Optic is
permissive (silently skips unknown market_ids), but PX and Kalshi
are strict — the pipeline raises on any unrecognized PX market
name or Kalshi ticker type.  That crash is our signal to evaluate
a new market type.

The only "exchange orphan" today is `player_turnovers`: PX offers
it, Optic and Kalshi do not.  PX rows for turnovers flow through
with no Optic match (`optic_id=None`), which is correct.


## NBA

### Implemented (24 MarketType values)

**Game-scoped (3):** moneyline, point_spread, game_total

**First-half / second-half (5):**
- `1h_moneyline` — PX + Optic (2-way)
- `1h_point_spread` — PX + Kalshi + Optic
- `1h_total` — PX + Kalshi + Optic
- `1h_winner_3way` — Kalshi + Optic (3-way: home/away/tie)
- `2h_winner_3way` — Kalshi + Optic (3-way: home/away/tie)

**Team-scoped (1):** team_total

**Player-scoped (15):**
- Stat lines (6): player_points, player_assists,
  player_rebounds, player_threes, player_blocks,
  player_steals
- Yes/no (2): player_double_double, player_triple_double
- Combos (5, PX + Optic — no Kalshi):
  player_pts_ast, player_pts_reb, player_pts_reb_ast,
  player_reb_ast, player_steals_blocks
- PX-only (1): player_turnovers
- H2H (1): player_assists_h2h (Optic only, needs grouping_key)

### Design notes

**2-way vs 3-way first-half moneylines are different bet types.**
PX's 2-way `First Half Moneyline` and Kalshi's 3-way `1HWINNER`
are genuinely different categories — the 2-way has an implicit
"tie = push" mechanism, while the 3-way prices the tie as a
separate outcome.  Optic confirms this by carrying them as
separate market IDs (`1st_half_moneyline` vs
`1st_half_moneyline_3-way`).

**3-way markets emit 3 canonical rows** with side values of
home team, away team, or `_TIE`.  The leading underscore
prevents collision with any team abbreviation.

**Deliberate omission: Optic `2nd_half_moneyline`** (2-way).
Neither PX nor Kalshi offers a 2-way second-half moneyline,
so there's nothing to match against.

### Exchange detail

**PX** classifies into 21 MarketType values via exact match
or market name suffix.  All 21 implemented.

**Kalshi** classifies into 16 game-level ticker types.  All 16
implemented:
- Game-level (8): GAME, SPREAD, TOTAL, TEAMTOTAL,
  1HWINNER, 1HSPREAD, 1HTOTAL, 2HWINNER
- Player-level (8): PTS, AST, REB, 3PT, BLK, STL, 2D, 3D

**Kalshi futures** (~20 prefixes, out of scope for game-level
matching): WINS, PLAYOFF, MVP, ROY, DPOY, COY, SIXTH, MIMP,
FINMVP, EFINMVP, WFINMVP, DRAFT*, TOPPICK, LOTTERYODDS,
PLAYIN, CLUTCH, TEAM, SEATTLE, conference/division seeds.

### Optic catalog (90 market_ids in data)

27 handled (mapped to MarketType via table_types).
63 not handled, broken down below.

**H2H (10 not handled) — next to add:**
- player_points_h2h_moneyline, player_points_h2h_spread
- player_rebounds_h2h_moneyline, player_rebounds_h2h_spread
- player_made_threes_h2h_moneyline, player_made_threes_h2h_spread
- player_blocks_h2h_moneyline, player_blocks_h2h_spread
- player_assists_h2h_spread

(player_assists_h2h_moneyline is already handled: this is the foundation for future 
markets that need the Optic grouping_key for disambiguation.)

**Multi-leg / parlay (14) — out of scope:**
- `_combo_` variants: player_points_combo_, player_assists_combo_,
  player_rebounds_combo_, player_made_threes_combo_,
  player_blocks_combo_
- `_each_` variants: player_points_each_, player_assists_each_,
  player_rebounds_each_, player_made_threes_each_,
  player_blocks_each_, player_steals_each_
- `_either_` variants: player_points_either_,
  player_assists_either_, player_rebounds_either_,
  player_made_threes_either_, player_blocks_either_,
  player_steals_either_

**Quarter-scoped (~20) — out of scope, no exchange overlap:**
- 1st quarter: moneyline, moneyline_3-way, point_spread,
  total_points, team_total, player_points, player_assists,
  player_rebounds
- 2nd quarter: moneyline, moneyline_3-way, point_spread,
  total_points, team_total
- 3rd quarter: moneyline, moneyline_3-way, point_spread,
  total_points, team_total
- 4th quarter: moneyline, moneyline_3-way, point_spread,
  total_points, team_total

**Half-scoped extras (4) — out of scope, no exchange overlap:**
- 1st_half_team_total, 2nd_half_moneyline,
  2nd_half_point_spread, 2nd_half_total_points

**Race-to (~15) — out of scope:**
- Full game: race_to_5/10/15/20_points
- 1st half: 1st_half_race_to_40/45/50/55/60_points
- 2nd half: 2nd_half_race_to_40/45/50/55/60_points
- Per quarter: 1st/2nd/3rd/4th_quarter_race_to_*

**Odd/even (~6) — out of scope:**
- total_points_odd_even, team_total_odd_even,
  1st/2nd_half_total_points_odd_even,
  1st/2nd_quarter_total_points_odd_even,
  2nd_quarter_team_total_odd_even

**Game-level aggregate stats (8) — out of scope:**
- Game totals: total_assists, total_blocks, total_steals,
  total_made_threes, both_teams_total_points
- Team totals: team_total_assists, team_total_blocks,
  team_total_steals, team_total_made_threes

**Shot-type props (5) — out of scope:**
- player_field_goals_made, player_field_goals_attempted,
  player_made_two_pointers, player_threes_attempted,
  player_two_pointers_attempted

**Novelty / special (6) — out of scope:**
- first_basket, first_basket_including_ft, first_made_three,
  team_first_basket, team_first_made_three, halftime_fulltime

**Most-X-player (5) — out of scope:**
- most_points_player, most_assists_player,
  most_rebounds_player, most_made_threes_player,
  most_points_+_rebounds_+_assists_player

**Other (2) — out of scope:**
- moneyline_3-way (full-game 3-way), will_there_be_overtime

**Micro-period (3) — out of scope:**
- 1st_3_minutes_player_points, 1st_3_minutes_player_assists,
  1st_3_minutes_player_rebounds


## NCAAB

### Implemented (13 MarketType values)

**Game-scoped (3):** moneyline, point_spread, game_total

**First-half (3):**
- `1h_moneyline` — PX + Optic (2-way)
- `1h_point_spread` — PX + Kalshi + Optic
- `1h_total` — PX + Kalshi + Optic
- `1h_winner_3way` — Kalshi + Optic (3-way)

**Team-scoped (1):** team_total

**Player-scoped (5):**
- Stat lines (4): player_points, player_assists,
  player_rebounds, player_threes
- Combos (1, PX + Optic): player_pts_reb

### Exchange detail

**PX** classifies into 12 MarketType values.  All implemented.

**Kalshi** classifies into 6 game-level ticker types (no player
props).  All implemented.  Awards `NAISMITH` / `UNDEFEATED` are tip
`ignore` pins (Python factories ship empty ignored sets).

### Optic catalog (43 market_ids in data)

13 handled.  30 not handled, broken down below.

**Half-scoped (10):**
- 1st half: 1st_half_team_total,
  1st_half_total_points_odd_even,
  1st_half_race_to_10/15/20/25_points
- 2nd half: 2nd_half_moneyline, 2nd_half_moneyline_3-way,
  2nd_half_point_spread, 2nd_half_team_total,
  2nd_half_total_points, 2nd_half_total_points_odd_even

**Player props not yet mapped (6):**
- player_points_+_assists, player_points_+_rebounds_+_assists
  (NBA maps these but NCAAB does not — no Kalshi counterpart)
- player_points_each_, player_points_either_,
  player_rebounds_each_, player_rebounds_either_

**Game-level (5):**
- both_teams_total_points, moneyline_3-way,
  total_points_odd_even, team_total_odd_even,
  will_there_be_overtime

**Race-to (5):**
- race_to_5/10/15/20/25/30/40/50_points

**Other (4):**
- first_basket_including_ft, halftime_fulltime


## NHL, Soccer, UFC

Data files exist under `data/` but no league mappers are
implemented.  Out of scope until exchange coverage is assessed.
