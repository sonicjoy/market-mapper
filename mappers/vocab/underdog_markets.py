"""Underdog UDX market crosswalk, keyed on the venue's typed Optic market id.

Every UDX contract carries ``external_ids.optic_odds.market_id``, the Optic
market it settles like (``point_spread``, ``2nd_quarter_total_points``,
``player_made_threes``). That typed field names the market and its period, so
nothing here reads a ticker. The table is per sport: Underdog's ``moneyline``
is a regulation-time 3-way in soccer and a 2-way win elsewhere.

An id that is absent maps nothing. The id names the market a contract is
priced from, which is not always the one it equals (``UDXUFCEXACTTOTAL``
"concludes during Round 2" carries ``to_start_round_2``, so UFC round counts
stay unmapped). UFC fight props, overtime, go-the-distance and MLB inning
lines also need the sentence to state that contract
(``mappers.exchanges.underdog``). MLB inning lines say "during the first 5
innings", so ``1st_half_*`` is the first five; ``1st_7_innings_*`` and the
1st-3 run line / total have no canonical type.
"""

from __future__ import annotations

from mappers.market_types import MarketType
from mappers.sport import Sport

_PERIODS = {
    "1st_half": "FIRST_HALF", "2nd_half": "SECOND_HALF",
    "1st_quarter": "FIRST_QUARTER", "2nd_quarter": "SECOND_QUARTER",
    "3rd_quarter": "THIRD_QUARTER", "4th_quarter": "FOURTH_QUARTER",
}


def _football_periods() -> dict[str, MarketType]:
    """Half and quarter game lines. A tie is NO on every win market, so 3-way."""
    out: dict[str, MarketType] = {}
    for prefix, name in _PERIODS.items():
        out[f"{prefix}_moneyline_3-way"] = MarketType[f"{name}_WINNER_3WAY"]
        out[f"{prefix}_point_spread"] = MarketType[f"{name}_POINT_SPREAD"]
        out[f"{prefix}_total_points"] = MarketType[f"{name}_TOTAL"]
    return out


_FOOTBALL: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "point_spread": MarketType.POINT_SPREAD,
    "total_points": MarketType.GAME_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    "1st_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    **_football_periods(),
    "player_passing_yards": MarketType.PLAYER_PASSING_YARDS,
    "player_passing_touchdowns": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "player_passing_attempts": MarketType.PLAYER_PASSING_ATTEMPTS,
    "player_passing_completions": MarketType.PLAYER_PASSING_COMPLETIONS,
    "player_interceptions": MarketType.PLAYER_INTERCEPTIONS,
    "player_longest_passing_completion": MarketType.PLAYER_LONGEST_PASSING_COMPLETION,
    "player_receiving_yards": MarketType.PLAYER_RECEIVING_YARDS,
    "player_receptions": MarketType.PLAYER_RECEPTIONS,
    "player_longest_reception": MarketType.PLAYER_LONGEST_RECEPTION,
    "player_rushing_yards": MarketType.PLAYER_RUSHING_YARDS,
    "player_rushing_attempts": MarketType.PLAYER_RUSHING_ATTEMPTS,
    "player_longest_rush": MarketType.PLAYER_LONGEST_RUSH,
    "player_field_goals_made": MarketType.PLAYER_FIELD_GOALS_MADE,
    "player_sacks": MarketType.PLAYER_SACKS,
    "anytime_touchdown_scorer": MarketType.PLAYER_TOUCHDOWNS,
    "first_touchdown_scorer": MarketType.FIRST_TOUCHDOWN_SCORER,
    # The TD ladder (UDXNFLTD 1.5 / 2.5, "during the full game (including overtime)") and the combined-yards and
    # kicking props map only through ``underdog_player_props`` (whole sentence + venue player id).
    "player_touchdowns": MarketType.PLAYER_TOUCHDOWNS,
    "player_passing_+_rushing_yards": MarketType.PLAYER_PASSING_RUSHING_YARDS,
    "player_rushing_+_receiving_yards": MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    "player_kicking_points": MarketType.PLAYER_KICKING_POINTS,
    "will_there_be_overtime": MarketType.WILL_THERE_BE_OVERTIME,
}

_BASEBALL: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "run_line": MarketType.POINT_SPREAD,
    "total_runs": MarketType.GAME_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    "1st_inning_total_runs": MarketType.FIRST_INNING_TOTAL,
    "1st_half_moneyline_3-way": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
    "1st_half_run_line": MarketType.FIRST_FIVE_POINT_SPREAD,
    "1st_half_total_runs": MarketType.FIRST_FIVE_TOTAL,
    "1st_3_innings_moneyline_3-way": MarketType.FIRST_THREE_MONEYLINE_3WAY,
    "player_hits": MarketType.PLAYER_HITS,
    "player_strikeouts": MarketType.PLAYER_STRIKEOUTS,
    "player_hits_+_runs_+_rbis": MarketType.PLAYER_HITS_RUNS_RBIS,
    "player_home_runs": MarketType.PLAYER_HOME_RUNS,
    "player_bases": MarketType.PLAYER_BASES,
    "player_rbis": MarketType.PLAYER_RBIS,
    "player_stolen_bases": MarketType.PLAYER_STOLEN_BASES,
    "player_outs": MarketType.PLAYER_OUTS,
    "player_hits_allowed": MarketType.PLAYER_HITS_ALLOWED,
    "player_earned_runs": MarketType.PLAYER_EARNED_RUNS,
    "player_walks": MarketType.PLAYER_WALKS_ALLOWED,
}

# Basketball periods. The period winners (UDXNBAGAMEWIN1H, 1Q-4Q, listed
# 2026-10-22) are team / TIE legs, "beat ... by above 0.5 points" / "by exactly
# 0 points" in the period, as Optic's 3-way. The filings (NBASPREAD,
# NBAENTITYOUTCOME) confine a named period to itself: "a quarter or half
# (including the fourth quarter and the second half) does not include any
# officially designated overtime period unless overtime is expressly specified",
# as Optic grades its 4Q and 1H team total. Not mapped: the 2H winner, which
# says "second half and overtime" while UDX tags Optic's regulation-only
# 2nd_half_moneyline_3-way.
_BASKETBALL: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "point_spread": MarketType.POINT_SPREAD,
    "total_points": MarketType.GAME_TOTAL,
    "1st_half_point_spread": MarketType.FIRST_HALF_POINT_SPREAD,
    "1st_half_total_points": MarketType.FIRST_HALF_TOTAL,
    # UDXNBATEAMTOTAL1H: "points scored during the first half", the named team's over.
    "1st_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    # UDXNBATOTAL1Q / UDXNBASPREAD1Q: "points during the first quarter" (2026-11-05),
    # Optic prices the quarter since 2026-11 (Kalshi / SX map the same ids).
    "1st_quarter_total_points": MarketType.FIRST_QUARTER_TOTAL,
    "1st_quarter_point_spread": MarketType.FIRST_QUARTER_POINT_SPREAD,
    "1st_half_moneyline_3-way": MarketType.FIRST_HALF_WINNER_3WAY,
    "1st_quarter_moneyline_3-way": MarketType.FIRST_QUARTER_WINNER_3WAY,
    "2nd_quarter_moneyline_3-way": MarketType.SECOND_QUARTER_WINNER_3WAY,
    "3rd_quarter_moneyline_3-way": MarketType.THIRD_QUARTER_WINNER_3WAY,
    "4th_quarter_moneyline_3-way": MarketType.FOURTH_QUARTER_WINNER_3WAY,
    "player_points": MarketType.PLAYER_POINTS,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_rebounds": MarketType.PLAYER_REBOUNDS,
    "player_made_threes": MarketType.PLAYER_THREES,
    # Full game incl. overtime, as Optic's. UDXNBAOVERTIME and UDXNCAAMBBOVERTIME
    # ("at least 1 jump balls ... during overtime only") stay unmapped: the filing
    # does not say how a game without overtime settles.
    "team_total": MarketType.TEAM_TOTAL,
    "player_points_+_rebounds_+_assists": MarketType.PLAYER_PTS_REB_AST,
    "player_steals": MarketType.PLAYER_STEALS,
    "player_blocks": MarketType.PLAYER_BLOCKS,
    # "above 1.5 steals AND blocks": the sum, as PRA's "points AND rebounds AND assists".
    "player_steals_+_blocks": MarketType.PLAYER_STEALS_BLOCKS,
    # "over 0.5 double-doubles": Optic's yes / no.
    "player_double_double": MarketType.PLAYER_DOUBLE_DOUBLE,
    "player_triple_double": MarketType.PLAYER_TRIPLE_DOUBLE,
    # UDXNBARACE10/20, one contract per team: "the first attainment of at least N
    # points ... including officially designated overtime periods". RACE30 stays
    # unmapped until Optic race_to_30_points is fetched (OPTIC_NBA_RACE_TO_30).
    "race_to_10_points": MarketType.RACE_TO_POINTS,
    "race_to_20_points": MarketType.RACE_TO_POINTS,
    # UDXNBAMOV: "beat ... by between 11 and 20 points" / "by at least 21
    # points", full game incl. overtime (the filing's rules). Yes only.
    "winning_margin": MarketType.WINNING_MARGIN,
}

# NHL game lines and team goals settle on the full game incl. overtime and the
# shootout, as Optic's hockey moneyline / puck_line / total_goals / team_total
# do. Period totals end at the horn. Period winners and period puck lines have
# no canonical type yet, so they stay unmapped.
#
# Skater props settle "during the entire game including overtime but excluding
# the shootout", as Optic's hockey props do (``hockey_markets``). They map only
# through ``underdog_player_props``: the whole sentence must be that contract, and
# the venue's Optic player id must name the sentence's player on the fixture
# (``PLAYER_ID_MARKETS_BY_SPORT``). ``first_goal_scorer`` (UDXNHLFGS) is "at
# least 0.5 first goal" on the same basis, YES only: Optic lists one selection
# per player and no "no goalscorer" one (7 books, 2026-10-29).
# ``player_saves`` (UDXNHLGOALIESAVES) stays unmapped: no RFQ has asked for it.
_HOCKEY: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "puck_line": MarketType.POINT_SPREAD,
    "total_goals": MarketType.GAME_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    "1st_period_total_goals": MarketType.FIRST_PERIOD_TOTAL,
    "2nd_period_total_goals": MarketType.SECOND_PERIOD_TOTAL,
    "3rd_period_total_goals": MarketType.THIRD_PERIOD_TOTAL,
    "will_there_be_overtime": MarketType.WILL_THERE_BE_OVERTIME,
    "first_goal_scorer": MarketType.FIRST_GOAL_SCORER,
    "player_goals": MarketType.PLAYER_GOALS,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_points": MarketType.PLAYER_POINTS,
    "player_shots_on_goal": MarketType.PLAYER_SHOTS_ON_GOAL,
}

# Soccer settles on regulation time: a draw is NO on a win contract.
_SOCCER: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE_3WAY,
    "asian_handicap": MarketType.POINT_SPREAD,
    "total_goals": MarketType.GAME_TOTAL,
    "both_teams_to_score": MarketType.BTTS,
    "1st_half_moneyline": MarketType.FIRST_HALF_WINNER_3WAY,
    "1st_half_asian_handicap": MarketType.FIRST_HALF_POINT_SPREAD,
    "1st_half_total_goals": MarketType.FIRST_HALF_TOTAL,
    # UDXEPLBTTS1H / TEAMTOTAL / CORNERS / TCORNERS (2026-10-23): first half or
    # regulation time ("corner kicks taken"), as Optic grades them; the pass
    # also requires the sentence to state that basis (underdog_pass).
    "1st_half_both_teams_to_score": MarketType.FIRST_HALF_BTTS,
    "team_total": MarketType.TEAM_TOTAL,
    "total_corners": MarketType.TOTAL_CORNERS,
    "team_total_corners": MarketType.TEAM_TOTAL_CORNERS,
    # UDXBRASILASCORE / SERIEASCORE / LIGAMXSCORE / MLSSCORE / LIGUE1SCORE
    # (2026-10-29): the 90-minute scoreline, as Optic's correct_score; YES only,
    # and the sentence (Brazil: the rules) must say "the entire game excluding
    # extra time".
    "correct_score": MarketType.CORRECT_SCORE,
}

# ``game_spread`` is the games handicap ("wins at least 2.5 more games");
# ``correct_score`` is "<player> wins ... by a final set score of 2-1".
_TENNIS: dict[str, MarketType] = {
    "correct_score": MarketType.CORRECT_SCORE,
    "moneyline": MarketType.MONEYLINE,
    "total_games": MarketType.MATCH_TOTAL_GAMES,
    "game_spread": MarketType.POINT_SPREAD,
}

# Fight props key on the sentence too: method and round go in grouping_key
# the way Optic's do (``mappers.fight_props``).
_COMBAT: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "method_of_victory": MarketType.METHOD_OF_VICTORY,
    "round_betting": MarketType.ROUND_BETTING,
    "go_the_distance": MarketType.FIGHT_GOES_DISTANCE,
}

# Esports settle on the whole series: the winner of the series, and the count
# of completed maps (UDX LOLGAMEWIN / CS2GAMEWIN / LOLTOTAL / CS2TOTAL filings,
# 2026-09-29), as Optic's series moneyline and total_maps do. A drawn series
# (best-of-two) pays each team $0.50 when no Draw ticker is listed; the Kalshi
# complement treats esports as no-draw the same way.
_ESPORTS: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total_maps": MarketType.TOTAL_MAPS,
}

MARKETS_BY_SPORT: dict[Sport, dict[str, MarketType]] = {
    Sport.FOOTBALL: _FOOTBALL,
    Sport.BASEBALL: _BASEBALL,
    Sport.BASKETBALL: _BASKETBALL,
    Sport.HOCKEY: _HOCKEY,
    Sport.SOCCER: _SOCCER,
    Sport.TENNIS: _TENNIS,
    Sport.MMA: _COMBAT,
    Sport.ESPORTS: _ESPORTS,
}

#: Tip league slugs whose Underdog mapping is a code decision. The league set
#: is code: a tip ``underdog`` exchange row and tip rules cannot add to or
#: change these (``with_code_underdog``, ``overlay_underdog``).
UNDERDOG_LEAGUE_SLUGS: frozenset[str] = frozenset({
    "nfl", "ncaaf", "mlb", "nba", "wnba", "nhl", "ncaab",
    # NCAAWBB filings: full game = regulation + overtime, as Optic and NCAAMBB.
    "ncaaw",
    "atp", "atp_challenger", "wta", "itf_men", "itf_women", "ufc",
    "lol", "cs2",
    "mls", "liga_mx", "uefa_nations_league", "international_friendlies",
    "brazil_serie_a", "saudi_pro_league", "argentina_primera_nacional",
    "ucl", "europa_league", "epl", "la_liga", "italy_serie_a",
    "england_championship", "england_league_1",
    "conmebol_copa_libertadores", "conmebol_sudamericana",
    "germany_bundesliga", "france_ligue_1", "argentina_primera", "brazil_serie_b",
    "colombia_primera_a", "ecuador_serie_a", "japan_j1_league",
})


#: UDX series never mapped, whatever Optic market id they carry. UDX defines a
#: series as "the ticker text before the first underscore or hyphen"
#: (``RfqStatsSeriesRow``); it is looked up whole, never split. UDX's Optic id
#: names the market a contract is priced from, not one it equals:
#: ``UDXNFLSWPP`` ("wins ... without its win probability falling below 10%
#: over any 1 minute window") carries ``moneyline`` and was stamped as one
#: (420 symbols, 2026-10-10). The rest are season futures and novelties
#: ("a new CBA before ...", "an NBA expansion team before ..."), and
#: ``UDXNCAAMFBOVERTIME``: "at least 1 kickoffs during overtime only", but
#: college overtime has no kickoff, so it is not ``will_there_be_overtime``.
UNDERDOG_BLOCKED_SERIES: frozenset[str] = frozenset({
    "UDXNFLSWPP",
    "UDXMLBCBA",
    "UDXMLBSTART",
    "UDXNBAEXPTEAM",
    "UDXNFLTEAMSALE",
    "UDXNCAAMFBOVERTIME",
})

#: Sentence clauses that make a contract something other than its Optic
#: market, in any series (a new league's SWPP lists before it is blocked).
UNDERDOG_BLOCKED_CLAUSES: tuple[str, ...] = (
    "win probability",
)


#: Optic market ids whose contracts map only when the venue's own Optic
#: ``player_id`` names the sentence's player on the matched fixture, and the
#: sentence is the whole contract (``mappers.exchanges.underdog_player_props``).
PLAYER_ID_MARKETS_BY_SPORT: dict[Sport, frozenset[str]] = {
    Sport.HOCKEY: frozenset({
        "player_goals", "player_assists", "player_points", "player_shots_on_goal",
        "first_goal_scorer",
    }),
    Sport.FOOTBALL: frozenset({
        "player_touchdowns", "player_passing_+_rushing_yards",
        "player_rushing_+_receiving_yards", "player_kicking_points",
    }),
}


def market_types_for_sport(sport: Sport) -> dict[str, MarketType]:
    """Optic market id -> canonical type for one sport; empty when unmapped."""
    return dict(MARKETS_BY_SPORT.get(sport, {}))


def player_id_markets_for_sport(sport: Sport) -> frozenset[str]:
    """Market ids of ``sport`` that need the venue's player id; empty when none."""
    return PLAYER_ID_MARKETS_BY_SPORT.get(sport, frozenset())
