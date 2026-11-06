"""Canonical NBA market types.

Exchange-independent definitions of the betting markets we track: each type is one
real-world question about a game, whatever way an exchange (PX, Kalshi, ...) encodes it.

The Scope on each type declares what additional parameter (beyond
the game) is needed to uniquely identify a market instance:

  GAME   — one per game (moneyline, spread, game_total)
  TEAM   — one per game per team (team_total)
  PLAYER — one per game per player (all player props)

The Shape on each type captures the structural form — how many rows a market produces,
what side labels it uses, and how lines are signed. Exchange build_rows dispatches on
(scope, shape), so NBA's POINT_SPREAD and NHL's PUCK_LINE are both Shape.SPREAD.
"""

from enum import Enum


class Scope(Enum):
    GAME = "game"
    TEAM = "team"
    PLAYER = "player"


class Shape(Enum):
    # (entity, line, side) splits a game+market_type's sides for every shape but
    # H2H, whose merge key also needs grouping_key (two matchups can share a player).
    # The optic.build_rows collision guard firing on a non-H2H shape means the market
    # doesn't fit the key: rethink before adding grouping_key (add-grouping-key.md).
    MONEYLINE = "moneyline"        # side=team, no line
    SPREAD = "spread"              # side=team, signed line
    TOTAL = "total"                # side=over/under, unsigned line
    THREE_WAY = "three_way"        # side=team or _TIE, no line
    OVER_UNDER = "over_under"      # side=over/under, line
    YES_NO = "yes_no"              # side=yes/no, no line
    YES_NO_LINE = "yes_no_line"    # side=yes/no, with line
    H2H = "h2h"                    # side=player, grouping_key=matchup pair
    # side=team abbrev or _TIE (winner of the scoreline, or draw); line=a
    # winner-goals.loser-goals numeric encoding of the scoreline (see
    # optic.py/polymarket.py build_rows' CORRECT_SCORE branches — both sides
    # must compute this identically, since (entity, line, side) is the merge
    # key). entity=None (GAME scope).
    CORRECT_SCORE = "correct_score"
    # side=the two covered 3-way outcomes, see shared.double_chance_side;
    # no line.
    DOUBLE_CHANCE = "double_chance"


class MarketType(Enum):
    scope: Scope
    shape: Shape

    def __new__(cls, value: str, scope: Scope, shape: Shape):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.scope = scope
        obj.shape = shape
        return obj

    # Game-scoped — one market per game
    MONEYLINE               = ("moneyline",             Scope.GAME,   Shape.MONEYLINE)
    POINT_SPREAD            = ("point_spread",          Scope.GAME,   Shape.SPREAD)
    # PX ships EPL "Spread (Regular Time)" sometimes as type=sup_moneyline.
    # Same shape as POINT_SPREAD but a distinct PX orderbook; downgrades
    # to POINT_SPREAD in build_rows when no regular spread coexists.
    POINT_SPREAD_YN         = ("point_spread_yn",       Scope.GAME,   Shape.SPREAD)
    GAME_TOTAL              = ("game_total",            Scope.GAME,   Shape.TOTAL)
    FIRST_HALF_MONEYLINE    = ("1h_moneyline",          Scope.GAME,   Shape.MONEYLINE)
    FIRST_HALF_POINT_SPREAD = ("1h_point_spread",       Scope.GAME,   Shape.SPREAD)
    FIRST_HALF_TOTAL        = ("1h_total",              Scope.GAME,   Shape.TOTAL)
    # Soccer 2nd-half game total — same shape as FIRST_HALF_TOTAL, just the
    # other half.
    SECOND_HALF_TOTAL       = ("2h_total",              Scope.GAME,   Shape.TOTAL)
    # Baseball 1st-inning total (runs scored in the first inning only).
    FIRST_INNING_TOTAL      = ("first_inning_total",    Scope.GAME,   Shape.TOTAL)
    # Baseball first-five-innings (F5) game lines — same shapes as full-game
    # ML/spread/total, scoped to innings 1–5.
    FIRST_FIVE_MONEYLINE    = ("f5_moneyline",          Scope.GAME,   Shape.MONEYLINE)
    FIRST_FIVE_POINT_SPREAD = ("f5_point_spread",       Scope.GAME,   Shape.SPREAD)
    FIRST_FIVE_TOTAL        = ("f5_total",              Scope.GAME,   Shape.TOTAL)
    # In Optic's taxonomy but unpriced on MLB (14d census, zero ticks); wired for
    # readiness. 3-WAY, NOT the 2-way FIRST_FIVE_MONEYLINE above.
    FIRST_FIVE_MONEYLINE_3WAY = ("f5_moneyline_3way",   Scope.GAME,   Shape.THREE_WAY)
    # First-three-innings 3-way (crypto Moneyline (3-Way) @ 1st-3rd Inning;
    # Optic 1st_3_innings_moneyline_3-way). Distinct from F5: leads after 3
    # vs after 5. No Optic F3 spread/total counterpart as of 2026-09-02.
    FIRST_THREE_MONEYLINE_3WAY = ("f3_moneyline_3way",  Scope.GAME,   Shape.THREE_WAY)
    # First-seven-innings 3-way (Optic 1st_7_innings_moneyline_3-way).
    FIRST_SEVEN_MONEYLINE_3WAY = ("f7_moneyline_3way",  Scope.GAME,   Shape.THREE_WAY)
    EXTRA_INNINGS           = ("extra_innings",         Scope.GAME,   Shape.YES_NO)
    # Optic Nth_inning_moneyline_3-way; no inning 9 (home half may not be played).
    INNING_1_WINNER_3WAY = ("i1_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_2_WINNER_3WAY = ("i2_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_3_WINNER_3WAY = ("i3_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_4_WINNER_3WAY = ("i4_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_5_WINNER_3WAY = ("i5_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_6_WINNER_3WAY = ("i6_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_7_WINNER_3WAY = ("i7_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    INNING_8_WINNER_3WAY = ("i8_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    # Optic Nth_inning_total_runs (inning 1 is FIRST_INNING_TOTAL above).
    INNING_2_TOTAL          = ("i2_total",              Scope.GAME,   Shape.TOTAL)
    INNING_3_TOTAL          = ("i3_total",              Scope.GAME,   Shape.TOTAL)
    INNING_4_TOTAL          = ("i4_total",              Scope.GAME,   Shape.TOTAL)
    INNING_5_TOTAL          = ("i5_total",              Scope.GAME,   Shape.TOTAL)
    INNING_6_TOTAL          = ("i6_total",              Scope.GAME,   Shape.TOTAL)
    INNING_7_TOTAL          = ("i7_total",              Scope.GAME,   Shape.TOTAL)
    INNING_8_TOTAL          = ("i8_total",              Scope.GAME,   Shape.TOTAL)
    INNING_9_TOTAL          = ("i9_total",              Scope.GAME,   Shape.TOTAL)
    # Hockey Nth-period total goals (Optic Nth_period_total_goals); no overtime.
    FIRST_PERIOD_TOTAL      = ("p1_total",              Scope.GAME,   Shape.TOTAL)
    SECOND_PERIOD_TOTAL     = ("p2_total",              Scope.GAME,   Shape.TOTAL)
    THIRD_PERIOD_TOTAL      = ("p3_total",              Scope.GAME,   Shape.TOTAL)
    MONEYLINE_DNB           = ("moneyline_dnb",         Scope.GAME,   Shape.MONEYLINE)
    MONEYLINE_3WAY          = ("moneyline_3way",        Scope.GAME,   Shape.THREE_WAY)
    # Soccer double chance: two of MONEYLINE_3WAY's three outcomes. Kalshi
    # prices it only as the No side of a GAME ticker (1H for the first-half
    # form below); see kalshi_complement.
    DOUBLE_CHANCE           = ("double_chance",         Scope.GAME,   Shape.DOUBLE_CHANCE)
    FIRST_HALF_WINNER_3WAY  = ("1h_winner_3way",        Scope.GAME,   Shape.THREE_WAY)
    FIRST_HALF_DOUBLE_CHANCE = ("1h_double_chance",     Scope.GAME,   Shape.DOUBLE_CHANCE)
    SECOND_HALF_WINNER_3WAY = ("2h_winner_3way",        Scope.GAME,   Shape.THREE_WAY)
    # NFL/NCAAF 1st-quarter game lines (Optic 1st_quarter_*; Poly US 1q-*).
    FIRST_QUARTER_WINNER_3WAY = ("1q_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    FIRST_QUARTER_POINT_SPREAD = ("1q_point_spread",    Scope.GAME,   Shape.SPREAD)
    FIRST_QUARTER_TOTAL     = ("1q_total",              Scope.GAME,   Shape.TOTAL)
    # NHL goals in the first 10 minutes (Optic 1st_10_minutes_total_goals), then
    # period game lines (Optic 1st_period_puck_line / _total_goals).
    FIRST_10_MINUTES_TOTAL  = ("first_10_minutes_total", Scope.GAME,  Shape.TOTAL)
    FIRST_PERIOD_WINNER_3WAY = ("p1_winner_3way",       Scope.GAME,   Shape.THREE_WAY)
    SECOND_PERIOD_WINNER_3WAY = ("p2_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    THIRD_PERIOD_WINNER_3WAY = ("p3_winner_3way",       Scope.GAME,   Shape.THREE_WAY)
    FIRST_PERIOD_POINT_SPREAD = ("p1_point_spread",     Scope.GAME,   Shape.SPREAD)
    SECOND_PERIOD_POINT_SPREAD = ("p2_point_spread",    Scope.GAME,   Shape.SPREAD)
    THIRD_PERIOD_POINT_SPREAD = ("p3_point_spread",     Scope.GAME,   Shape.SPREAD)
    TOTAL_TOUCHDOWNS        = ("total_touchdowns",      Scope.GAME,   Shape.TOTAL)
    # NFL/NCAAF 2nd-4th-quarter game lines (Optic Nth_quarter_*).
    SECOND_QUARTER_WINNER_3WAY = ("2q_winner_3way",     Scope.GAME,   Shape.THREE_WAY)
    SECOND_QUARTER_POINT_SPREAD = ("2q_point_spread",   Scope.GAME,   Shape.SPREAD)
    SECOND_QUARTER_TOTAL    = ("2q_total",              Scope.GAME,   Shape.TOTAL)
    THIRD_QUARTER_WINNER_3WAY = ("3q_winner_3way",      Scope.GAME,   Shape.THREE_WAY)
    THIRD_QUARTER_POINT_SPREAD = ("3q_point_spread",    Scope.GAME,   Shape.SPREAD)
    THIRD_QUARTER_TOTAL     = ("3q_total",              Scope.GAME,   Shape.TOTAL)
    FOURTH_QUARTER_WINNER_3WAY = ("4q_winner_3way",     Scope.GAME,   Shape.THREE_WAY)
    FOURTH_QUARTER_POINT_SPREAD = ("4q_point_spread",   Scope.GAME,   Shape.SPREAD)
    FOURTH_QUARTER_TOTAL    = ("4q_total",              Scope.GAME,   Shape.TOTAL)
    # Basketball periods counting overtime (Optic 4th_quarter_*_incl_ot, 2nd_half_team_total_incl_ot).
    FOURTH_QUARTER_MONEYLINE_INCL_OT = ("4q_moneyline_incl_ot", Scope.GAME, Shape.MONEYLINE)
    FOURTH_QUARTER_POINT_SPREAD_INCL_OT = ("4q_point_spread_incl_ot", Scope.GAME, Shape.SPREAD)
    FOURTH_QUARTER_TOTAL_INCL_OT = ("4q_total_incl_ot",  Scope.GAME,   Shape.TOTAL)
    SECOND_HALF_TEAM_TOTAL_INCL_OT = ("2h_team_total_incl_ot", Scope.TEAM, Shape.TOTAL)
    # Both teams score at least one point in the quarter (Optic
    # Nth_quarter_both_teams_to_score).
    FIRST_QUARTER_BOTH_SCORE = ("1q_both_teams_score",  Scope.GAME,   Shape.YES_NO)
    SECOND_QUARTER_BOTH_SCORE = ("2q_both_teams_score", Scope.GAME,   Shape.YES_NO)
    THIRD_QUARTER_BOTH_SCORE = ("3q_both_teams_score",  Scope.GAME,   Shape.YES_NO)
    FOURTH_QUARTER_BOTH_SCORE = ("4q_both_teams_score", Scope.GAME,   Shape.YES_NO)
    GAME_TOTAL_PASSING_TOUCHDOWNS = (
        "total_passing_touchdowns", Scope.GAME, Shape.TOTAL,
    )
    GAME_TOTAL_RUSHING_TOUCHDOWNS = (
        "total_rushing_touchdowns", Scope.GAME, Shape.TOTAL,
    )
    GAME_TOTAL_RUSHING_YARDS = ("total_rushing_yards",  Scope.GAME,   Shape.TOTAL)
    GAME_TOTAL_PASSING_YARDS = ("total_passing_yards",  Scope.GAME,   Shape.TOTAL)
    # First team to score a touchdown (Optic first_team_touchdown; its
    # team-less "Neither" leg is the TIE side).
    FIRST_TEAM_TOUCHDOWN    = ("first_team_touchdown",  Scope.GAME,   Shape.THREE_WAY)
    WILL_THERE_BE_OVERTIME  = ("will_there_be_overtime", Scope.GAME,  Shape.YES_NO)
    PICK_SIX                = ("pick_six",              Scope.GAME,   Shape.YES_NO)
    BOTH_TEAMS_SCORE_TD     = ("both_teams_score_td",   Scope.GAME,   Shape.YES_NO)
    RACE_TO_POINTS          = ("race_to_points",        Scope.GAME,   Shape.THREE_WAY)
    # One Yes per outcome; the quarter ("q1".."q4") is the grouping_key.
    # Dead heat on a tie, on the venue and at the books.
    HIGHEST_SCORING_QUARTER = ("highest_scoring_quarter", Scope.GAME, Shape.YES_NO)
    # Halftime / full time (Optic halftime_fulltime, "A :: B"): one Yes per
    # outcome, grouping_key "<1H side>|<full-time side>" (side or _TIE).
    HALFTIME_FULLTIME       = ("halftime_fulltime",     Scope.GAME,   Shape.YES_NO)
    WILL_THERE_BE_A_SAFETY  = ("will_there_be_a_safety", Scope.GAME,  Shape.YES_NO)
    SUCCESSFUL_TWO_POINT_CONVERSION = (
        "successful_2_point_conversion", Scope.GAME, Shape.YES_NO,
    )
    # Soccer "first team to score" — 3-way (team/team/Draw), same shape as
    # MONEYLINE_3WAY/SECOND_HALF_WINNER_3WAY. The complementary "Neither team
    # to score first?" leg has no clean optic selection under THREE_WAY_FIXED
    # (_TIE means Draw, not "no goal") and stays permanently unmapped — see
    # soccer_first_to_score_rule in polymarket.py.
    FIRST_TEAM_TO_SCORE     = ("first_team_to_score",   Scope.GAME,   Shape.THREE_WAY)
    # Soccer "Exact Score" — the single biggest dropped soccer form
    # (~2,284 rows, 27% of poly soccer per wave-rescue-probe-findings.md).
    # One row per fixture, single-affirmative like FIRST_TEAM_TO_SCORE, but
    # its own Shape (CORRECT_SCORE) since none of THREE_WAY/OVER_UNDER/etc.
    # can carry a discrete scoreline pair. See soccer_exact_score_rule in
    # polymarket.py and the CORRECT_SCORE branches of both exchanges'
    # build_rows.
    CORRECT_SCORE           = ("correct_score",         Scope.GAME,   Shape.CORRECT_SCORE)
    # Soccer 1st-half exact score (Optic 1st_half_correct_score); same row
    # shape as CORRECT_SCORE.
    FIRST_HALF_CORRECT_SCORE = ("1h_correct_score",     Scope.GAME,   Shape.CORRECT_SCORE)
    # Soccer both-teams-to-score: one yes/no question per game, the
    # first game-scoped use of Shape.YES_NO (previously only player
    # DD/TD).  Rows key as entity=None, line=None, side=yes/no.
    BTTS                    = ("btts",                  Scope.GAME,   Shape.YES_NO)
    FIRST_HALF_BTTS         = ("1h_btts",               Scope.GAME,   Shape.YES_NO)
    SECOND_HALF_BTTS        = ("2h_btts",               Scope.GAME,   Shape.YES_NO)
    # Hockey both teams to score in regulation (Optic
    # both_teams_to_score_reg_time; DKEX BTMSC/GNO).
    BTTS_REG_TIME           = ("btts_reg_time",         Scope.GAME,   Shape.YES_NO)
    # 2nd-half handicap (soccer 2nd_half_asian_handicap, football
    # 2nd_half_point_spread).
    SECOND_HALF_POINT_SPREAD = ("2h_point_spread",      Scope.GAME,   Shape.SPREAD)
    # Soccer first team to score within one half (Optic
    # Nth_half_first_team_to_score).
    FIRST_HALF_FIRST_TEAM_TO_SCORE = (
        "1h_first_team_to_score", Scope.GAME, Shape.THREE_WAY,
    )
    SECOND_HALF_FIRST_TEAM_TO_SCORE = (
        "2h_first_team_to_score", Scope.GAME, Shape.THREE_WAY,
    )
    # Soccer combined-corners ladder ("N+ corners" = over N−0.5).
    # Kalshi settles corners ET-INCLUSIVE ("entire game (regulation,
    # stoppage and any extra time periods)"), unlike the goals-based
    # game totals — see the knockout caveat in world_cup.py.
    TOTAL_CORNERS           = ("total_corners",         Scope.GAME,   Shape.TOTAL)
    # Tennis total sets played (Tier 1 of the tennis rescue,
    # wave-tennis-probe-findings.md section B.3/tennis rescue scope). Line is
    # always 2.5 on tour-level best-of-3 tennis (Optic's own `total_sets`
    # market_id constant); poly's outcome_label bakes the line in
    # ("Over 2.5"/"Under 2.5") — see the build_rows OVER_UNDER startswith fix
    # (GOTCHA-1) in polymarket.py.
    TOTAL_SETS              = ("total_sets",            Scope.GAME,   Shape.TOTAL)
    # Tennis rescue Tier 2 (wave-tennis-probe-findings.md section C, task TN3)
    # -- the four SURNAME-only poly forms. All reuse existing Shapes; the
    # surname-vs-full-name matching is handled by ParsedMarket.name_granularity
    # (task TN2), not by anything Shape-specific here.
    MATCH_TOTAL_GAMES       = ("match_total_games",     Scope.GAME,   Shape.TOTAL)
    FIRST_SET_TOTAL_GAMES   = ("1st_set_total_games",   Scope.GAME,   Shape.TOTAL)
    SECOND_SET_TOTAL_GAMES  = ("2nd_set_total_games",   Scope.GAME,   Shape.TOTAL)
    SET_HANDICAP            = ("set_handicap",          Scope.GAME,   Shape.SPREAD)
    FIRST_SET_WINNER        = ("1st_set_winner",        Scope.GAME,   Shape.MONEYLINE)
    SECOND_SET_WINNER       = ("2nd_set_winner",        Scope.GAME,   Shape.MONEYLINE)
    # UFC/MMA v1 (ufc-probe-findings.md sections B/C; task-u1). Fighter
    # moneyline reuses MarketType.MONEYLINE verbatim (TEAM_LABEL, same as
    # tennis) -- no new constant for it. These 3 are the non-fighter GAME-scope
    # forms: poly names ZERO fighters in the question, so their fixture
    # resolves via pipeline.py's Phase-B slug-key (seeded by the fight's own
    # MONEYLINE market, which names both fighters and resolves in Phase A).
    # Total rounds: exact analog of tennis's TOTAL_SETS (Shape.TOTAL, GAME).
    TOTAL_ROUNDS            = ("total_rounds",          Scope.GAME,   Shape.TOTAL)
    # "Fight to Go the Distance?" -- genuine Yes/No pair, same shape as BTTS.
    FIGHT_GOES_DISTANCE     = ("fight_goes_distance",    Scope.GAME,   Shape.YES_NO)
    # Optic to_start_round_N: Yes = round N's opening bell sounds. Genuine
    # Yes/No pair; Polymarket US "Fight ends before Round N begins" is its
    # No.
    TO_START_ROUND_2        = ("to_start_round_2",       Scope.GAME,   Shape.YES_NO)
    TO_START_ROUND_3        = ("to_start_round_3",       Scope.GAME,   Shape.YES_NO)
    TO_START_ROUND_4        = ("to_start_round_4",       Scope.GAME,   Shape.YES_NO)
    TO_START_ROUND_5        = ("to_start_round_5",       Scope.GAME,   Shape.YES_NO)
    # "Will the fight be won by KO or TKO?" -- genuine Yes/No pair (optic
    # win_by_ko_tko), same shape as BTTS. Distinct from the deferred
    # FIGHTER_WIN_BY_KOTKO (Scope.TEAM, not built in v1 -- no clean optic
    # target without a free-text name-suffix bucketer; see probe section C).
    GAME_WIN_BY_KOTKO       = ("game_win_by_kotko",      Scope.GAME,   Shape.YES_NO)
    # Esports series sub-markets. A LoL/CS2/Dota2 fixture is a best-of-N
    # SERIES, so alongside the series moneyline Optic prices two series-level
    # derivatives, both league-independent (identical market_ids across
    # league_of_legends / cs2 / dota_2):
    #   map_handicap -- selection=team, points=+-1.5, selection_line empty.
    #     Byte-identical row shape to soccer's asian_handicap, hence
    #     Shape.SPREAD. Priced by Pinnacle/Stake/Betano/Betsson/Unibet and
    #     NOT by Polymarket, which is exactly why poly's own "Game Handicap"
    #     legs could never map off Optic's Polymarket book.
    #   total_maps -- selection empty, selection_line=over/under, points=N.5.
    #     Same shape as tennis TOTAL_SETS, hence Shape.TOTAL.
    # Named for Optic's market_ids; poly calls the same two markets "Game
    # Handicap"/"Map Handicap" and "Games Total"/"Maps Total" depending on
    # the title, which esports_map_handicap_rule / esports_total_maps_rule
    # in polymarket.py both accept.
    MAP_HANDICAP            = ("map_handicap",           Scope.GAME,   Shape.SPREAD)
    TOTAL_MAPS              = ("total_maps",             Scope.GAME,   Shape.TOTAL)
    # Esports single-map winner (Optic Nth_map_moneyline).
    MAP_1_WINNER = ("map_1_winner",              Scope.GAME,   Shape.MONEYLINE)
    MAP_2_WINNER = ("map_2_winner",              Scope.GAME,   Shape.MONEYLINE)
    MAP_3_WINNER = ("map_3_winner",              Scope.GAME,   Shape.MONEYLINE)
    MAP_4_WINNER = ("map_4_winner",              Scope.GAME,   Shape.MONEYLINE)
    MAP_5_WINNER = ("map_5_winner",              Scope.GAME,   Shape.MONEYLINE)
    # Esports per-map sub-markets (Optic Nth_map_round_handicap /
    # Nth_map_total_rounds for CS2/Valorant, Nth_map_team_first_blood for
    # LoL/Dota 2). First blood is 2-way: one team always draws it.
    MAP_1_ROUND_HANDICAP = ("map_1_round_handicap", Scope.GAME, Shape.SPREAD)
    MAP_2_ROUND_HANDICAP = ("map_2_round_handicap", Scope.GAME, Shape.SPREAD)
    MAP_3_ROUND_HANDICAP = ("map_3_round_handicap", Scope.GAME, Shape.SPREAD)
    MAP_1_TOTAL_ROUNDS = ("map_1_total_rounds",     Scope.GAME,   Shape.TOTAL)
    MAP_2_TOTAL_ROUNDS = ("map_2_total_rounds",     Scope.GAME,   Shape.TOTAL)
    MAP_3_TOTAL_ROUNDS = ("map_3_total_rounds",     Scope.GAME,   Shape.TOTAL)
    MAP_1_FIRST_BLOOD = ("map_1_first_blood",       Scope.GAME,   Shape.MONEYLINE)
    MAP_2_FIRST_BLOOD = ("map_2_first_blood",       Scope.GAME,   Shape.MONEYLINE)
    MAP_3_FIRST_BLOOD = ("map_3_first_blood",       Scope.GAME,   Shape.MONEYLINE)
    MAP_4_FIRST_BLOOD = ("map_4_first_blood",       Scope.GAME,   Shape.MONEYLINE)
    MAP_5_FIRST_BLOOD = ("map_5_first_blood",       Scope.GAME,   Shape.MONEYLINE)
    # "Is the map's total kill count odd?" Yes = Optic Odd, No = Optic Even
    # (Nth_map_total_kills_odd_even) — a true binary.
    MAP_1_KILLS_ODD = ("map_1_kills_odd",           Scope.GAME,   Shape.YES_NO)
    MAP_2_KILLS_ODD = ("map_2_kills_odd",           Scope.GAME,   Shape.YES_NO)
    MAP_3_KILLS_ODD = ("map_3_kills_odd",           Scope.GAME,   Shape.YES_NO)
    MAP_4_KILLS_ODD = ("map_4_kills_odd",           Scope.GAME,   Shape.YES_NO)
    MAP_5_KILLS_ODD = ("map_5_kills_odd",           Scope.GAME,   Shape.YES_NO)

    # Team-scoped — one per team per game
    TEAM_TOTAL              = ("team_total",            Scope.TEAM,   Shape.TOTAL)
    TEAM_TOTAL_TOUCHDOWNS   = ("team_total_touchdowns", Scope.TEAM,   Shape.TOTAL)
    TEAM_TOTAL_FIELD_GOALS  = ("team_total_field_goals", Scope.TEAM,  Shape.TOTAL)
    TEAM_TOTAL_SACKS        = ("team_total_sacks",      Scope.TEAM,   Shape.TOTAL)
    TEAM_TOTAL_FIRST_DOWNS  = ("team_total_first_downs", Scope.TEAM,  Shape.TOTAL)
    TEAM_TOTAL_RUSHING_YARDS = ("team_total_rushing_yards", Scope.TEAM, Shape.TOTAL)
    TEAM_TOTAL_RUSHING_TOUCHDOWNS = (
        "team_total_rushing_touchdowns", Scope.TEAM, Shape.TOTAL,
    )
    TEAM_TOTAL_PASSING_TOUCHDOWNS = (
        "team_total_passing_touchdowns", Scope.TEAM, Shape.TOTAL,
    )
    WINNING_MARGIN_5WAY     = ("winning_margin_5-way",  Scope.TEAM,   Shape.YES_NO)
    WINNING_MARGIN          = ("winning_margin",        Scope.TEAM,   Shape.YES_NO)  # band = grouping_key
    TEAM_TOTAL_RECEPTIONS   = ("team_total_receptions", Scope.TEAM,   Shape.TOTAL)
    TEAM_TOTAL_RECEIVING_YARDS = ("team_total_receiving_yards", Scope.TEAM, Shape.TOTAL)
    TEAM_TOTAL_RECEIVING_TOUCHDOWNS = ("team_total_receiving_touchdowns", Scope.TEAM, Shape.TOTAL)
    TEAM_TOTAL_PASSING_YARDS = ("team_total_passing_yards", Scope.TEAM, Shape.TOTAL)
    # Total offensive yards (Optic team_total_yards).
    TEAM_TOTAL_YARDS        = ("team_total_yards",      Scope.TEAM,   Shape.TOTAL)
    # Scrimmage yards = rushing + receiving (Optic
    # team_total_rushing_+_receiving_yards).
    TEAM_TOTAL_SCRIMMAGE_YARDS = ("team_total_rushing_+_receiving_yards", Scope.TEAM, Shape.TOTAL)
    # Soccer 1st/2nd-half team totals — same shape as TEAM_TOTAL, half-scoped.
    FIRST_HALF_TEAM_TOTAL   = ("1h_team_total",         Scope.TEAM,   Shape.TOTAL)
    SECOND_HALF_TEAM_TOTAL  = ("2h_team_total",         Scope.TEAM,   Shape.TOTAL)
    # Hockey 1st-period team total (Optic 1st_period_team_total).
    FIRST_PERIOD_TEAM_TOTAL = ("p1_team_total",         Scope.TEAM,   Shape.TOTAL)
    SECOND_PERIOD_TEAM_TOTAL = ("p2_team_total",        Scope.TEAM,   Shape.TOTAL)
    THIRD_PERIOD_TEAM_TOTAL = ("p3_team_total",         Scope.TEAM,   Shape.TOTAL)
    TEAM_TOTAL_CORNERS      = ("team_total_corners",    Scope.TEAM,   Shape.TOTAL)
    # Soccer knockout "to advance": one yes/no per team (entity=team, line=None).
    # PROGRESS probability (a 90' tie advances via ET/pens): Optic to_advance,
    # NOT the regular-time 3-way ML — see world_cup.py.
    TO_ADVANCE              = ("to_advance",            Scope.TEAM,   Shape.YES_NO)

    # Player-scoped — one per player per game
    PLAYER_POINTS           = ("player_points",         Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_ASSISTS          = ("player_assists",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_REBOUNDS         = ("player_rebounds",       Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_THREES           = ("player_threes",         Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_BLOCKS           = ("player_blocks",         Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_STEALS           = ("player_steals",         Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_DOUBLE_DOUBLE    = ("player_double_double",  Scope.PLAYER, Shape.YES_NO)
    PLAYER_TRIPLE_DOUBLE    = ("player_triple_double",  Scope.PLAYER, Shape.YES_NO)
    PLAYER_STEALS_BLOCKS    = ("player_steals_blocks",  Scope.PLAYER, Shape.OVER_UNDER)
    # One player scores the game's first basket (Optic first_basket; one
    # yes/no question per player, like FIRST_GOAL_SCORER).
    FIRST_BASKET            = ("first_basket",          Scope.PLAYER, Shape.YES_NO)
    PLAYER_PTS_AST          = ("player_pts_ast",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PTS_REB          = ("player_pts_reb",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PTS_REB_AST      = ("player_pts_reb_ast",    Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_REB_AST          = ("player_reb_ast",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_TURNOVERS        = ("player_turnovers",      Scope.PLAYER, Shape.OVER_UNDER)
    # Baseball player props.
    # Batter-side counterparts of the pitcher markets below (Optic
    # player_runs / player_batting_strikeouts / player_batting_walks).
    PLAYER_RUNS             = ("player_runs",           Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_BATTING_STRIKEOUTS = ("player_batting_strikeouts", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_BATTING_WALKS    = ("player_batting_walks",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_HOME_RUNS        = ("player_home_runs",      Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_STRIKEOUTS       = ("player_strikeouts",     Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_HITS             = ("player_hits",           Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_BASES            = ("player_bases",          Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_HITS_RUNS_RBIS   = ("player_hits_runs_rbis", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RBIS             = ("player_rbis",           Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_STOLEN_BASES     = ("player_stolen_bases",   Scope.PLAYER, Shape.OVER_UNDER)
    # Pitcher outs recorded (Optic player_outs; Kalshi KXMLBOUTS).
    PLAYER_OUTS             = ("player_outs",           Scope.PLAYER, Shape.OVER_UNDER)
    # Pitcher allowed stats (Optic player_hits_allowed / player_earned_runs /
    # player_walks, walks allowed; batting walks is separate).
    PLAYER_HITS_ALLOWED     = ("player_hits_allowed",   Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_EARNED_RUNS      = ("player_earned_runs",    Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_WALKS_ALLOWED    = ("player_walks_allowed",  Scope.PLAYER, Shape.OVER_UNDER)
    # NFL player props (Optic market_id player_passing_yards; Kalshi PASSYDS).
    PLAYER_PASSING_YARDS    = ("player_passing_yards",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_INTERCEPTIONS    = ("player_interceptions",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_TOUCHDOWNS = ("player_passing_touchdowns", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RECEIVING_YARDS  = ("player_receiving_yards", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RECEPTIONS       = ("player_receptions",     Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RUSHING_YARDS    = ("player_rushing_yards",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RUSHING_ATTEMPTS = ("player_rushing_attempts", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_ATTEMPTS = ("player_passing_attempts", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_COMPLETIONS = ("player_passing_completions", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_LONGEST_RECEPTION = ("player_longest_reception", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_LONGEST_RUSH     = ("player_longest_rush",   Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_LONGEST_PASSING_COMPLETION = (
        "player_longest_passing_completion", Scope.PLAYER, Shape.OVER_UNDER,
    )
    PLAYER_RUSHING_RECEIVING_YARDS = (
        "player_rushing_+_receiving_yards", Scope.PLAYER, Shape.OVER_UNDER,
    )
    PLAYER_PASSING_RUSHING_YARDS = (
        "player_passing_+_rushing_yards", Scope.PLAYER, Shape.OVER_UNDER,
    )
    # Defensive / kicker props (Optic player_tackles_+_assists /
    # player_kicking_points; Novig TACKLES_ASSISTS / KICKING_POINTS).
    PLAYER_TACKLES_ASSISTS  = ("player_tackles_+_assists", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_KICKING_POINTS   = ("player_kicking_points", Scope.PLAYER, Shape.OVER_UNDER)
    # Optic player_sacks / player_field_goals_made / last_touchdown_scorer (Novig, DKEX too).
    PLAYER_SACKS            = ("player_sacks",          Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_TACKLES          = ("player_tackles",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_FIELD_GOALS_MADE = ("player_field_goals_made", Scope.PLAYER, Shape.OVER_UNDER)
    LAST_TOUCHDOWN_SCORER   = ("last_touchdown_scorer", Scope.PLAYER, Shape.YES_NO)
    PLAYER_TOUCHDOWNS       = ("player_touchdowns",     Scope.PLAYER, Shape.OVER_UNDER)
    # Kalshi "(Protected)" / Novig *_PROTECTED props: base shape, settled with insurance.
    PLAYER_POINTS_INSURANCE = ("player_points_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_REBOUNDS_INSURANCE = ("player_rebounds_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_ASSISTS_INSURANCE = ("player_assists_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_THREES_INSURANCE = ("player_threes_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_YARDS_INSURANCE = ("player_passing_yards_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_TOUCHDOWNS_INSURANCE = ("player_passing_touchdowns_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RECEIVING_YARDS_INSURANCE = ("player_receiving_yards_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RECEPTIONS_INSURANCE = ("player_receptions_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RUSHING_YARDS_INSURANCE = ("player_rushing_yards_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_TOUCHDOWNS_INSURANCE = ("player_touchdowns_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_ATTEMPTS_INSURANCE = ("player_passing_attempts_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_COMPLETIONS_INSURANCE = (
        "player_passing_completions_insurance", Scope.PLAYER, Shape.OVER_UNDER,
    )
    PLAYER_LONGEST_PASSING_COMPLETION_INSURANCE = (
        "player_longest_passing_completion_insurance", Scope.PLAYER, Shape.OVER_UNDER,
    )
    PLAYER_INTERCEPTIONS_INSURANCE = ("player_interceptions_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RUSHING_ATTEMPTS_INSURANCE = ("player_rushing_attempts_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_LONGEST_RUSH_INSURANCE = ("player_longest_rush_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_LONGEST_RECEPTION_INSURANCE = ("player_longest_reception_insurance", Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_PASSING_RUSHING_YARDS_INSURANCE = (
        "player_passing_+_rushing_yards_insurance", Scope.PLAYER, Shape.OVER_UNDER,
    )
    PLAYER_RUSHING_RECEIVING_YARDS_INSURANCE = (
        "player_rushing_+_receiving_yards_insurance", Scope.PLAYER, Shape.OVER_UNDER,
    )
    FIRST_TOUCHDOWN_SCORER  = ("first_touchdown_scorer", Scope.PLAYER, Shape.YES_NO)
    TEAM_FIRST_TOUCHDOWN_SCORER = ("team_first_touchdown_scorer", Scope.PLAYER, Shape.YES_NO)
    # Soccer goals ladder ("N+ goals" = over N−0.5); 0.5 is ANYTIME_GOAL_SCORER.
    PLAYER_GOALS            = ("player_goals",          Scope.PLAYER, Shape.OVER_UNDER)
    # Hockey skater props (Optic player_shots_on_goal / player_power_play_points;
    # player_goals/assists/points reuse the types around -- key carries the league).
    PLAYER_SHOTS_ON_GOAL    = ("player_shots_on_goal",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_POWER_PLAY_POINTS = ("player_power_play_points", Scope.PLAYER, Shape.OVER_UNDER)
    # Soccer FIFA player props (crypto.com threshold Yes/No contracts).
    PLAYER_SHOTS            = ("player_shots",            Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_SHOTS_ON_TARGET  = ("player_shots_on_target",  Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_SAVES            = ("player_saves",            Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_FOULS            = ("player_fouls",            Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_FOULS_WON        = ("player_fouls_won",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_CARDS            = ("player_cards",            Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_RED_CARDS        = ("player_red_cards",        Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_GOALS_OR_ASSIST  = ("player_goals_or_assist",  Scope.PLAYER, Shape.OVER_UNDER)
    # First goalscorer: one yes/no per player (crypto: one contract each).
    FIRST_GOAL_SCORER       = ("first_goal_scorer",       Scope.PLAYER, Shape.YES_NO)
    # Soccer anytime scorer: PLAYER_GOALS over 0.5 (mappers/anytime_scorer.py).
    ANYTIME_GOAL_SCORER     = ("anytime_goal_scorer",     Scope.PLAYER, Shape.YES_NO)
    # Affirmative per player; a tie dead-heats.
    MOST_PASSING_YARDS      = ("most_passing_yards",      Scope.PLAYER, Shape.YES_NO)
    # Tennis games won by ONE player over the match (Optic player_games_won,
    # Novig PLAYER_GAMES_WON); same row shape as any player over/under.  The
    # set-scoped form (Optic 1st_set_player_games_won) stays unmapped.
    PLAYER_GAMES_WON        = ("player_games_won",         Scope.PLAYER, Shape.OVER_UNDER)

    # MMA / UFC — fight props.  METHOD_OF_VICTORY is fighter-scoped (entity=
    # fighter, method in grouping_key); METHOD_OF_FINISH / ROUND_BETTING are
    # fight-scoped with method/round in grouping_key; side=yes on Optic.
    METHOD_OF_VICTORY       = ("method_of_victory",       Scope.TEAM,   Shape.YES_NO)
    METHOD_OF_FINISH        = ("method_of_finish",        Scope.GAME,   Shape.YES_NO)
    ROUND_BETTING           = ("round_betting",           Scope.GAME,   Shape.YES_NO)
    GO_THE_DISTANCE         = ("go_the_distance",         Scope.GAME,   Shape.YES_NO)
    # Fighter wins specifically by KO/submission/DQ (Optic team-scoped yes/no).
    WIN_BY_KO_SUB_DQ        = ("win_by_ko_sub_dq",        Scope.TEAM,   Shape.YES_NO)

    # Player yes/no with line: an OVER_UNDER stat as a PX sup_moneyline binary (own type).
    PLAYER_ASSISTS_YN       = ("player_assists_yn",       Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_BLOCKS_YN        = ("player_blocks_yn",        Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_GOALS_YN         = ("player_goals_yn",         Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_POINTS_YN        = ("player_points_yn",        Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_PTS_AST_YN       = ("player_pts_ast_yn",       Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_PTS_REB_YN       = ("player_pts_reb_yn",       Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_PTS_REB_AST_YN   = ("player_pts_reb_ast_yn",   Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_REB_AST_YN       = ("player_reb_ast_yn",       Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_REBOUNDS_YN      = ("player_rebounds_yn",      Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_STEALS_YN        = ("player_steals_yn",        Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_STEALS_BLOCKS_YN = ("player_steals_blocks_yn", Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_THREES_YN        = ("player_threes_yn",        Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_TURNOVERS_YN     = ("player_turnovers_yn",     Scope.PLAYER, Shape.YES_NO_LINE)
    PLAYER_TOUCHDOWNS_YN    = ("player_touchdowns_yn",    Scope.PLAYER, Shape.YES_NO_LINE)

    # Player-scoped — head-to-head matchups
    # H2H markets require grouping_key in the merge key (see add-grouping-key.md).
    PLAYER_ASSISTS_H2H      = ("player_assists_h2h_moneyline", Scope.PLAYER, Shape.H2H)
