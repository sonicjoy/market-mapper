"""SX Bet market type id -> canonical MarketType, per sport.

SX types every market with a numeric ``type`` (vendor reference: the
"Market types" table at docs.sx.bet/api-reference/market-types, captured
2026-10-13 in the workspace's ``docs/sxbet/data_samples/``).  The period is
part of the type id (53 = Asian handicap, halftime), so the id alone keys
the market.

**Every entry is one Optic already agrees with.**  On 2026-10-13 (prod),
each (sport, type) below was read off the SX markets Optic itself maps
(``source_ids["SX Bet"]`` in ``markets_us.market_mapping``), and every one
landed on exactly one canonical ``market_type``.  Types Optic never maps for
SX are left out until a rules check says what they settle on:

* soccer 52 "12" -- Who will win, two outcomes: a draw's settlement is not
  documented (draw-no-bet or loss?), so it is not ``moneyline``.
* American football 63 / 202-205 -- half / quarter winners "Home/Away":
  2-way, Optic's period winners are 3-way.
* hockey 28 -- "including overtime": whether a shootout counts is
  unconfirmed.
* baseball 1618 -- F5 winner "12": Optic's F5 moneyline is 3-way.
* 995 anytime TD scorer, 274 outrights, 88 to qualify, 17 BTTS, 41/42.

Three-way (type 1) is listed as three binaries, "X" / "Not X" (and "Tie" /
"Not tie"): only the affirmative outcome is built.  "Not X" is the double
chance on the other two, but the SX maker refuses every Not-X leg (owner
decision 2026-07-16), so no row is made for it.
"""

from __future__ import annotations

from mappers.market_types import MarketType as M

#: The 1X2 binary: outcome one is the result, outcome two its complement.
THREE_WAY_TYPE = 1

SOCCER: dict[int, M] = {
    1: M.MONEYLINE_3WAY,       # 1X2, one binary per result -- 507 Optic-mapped
    2: M.GAME_TOTAL,           # Under/Over -- 1,104
    3: M.POINT_SPREAD,         # Asian Handicap (Optic asian_handicap) -- 680
}

AMERICAN_FOOTBALL: dict[int, M] = {
    226: M.MONEYLINE,                    # 12 incl. OT -- 72
    342: M.POINT_SPREAD,                 # AH incl. OT -- 837
    28: M.GAME_TOTAL,                    # O/U incl. OT -- 861
    53: M.FIRST_HALF_POINT_SPREAD,       # AH halftime -- 122
    77: M.FIRST_HALF_TOTAL,              # O/U halftime -- 116
    64: M.FIRST_QUARTER_POINT_SPREAD,    # AH first period -- 101
    21: M.FIRST_QUARTER_TOTAL,           # O/U first period -- 72
    65: M.SECOND_QUARTER_POINT_SPREAD,   # AH second period -- 1
    45: M.SECOND_QUARTER_TOTAL,          # O/U second period -- 1
    66: M.THIRD_QUARTER_POINT_SPREAD,    # AH third period -- 1
    46: M.THIRD_QUARTER_TOTAL,           # O/U third period -- 1
}

#: Basketball's periods are quarters too; the same ids, the same Optic
#: market ids (1st_half_point_spread, 1st_quarter_total_points ...).
BASKETBALL: dict[int, M] = {
    226: M.MONEYLINE,                    # 5
    342: M.POINT_SPREAD,                 # 15
    28: M.GAME_TOTAL,                    # 20
    53: M.FIRST_HALF_POINT_SPREAD,
    77: M.FIRST_HALF_TOTAL,
    64: M.FIRST_QUARTER_POINT_SPREAD,
    21: M.FIRST_QUARTER_TOTAL,
}

HOCKEY: dict[int, M] = {
    226: M.MONEYLINE,                    # 16
    342: M.POINT_SPREAD,                 # puck line -- 71
}

BASEBALL: dict[int, M] = {
    226: M.MONEYLINE,                    # 2
    342: M.POINT_SPREAD,                 # run line -- 12
    28: M.GAME_TOTAL,                    # 15
    236: M.FIRST_FIVE_TOTAL,             # 1st 5 innings O/U -- 8
    281: M.FIRST_FIVE_POINT_SPREAD,      # 1st 5 innings AH (Optic 1st_half_run_line)
}

TENNIS: dict[int, M] = {
    52: M.MONEYLINE,                     # 18
    166: M.MATCH_TOTAL_GAMES,            # O/U games -- 172
    201: M.POINT_SPREAD,                 # AH games (Optic game_spread) -- 185
    165: M.TOTAL_SETS,                   # set total -- 17
    866: M.SET_HANDICAP,                 # set spread -- 34
    202: M.FIRST_SET_WINNER,             # first period winner -- 18
    203: M.SECOND_SET_WINNER,            # second period winner -- 14
}

#: UFC: a two-fighter "12"; a draw / no contest voids, as Optic's 2-way
#: moneyline does (the DKEX UFC rules check, docs/adding-dkex.md).
MMA: dict[int, M] = {
    52: M.MONEYLINE,
}

#: SX ``sportLabel`` -> crosswalk.
BY_SPORT: dict[str, dict[int, M]] = {
    "Soccer": SOCCER,
    "Football": AMERICAN_FOOTBALL,
    "Basketball": BASKETBALL,
    "Hockey": HOCKEY,
    "Baseball": BASEBALL,
    "Tennis": TENNIS,
    "Mixed Martial Arts": MMA,
}

#: Types deliberately not mapped -- keeps the unknown-type report
#: meaningful.  A type a sport's crosswalk maps wins over this list (tennis
#: maps 52 and 202/203; soccer and American football do not).  See the
#: module docstring for each reason.
IGNORED_TYPES: frozenset[int] = frozenset({
    17, 28, 29, 41, 42, 52, 63, 88, 202, 203, 204, 205, 274, 835, 995, 1536, 1618,
})
