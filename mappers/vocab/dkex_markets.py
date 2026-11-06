"""Shared DKEX market crosswalks, one per sport.

DKEX puts the period in its own symbol segment, so every crosswalk is
keyed on the ``(market, period)`` PAIR: ``TPTS/FG`` is the game total,
``TPTS/H1`` the first-half total, ``TRUNS/IT5`` the first-five-innings
total.  Keying on the market token alone would merge a first-half total
onto the full-game key and publish a contract that settles differently.

Market tokens and their volumes come from the 2026-09-14 public daily
market report (371,046 symbols).  A token DKEX lists but we do not map
goes in the ``*_IGNORED`` set with its reason, so an unknown-market
warning stays meaningful -- the same discipline every venue's explicit
ignore list follows.

Periods DKEX lists that no canonical type exists for (baseball inning 9,
the football quarter / half WIN markets whose ties split 50/50) are simply
absent from the dicts below: they parse fine, classify to None, and are counted as unmapped
rather than being forced onto a neighbouring key.
"""

from __future__ import annotations

from mappers.market_types import MarketType

# === Football (NFL + CFB share a market vocabulary) ===

FOOTBALL: dict[tuple[str, str], MarketType] = {
    ("WIN",   "FG"): MarketType.MONEYLINE,
    ("MOVY",  "FG"): MarketType.POINT_SPREAD,
    ("MOVY",  "H1"): MarketType.FIRST_HALF_POINT_SPREAD,
    ("MOVY",  "Q1"): MarketType.FIRST_QUARTER_POINT_SPREAD,
    # Half / quarter winners: DKEX settles a tie 50/50 on both sides, Optic's
    # 3-way prices the tie as its own outcome.  Mapped anyway (only the team
    # leg is stamped); trade them knowing the tie settles differently.
    ("WIN",   "H1"): MarketType.FIRST_HALF_WINNER_3WAY,
    ("WIN",   "H2"): MarketType.SECOND_HALF_WINNER_3WAY,
    ("WIN",   "Q1"): MarketType.FIRST_QUARTER_WINNER_3WAY,
    ("WIN",   "Q2"): MarketType.SECOND_QUARTER_WINNER_3WAY,
    ("WIN",   "Q3"): MarketType.THIRD_QUARTER_WINNER_3WAY,
    ("WIN",   "Q4"): MarketType.FOURTH_QUARTER_WINNER_3WAY,
    ("MOVY",  "Q2"): MarketType.SECOND_QUARTER_POINT_SPREAD,
    ("MOVY",  "Q3"): MarketType.THIRD_QUARTER_POINT_SPREAD,
    ("MOVY",  "Q4"): MarketType.FOURTH_QUARTER_POINT_SPREAD,
    ("MOVY",  "H2"): MarketType.SECOND_HALF_POINT_SPREAD,
    ("TPTS",  "FG"): MarketType.GAME_TOTAL,
    ("TPTS",  "H1"): MarketType.FIRST_HALF_TOTAL,
    ("TPTS",  "H2"): MarketType.SECOND_HALF_TOTAL,
    ("TPTS",  "Q1"): MarketType.FIRST_QUARTER_TOTAL,
    ("TPTS",  "Q2"): MarketType.SECOND_QUARTER_TOTAL,
    ("TPTS",  "Q3"): MarketType.THIRD_QUARTER_TOTAL,
    ("TPTS",  "Q4"): MarketType.FOURTH_QUARTER_TOTAL,
    ("TMPTS", "FG"): MarketType.TEAM_TOTAL,
    # Player props.  The *OU tokens are the two-sided ("O/U") presentation
    # of the same contract as the bare token -- same settlement, same
    # canonical type.  What differs is which sides the venue shows, and
    # sides live on the leg, not in the symbol.
    ("PPAY",    "FG"): MarketType.PLAYER_PASSING_YARDS,
    ("PPAYOU",  "FG"): MarketType.PLAYER_PASSING_YARDS,
    ("PCMP",    "FG"): MarketType.PLAYER_PASSING_COMPLETIONS,
    ("PPAA",    "FG"): MarketType.PLAYER_PASSING_ATTEMPTS,
    ("PPATD",   "FG"): MarketType.PLAYER_PASSING_TOUCHDOWNS,
    ("PPATDOU", "FG"): MarketType.PLAYER_PASSING_TOUCHDOWNS,
    ("PINT",    "FG"): MarketType.PLAYER_INTERCEPTIONS,
    ("PREY",    "FG"): MarketType.PLAYER_RECEIVING_YARDS,
    ("PREYOU",  "FG"): MarketType.PLAYER_RECEIVING_YARDS,
    ("PREC",    "FG"): MarketType.PLAYER_RECEPTIONS,
    ("PRECOU",  "FG"): MarketType.PLAYER_RECEPTIONS,
    ("PRUY",    "FG"): MarketType.PLAYER_RUSHING_YARDS,
    ("PRUYOU",  "FG"): MarketType.PLAYER_RUSHING_YARDS,
    ("PRUA",    "FG"): MarketType.PLAYER_RUSHING_ATTEMPTS,
    ("PRUAOU",  "FG"): MarketType.PLAYER_RUSHING_ATTEMPTS,
    ("PRUREY",  "FG"): MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    ("FTD",     "FG"): MarketType.FIRST_TOUCHDOWN_SCORER,
    ("LTD",     "FG"): MarketType.LAST_TOUCHDOWN_SCORER,
    ("PSCK",    "FG"): MarketType.PLAYER_SACKS,
    # PTKL is tackles (a safety's line is 3.5, which only fits solo
    # tackles; tackles + assists runs about 6).  Inferred from the lines,
    # the rules text was not available.
    ("PTKL",    "FG"): MarketType.PLAYER_TACKLES,
    # PTKA: "combined tackles and assists recorded by a player in this game"
    # (rules text read 2026-10-05); void if the player takes no snap.  Optic's
    # player_tackles_+_assists.
    ("PTKA",    "FG"): MarketType.PLAYER_TACKLES_ASSISTS,
    # PAST: "assists recorded by a player in this game" (rules text read
    # 2026-10-12), the defensive assisted tackle -- Optic's NFL
    # player_assists prices defenders (Landman, Fiske) at 0.5 / 3.5.  Void
    # if the player takes no snap, as for PTKL and PTKA.
    ("PAST",    "FG"): MarketType.PLAYER_ASSISTS,
    ("PFGM",    "FG"): MarketType.PLAYER_FIELD_GOALS_MADE,
    # "1+ / 2+ touchdowns" ladders: the line is in the token, not in a GTE
    # threshold, so they need FOOTBALL_IMPLIED_LINES to key apart.
    ("PTDS1",   "FG"): MarketType.PLAYER_TOUCHDOWNS,
    ("PTDS2",   "FG"): MarketType.PLAYER_TOUCHDOWNS,
}

#: Markets whose line is implied by the token rather than a GTE threshold.
FOOTBALL_IMPLIED_LINES: dict[str, float] = {
    "PTDS1": 0.5,   # "1+ touchdowns" == over 0.5
    "PTDS2": 1.5,   # "2+ touchdowns" == over 1.5
}

FOOTBALL_IGNORED = frozenset({
    "WCHP",    # Super Bowl / season outright
    "LMVP",
})

# === Baseball ===

BASEBALL: dict[tuple[str, str], MarketType] = {
    ("WIN",   "FG"):  MarketType.MONEYLINE,
    # The run line.  DKEX expresses it as "team wins by >= N", which is
    # the yes side of the -N spread on that team.
    ("MOVY",  "FG"):  MarketType.POINT_SPREAD,
    ("MOVY",  "IT5"): MarketType.FIRST_FIVE_POINT_SPREAD,
    ("TRUNS", "FG"):  MarketType.GAME_TOTAL,
    ("TRUNS", "IT5"): MarketType.FIRST_FIVE_TOTAL,
    ("TRUNS", "I1"):  MarketType.FIRST_INNING_TOTAL,
    # TRUNS/In is runs in inning n alone (IT5 is innings 1-5 together).
    # Inning 9 is mapped too, although an unplayed bottom half (home side
    # ahead) settles at fair value on DKEX and is simply not played in Optic.
    ("TRUNS", "I2"):  MarketType.INNING_2_TOTAL,
    ("TRUNS", "I3"):  MarketType.INNING_3_TOTAL,
    ("TRUNS", "I4"):  MarketType.INNING_4_TOTAL,
    ("TRUNS", "I5"):  MarketType.INNING_5_TOTAL,
    ("TRUNS", "I6"):  MarketType.INNING_6_TOTAL,
    ("TRUNS", "I7"):  MarketType.INNING_7_TOTAL,
    ("TRUNS", "I8"):  MarketType.INNING_8_TOTAL,
    ("TRUNS", "I9"):  MarketType.INNING_9_TOTAL,
    # DKEX settles a tied F5 50/50 on both sides where Optic's 3-way F5
    # prices the tie as its own outcome; only the team-win leg is stamped.
    ("WIN",   "IT5"): MarketType.FIRST_FIVE_MONEYLINE_3WAY,
    # Single-inning 3-way, same shape as F5: a team's own win is stamped YES
    # only, since an inning double chance cannot be priced.  Optic has no
    # 9th-inning 3-way, so none is listed.
    ("WIN",   "I1"):  MarketType.INNING_1_WINNER_3WAY,
    ("WIN",   "I2"):  MarketType.INNING_2_WINNER_3WAY,
    ("WIN",   "I3"):  MarketType.INNING_3_WINNER_3WAY,
    ("WIN",   "I4"):  MarketType.INNING_4_WINNER_3WAY,
    ("WIN",   "I5"):  MarketType.INNING_5_WINNER_3WAY,
    ("WIN",   "I6"):  MarketType.INNING_6_WINNER_3WAY,
    ("WIN",   "I7"):  MarketType.INNING_7_WINNER_3WAY,
    ("WIN",   "I8"):  MarketType.INNING_8_WINNER_3WAY,
    ("PHRN",  "FG"):  MarketType.PLAYER_HOME_RUNS,
    ("PKS",   "FG"):  MarketType.PLAYER_STRIKEOUTS,
    ("PHIT",  "FG"):  MarketType.PLAYER_HITS,
    ("PTBS",  "FG"):  MarketType.PLAYER_BASES,
    ("PHRR",  "FG"):  MarketType.PLAYER_HITS_RUNS_RBIS,
    ("PRBI",  "FG"):  MarketType.PLAYER_RBIS,
}

BASEBALL_IGNORED: frozenset[str] = frozenset()

# === Basketball (WNBA, NBA incl. preseason) ===

BASKETBALL: dict[tuple[str, str], MarketType] = {
    ("WIN",   "FG"): MarketType.MONEYLINE,
    ("MOVY",  "FG"): MarketType.POINT_SPREAD,
    ("TPTS",  "FG"): MarketType.GAME_TOTAL,
    ("TMPTS", "FG"): MarketType.TEAM_TOTAL,
    # Half / quarter spreads: "team's winning margin exceeds the line",
    # period only, overtime excluded (rules read 2026-10-08).
    ("MOVY",  "H1"): MarketType.FIRST_HALF_POINT_SPREAD,
    ("MOVY",  "Q1"): MarketType.FIRST_QUARTER_POINT_SPREAD,
    ("MOVY",  "Q2"): MarketType.SECOND_QUARTER_POINT_SPREAD,
    ("MOVY",  "Q3"): MarketType.THIRD_QUARTER_POINT_SPREAD,
    # Half / quarter totals, same period basis as the spreads (TPTS/Q3 rules
    # read 2026-10-16: overtime excluded).
    ("TPTS",  "H1"): MarketType.FIRST_HALF_TOTAL,
    ("TPTS",  "Q1"): MarketType.FIRST_QUARTER_TOTAL,
    ("TPTS",  "Q2"): MarketType.SECOND_QUARTER_TOTAL,
    ("TPTS",  "Q3"): MarketType.THIRD_QUARTER_TOTAL,
    ("TMPTS", "H1"): MarketType.FIRST_HALF_TEAM_TOTAL,
    # Not mapped (owner 2026-10-23: only what settles like Optic):
    # - WIN/H1, Q1-Q3, Q4: a tied period settles 50/50 on DKEX; Optic's 3-way
    #   team leg loses on a tie and its Q4 2-way pushes it.
    # - H2 (WIN, MOVY, TPTS, TMPTS): counts overtime on DKEX; Optic grades its
    #   2nd_half_* lines on regulation (grader, 2026-10-22/23).
    # Q4 includes overtime on DKEX (rules read 2026-10-16), which is
    # Optic's 4th_quarter_*_incl_ot.
    ("MOVY",  "Q4"): MarketType.FOURTH_QUARTER_POINT_SPREAD_INCL_OT,
    ("TPTS",  "Q4"): MarketType.FOURTH_QUARTER_TOTAL_INCL_OT,
    ("PPTS",  "FG"): MarketType.PLAYER_POINTS,
    ("PREB",  "FG"): MarketType.PLAYER_REBOUNDS,
    ("PAST",  "FG"): MarketType.PLAYER_ASSISTS,
    ("P3PM",  "FG"): MarketType.PLAYER_THREES,
    # NBA props, staging 2026-10-08 (rules text read): every stat counts
    # overtime and settles on Stats Perform's box score; a player absent
    # from the box score settles at the last fair price (void).  The *OU
    # tokens are the two-sided presentation of the bare token, as in
    # football -- same settlement, same canonical type.
    ("PPTSOU", "FG"): MarketType.PLAYER_POINTS,
    ("PREBOU", "FG"): MarketType.PLAYER_REBOUNDS,
    ("PASTOU", "FG"): MarketType.PLAYER_ASSISTS,
    ("PBLK",   "FG"): MarketType.PLAYER_BLOCKS,
    # Combined stats: PPRB points + rebounds, PPAS points + assists, PRAS
    # rebounds + assists, PPRA all three.
    ("PPRB",   "FG"): MarketType.PLAYER_PTS_REB,
    ("PPAS",   "FG"): MarketType.PLAYER_PTS_AST,
    ("PRAS",   "FG"): MarketType.PLAYER_REB_AST,
    ("PPRA",   "FG"): MarketType.PLAYER_PTS_REB_AST,
    ("PPRAOU", "FG"): MarketType.PLAYER_PTS_REB_AST,
    # Double-double: 10+ in any two of points, rebounds, assists, steals,
    # blocks.  No strike: a plain yes/no per player.
    ("DDBL",   "FG"): MarketType.PLAYER_DOUBLE_DOUBLE,
    # Steals and triple-double (rules read 2026-10-16): overtime counts,
    # absent player voids, as for the props above.
    ("PSTL",   "FG"): MarketType.PLAYER_STEALS,
    ("PSTLOU", "FG"): MarketType.PLAYER_STEALS,
    ("TDBL",   "FG"): MarketType.PLAYER_TRIPLE_DOUBLE,
}

BASKETBALL_IGNORED: frozenset[str] = frozenset()

# === Soccer ===
#
# Every soccer contract DKEX lists settles on 90 minutes plus stoppage
# time, extra time and penalties excluded (the venue's per-market rules
# text, read 2026-09-29) -- the same basis as Optic's moneyline /
# double_chance / asian_handicap / total_goals / both_teams_to_score.
#
# DWIN is the 3-way result, listed as three binaries: one per team (the
# team is parameters.participant) and the draw (no participant).  Each
# leg's No side is the double chance on the other two outcomes; see
# mappers/exchanges/dkex.py:_three_way_rows.
#
# SGL1 is the anytime goalscorer, "at least one goal" at strike 0.5.  A
# player who does not enter the match settles at the last fair price
# rather than No -- the usual anytime-scorer void treatment.  The "No
# Goalscorer" leg has no participant and drops as unbuildable.

SOCCER: dict[tuple[str, str], MarketType] = {
    ("DWIN",  "FG"): MarketType.MONEYLINE_3WAY,
    # "Team wins by >= N.5 goals": the yes side of the -N.5 Asian
    # handicap on that team (Optic asian_handicap); half lines only, so
    # no push.
    ("MOVY",  "FG"): MarketType.POINT_SPREAD,
    ("TGLS",  "FG"): MarketType.GAME_TOTAL,
    ("BTMSC", "FG"): MarketType.BTTS,
    ("SGL1",  "FG"): MarketType.PLAYER_GOALS,
}

SOCCER_IGNORED: frozenset[str] = frozenset()

# === Tennis ===
#
# WIN/MTH is the match winner: the winning player's leg resolves Yes, the
# other No; a match abandoned before a set is played settles at the last
# fair price (a void).  Two outcomes and no draw, so No on one player is
# Yes on the other -- Optic's 2-way moneyline.  WTRN/TRN is the
# tournament outright (period TRN is ignored for every sport).

# GMAR/MTH is the games handicap and SMAR/MTH the sets handicap: "player
# wins by >= N", the yes side of the -N line on that player (the MOVY shape),
# a tiebreak -- a match tiebreak too -- counting as one game or set (market
# rules, fetched 2026-10-09).  TGMS/MTH is total games, yes is over.  WIN/S1
# and WIN/S2 are the 1st and 2nd set winner; a set that is not completed
# settles at the last fair price, the push Optic's set moneyline gives.
TENNIS: dict[tuple[str, str], MarketType] = {
    ("WIN", "MTH"): MarketType.MONEYLINE,
    ("GMAR", "MTH"): MarketType.POINT_SPREAD,
    ("SMAR", "MTH"): MarketType.SET_HANDICAP,
    ("TGMS", "MTH"): MarketType.MATCH_TOTAL_GAMES,
    ("WIN", "S1"): MarketType.FIRST_SET_WINNER,
    ("WIN", "S2"): MarketType.SECOND_SET_WINNER,
}

TENNIS_IGNORED: frozenset[str] = frozenset({"WTRN"})

# === UFC ===
#
# WIN/FT is the bout winner by any method.  A draw or no contest settles
# at the last fair price (a void) -- the same as Optic's 2-way moneyline
# pushing -- so No on one fighter is Yes on the other.
#
# TRNDS/FT is total rounds (announced 2026-10-22, staging; production from
# the 10/24 cards): no participants, yes is over the strike, Optic's
# total_rounds.  The rules text was not read, so the stoppage-mid-round
# treatment is inferred from that shared convention, not confirmed.

UFC: dict[tuple[str, str], MarketType] = {
    ("WIN", "FT"): MarketType.MONEYLINE,
    ("TRNDS", "FT"): MarketType.TOTAL_ROUNDS,
}

UFC_IGNORED: frozenset[str] = frozenset()

# === Hockey ===
#
# WIN/FG is the game winner including overtime and the shootout (market
# rules, fetched 2026-09-29): no tie, so No on one team is Yes on the
# other -- Optic's 2-way NHL moneyline.  DWIN/GNO is the regulation-only
# 3-way, whose No leg is "the other team or a tie"; it is not mapped.
#
# MOVY/FG is the puck line: "team wins by >= N", the yes side of the -N
# line on that team (Optic puck_line).  We have no rules text saying
# whether DKEX counts overtime, and at 1.5+ it does not matter: overtime
# is sudden death and the shootout adds one goal, so a margin of 2+ only
# ever stands at the end of regulation.  A 0.5 line would be the
# regulation-or-not moneyline question again, so HOCKEY_MIN_STRIKES keeps
# it out (DKEX listed 1.5 / 2.5 / 3.5 only on 2026-10-03).
#
# TGLS/PRn and TMGLS/PRn are the nth period's game and team total goals.
# A period ends at its horn, so overtime and the shootout never touch
# them -- the same contract as Optic's nth_period_total_goals / _team_total.
#
# TGLS/FG and TMGLS/FG are the full-game total and team total, mapped onto
# Optic's total_goals / team_total exactly as Kalshi, Novig, crypto.com and
# Underdog already are.  The DKEX rules text for these two was not read
# (the venue API refused our address on 2026-10-06), so the shootout-goal
# treatment is inferred from that shared convention, not confirmed.
# Trading (2026-10-07): NHL props, team goals included, count overtime across
# the board, so TMGLS is on.
#
# DWIN/GNO is the regulation-only 3-way (rules read 2026-09-29: overtime
# and the shootout excluded, a level game resolves the Tie selection Yes),
# i.e. Optic's moneyline_3-way.  OVTM/FG is "the game goes to overtime".
#
# Player props.  Overtime counts toward a skater's or goalie's line and the
# shootout never does, in every book; the *OU tokens are the two-sided
# presentation of the bare token, as in football.  SGL1 is the anytime
# goalscorer ("at least one goal" at strike 0.5, same as soccer) and SFGL
# the first goalscorer.

HOCKEY: dict[tuple[str, str], MarketType] = {
    ("WIN", "FG"): MarketType.MONEYLINE,
    ("MOVY", "FG"): MarketType.POINT_SPREAD,
    ("DWIN", "GNO"): MarketType.MONEYLINE_3WAY,
    ("TGLS", "FG"): MarketType.GAME_TOTAL,
    ("TGLS", "PR1"): MarketType.FIRST_PERIOD_TOTAL,
    ("TGLS", "PR2"): MarketType.SECOND_PERIOD_TOTAL,
    ("TGLS", "PR3"): MarketType.THIRD_PERIOD_TOTAL,
    ("TMGLS", "FG"): MarketType.TEAM_TOTAL,
    ("TMGLS", "PR1"): MarketType.FIRST_PERIOD_TEAM_TOTAL,
    ("TMGLS", "PR2"): MarketType.SECOND_PERIOD_TEAM_TOTAL,
    ("TMGLS", "PR3"): MarketType.THIRD_PERIOD_TEAM_TOTAL,
    ("OVTM", "FG"): MarketType.WILL_THERE_BE_OVERTIME,
    ("BTMSC", "GNO"): MarketType.BTTS_REG_TIME,
    ("PGLS", "FG"): MarketType.PLAYER_GOALS,
    ("SGL1", "FG"): MarketType.PLAYER_GOALS,
    ("SFGL", "FG"): MarketType.FIRST_GOAL_SCORER,
    ("PAST", "FG"): MarketType.PLAYER_ASSISTS,
    ("PPTS", "FG"): MarketType.PLAYER_POINTS,
    ("PPTSOU", "FG"): MarketType.PLAYER_POINTS,
    ("PPPTS", "FG"): MarketType.PLAYER_POWER_PLAY_POINTS,
    ("PSOG", "FG"): MarketType.PLAYER_SHOTS_ON_GOAL,
    ("PSOGOU", "FG"): MarketType.PLAYER_SHOTS_ON_GOAL,
    ("GSVS", "FG"): MarketType.PLAYER_SAVES,
    ("GSVSOU", "FG"): MarketType.PLAYER_SAVES,
}

HOCKEY_MIN_STRIKES: dict[tuple[str, str], float] = {
    ("MOVY", "FG"): 1.5,
}

HOCKEY_IGNORED: frozenset[str] = frozenset()
