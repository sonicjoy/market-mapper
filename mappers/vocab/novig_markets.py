"""Shared Novig market-type vocabulary, keyed by sport.

Novig's ``market.type`` vocabulary is strikingly consistent across leagues
-- ``MONEY`` / ``SPREAD`` / ``TOTAL`` / ``TEAM_TOTAL`` mean the same thing
in the NFL feed as in the MLS one -- so the crosswalks live here once and
each league module composes the pieces it needs, the same way
``soccer_markets.py`` and ``esports_markets.py`` already work.

Everything below was read off the LIVE feed on 2026-08-14 (10,930 open
markets across ATP, MLB, MLS, NFL, PGA, UFC, WNBA, WTA) rather than from
the docs.  Leagues that were out of season that day (NBA, NHL, CFL, the
European soccer leagues, the three esports) had scheduled events but no
markets attached, so their crosswalks are composed from the shared
vocabulary and are marked UNVERIFIED where that inference is doing real
work; the pipeline prints an "unknown market type" warning the first time
Novig ships something not listed here, which is the signal to revisit.

Judgement calls worth recording, each checked against real payloads:

* **Baseball ``_1H`` is first-five-innings, not a half.**  Novig labels the
  MLB market "SF -0.5 1H", and Optic labels the same market
  ``1st_half_run_line`` -- which ``leagues/mlb.py`` already maps to
  ``FIRST_FIVE_POINT_SPREAD``.  Baseball has no halves, so mapping these to
  ``FIRST_HALF_*`` would key rows that can never merge.
* **Novig's F5 moneyline is 2-way; Optic's is 3-way.**  ``MONEY_1H`` maps
  to the honest ``FIRST_FIVE_MONEYLINE`` (2-way) even though Optic/Kalshi
  price ``FIRST_FIVE_MONEYLINE_3WAY``, so most of these rows will drop as
  "optic didn't price" rather than merge onto a differently-settling key.
* **UFC per-method markets are ``METHOD_OF_VICTORY``, not the bundled
  ``WIN_BY_KO_SUB_DQ``.**  Novig splits ``VICTORY_BY_KO_KTO_OR_DQ`` /
  ``VICTORY_BY_SUBMISSION`` / ``VICTORY_BY_DECISION`` into one Yes/No
  market per method.  ``WIN_BY_KO_SUB_DQ`` bundles knockout + submission +
  DQ into ONE contract and would indeed settle differently -- but
  ``METHOD_OF_VICTORY`` is fighter-scoped with the method in
  ``grouping_key``, which is precisely this shape, and Optic's
  ``method_of_victory`` buckets carry the same three canonical keys. So
  these map like-for-like. (They were ignored until 2026-09-01 on the
  strength of the ``WIN_BY_KO_SUB_DQ`` comparison alone.)
* **Tennis ``SPREAD`` is a GAMES handicap** (observed range -8.5..+9.5),
  distinct from ``SET_SPREAD`` (strictly +/-1.5), and tennis ``TOTAL`` is
  total games (15.5..26.5), not sets.  ``UFC TOTAL`` is rounds (1.5..4.5).
"""

from mappers.exchanges.novig import NovigConfig
from mappers.market_types import MarketType

# === Shared game lines ===

#: The core three every team sport ships.
GAME_LINES: dict[str, MarketType] = {
    "MONEY": MarketType.MONEYLINE,
    "SPREAD": MarketType.POINT_SPREAD,
    "TOTAL": MarketType.GAME_TOTAL,
}

#: Team totals carry ``market.competitor`` (with an Optic team id).
TEAM_TOTALS: dict[str, MarketType] = {
    "TEAM_TOTAL": MarketType.TEAM_TOTAL,
}

#: Real first-half markets — basketball and football only.
HALVES: dict[str, MarketType] = {
    "MONEY_1H": MarketType.FIRST_HALF_MONEYLINE,
    "SPREAD_1H": MarketType.FIRST_HALF_POINT_SPREAD,
    "TOTAL_1H": MarketType.FIRST_HALF_TOTAL,
}

#: Baseball's "1H" is first-five-innings (see module docstring).
BASEBALL_F5: dict[str, MarketType] = {
    "MONEY_1H": MarketType.FIRST_FIVE_MONEYLINE,
    "SPREAD_1H": MarketType.FIRST_FIVE_POINT_SPREAD,
    "TOTAL_1H": MarketType.FIRST_FIVE_TOTAL,
}


# === Basketball ===

BASKETBALL_PROPS: dict[str, MarketType] = {
    "POINTS": MarketType.PLAYER_POINTS,
    "REBOUNDS": MarketType.PLAYER_REBOUNDS,
    "ASSISTS": MarketType.PLAYER_ASSISTS,
    "THREE_POINTERS_MADE": MarketType.PLAYER_THREES,
    "BLOCKS": MarketType.PLAYER_BLOCKS,
    "STEALS": MarketType.PLAYER_STEALS,
    "TURNOVERS": MarketType.PLAYER_TURNOVERS,
    "POINTS_REBOUNDS": MarketType.PLAYER_PTS_REB,
    "POINTS_ASSISTS": MarketType.PLAYER_PTS_AST,
    "REBOUNDS_ASSISTS": MarketType.PLAYER_REB_AST,
    "POINTS_REBOUNDS_ASSISTS": MarketType.PLAYER_PTS_REB_AST,
    "STEALS_BLOCKS": MarketType.PLAYER_STEALS_BLOCKS,
    # Novig ships these as Over/Under 0.5; our canonical form is YES_NO,
    # and novig.build_rows maps index 0 -> "yes" and drops the strike.
    "DOUBLE_DOUBLE": MarketType.PLAYER_DOUBLE_DOUBLE,
    "TRIPLE_DOUBLE": MarketType.PLAYER_TRIPLE_DOUBLE,
}

BASKETBALL: dict[str, MarketType] = {
    **GAME_LINES, **TEAM_TOTALS, **HALVES, **BASKETBALL_PROPS,
    # "Which player scores the game's first basket": one Yes/No market per
    # player, like FIRST_GOAL_SCORER.  Optic's first_basket is the same
    # question (its first_basket_including_ft is the free-throw variant).
    "FIRST_BASKET": MarketType.FIRST_BASKET,
}

BASKETBALL_IGNORED: frozenset[str] = frozenset()


# === Football (NFL / CFL) ===

FOOTBALL_PROPS: dict[str, MarketType] = {
    "PASSING_YARDS": MarketType.PLAYER_PASSING_YARDS,
    "PASSING_TOUCHDOWNS": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "PASSING_ATTEMPTS": MarketType.PLAYER_PASSING_ATTEMPTS,
    "PASSING_COMPLETIONS": MarketType.PLAYER_PASSING_COMPLETIONS,
    "RECEIVING_YARDS": MarketType.PLAYER_RECEIVING_YARDS,
    "RECEPTIONS": MarketType.PLAYER_RECEPTIONS,
    "RUSHING_YARDS": MarketType.PLAYER_RUSHING_YARDS,
    "RUSHING_ATTEMPTS": MarketType.PLAYER_RUSHING_ATTEMPTS,
    "LONGEST_RECEPTION": MarketType.PLAYER_LONGEST_RECEPTION,
    "LONGEST_RUSH": MarketType.PLAYER_LONGEST_RUSH,
    "INTERCEPTIONS_THROWN": MarketType.PLAYER_INTERCEPTIONS,
    "TOUCHDOWNS": MarketType.PLAYER_TOUCHDOWNS,
    "FIRST_TOUCHDOWN_SCORER": MarketType.FIRST_TOUCHDOWN_SCORER,
    "RUSHING_AND_RECEIVING_YARDS": MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    "PASSING_AND_RUSHING_YARDS": MarketType.PLAYER_PASSING_RUSHING_YARDS,
    "LONGEST_COMPLETION": MarketType.PLAYER_LONGEST_PASSING_COMPLETION,
    "TACKLES_ASSISTS": MarketType.PLAYER_TACKLES_ASSISTS,
    "KICKING_POINTS": MarketType.PLAYER_KICKING_POINTS,
    "FIELD_GOALS_MADE": MarketType.PLAYER_FIELD_GOALS_MADE,
}

#: NFL "participation protection" props (docs.novig.com/api/concepts/
#: participation-protection, live 2026-11-05): own book, pregame only; a
#: player who misses the second half voids to pregame FMV.  Same contract as
#: Kalshi's "(Protected)" props, so the base type's ``_insurance`` twin, which
#: insurance_stamp gives the base prop's Optic odd.
FOOTBALL_PROTECTED: dict[str, MarketType] = {
    "PASSING_YARDS_PROTECTED": MarketType.PLAYER_PASSING_YARDS_INSURANCE,
    "PASSING_ATTEMPTS_PROTECTED": MarketType.PLAYER_PASSING_ATTEMPTS_INSURANCE,
    "PASSING_COMPLETIONS_PROTECTED": MarketType.PLAYER_PASSING_COMPLETIONS_INSURANCE,
    "PASSING_TOUCHDOWNS_PROTECTED": MarketType.PLAYER_PASSING_TOUCHDOWNS_INSURANCE,
    "LONGEST_COMPLETION_PROTECTED": MarketType.PLAYER_LONGEST_PASSING_COMPLETION_INSURANCE,
    "INTERCEPTIONS_THROWN_PROTECTED": MarketType.PLAYER_INTERCEPTIONS_INSURANCE,
    "RUSHING_YARDS_PROTECTED": MarketType.PLAYER_RUSHING_YARDS_INSURANCE,
    "RUSHING_ATTEMPTS_PROTECTED": MarketType.PLAYER_RUSHING_ATTEMPTS_INSURANCE,
    "LONGEST_RUSH_PROTECTED": MarketType.PLAYER_LONGEST_RUSH_INSURANCE,
    "RECEIVING_YARDS_PROTECTED": MarketType.PLAYER_RECEIVING_YARDS_INSURANCE,
    "RECEPTIONS_PROTECTED": MarketType.PLAYER_RECEPTIONS_INSURANCE,
    "LONGEST_RECEPTION_PROTECTED": MarketType.PLAYER_LONGEST_RECEPTION_INSURANCE,
    "PASSING_AND_RUSHING_YARDS_PROTECTED": MarketType.PLAYER_PASSING_RUSHING_YARDS_INSURANCE,
    "RUSHING_AND_RECEIVING_YARDS_PROTECTED": MarketType.PLAYER_RUSHING_RECEIVING_YARDS_INSURANCE,
    "TOUCHDOWNS_PROTECTED": MarketType.PLAYER_TOUCHDOWNS_INSURANCE,
}

FOOTBALL: dict[str, MarketType] = {
    **GAME_LINES, **TEAM_TOTALS, **HALVES, **FOOTBALL_PROPS, **FOOTBALL_PROTECTED,
    # Optic prices a football half winner only as 3-way ("1h_winner_3way"), so
    # Novig's 2-way MONEY_1H binds there (home/away rows; a tied half settles
    # differently, trading decides).  "1h_moneyline" would never merge.
    "MONEY_1H": MarketType.FIRST_HALF_WINNER_3WAY,
}

FOOTBALL_IGNORED: frozenset[str] = frozenset()


# === Baseball ===

BASEBALL_PROPS: dict[str, MarketType] = {
    "HITS": MarketType.PLAYER_HITS,
    "HOME_RUNS": MarketType.PLAYER_HOME_RUNS,
    "TOTAL_BASES": MarketType.PLAYER_BASES,
    "HITS_RUNS_RBIS": MarketType.PLAYER_HITS_RUNS_RBIS,
    # The unqualified "strikeouts" prop is the pitcher's; the batter's
    # (BATTING_STRIKEOUTS) is a different contract and is ignored below.
    "PITCHER_STRIKEOUTS": MarketType.PLAYER_STRIKEOUTS,
    "RBIS": MarketType.PLAYER_RBIS,
    "RUNS": MarketType.PLAYER_RUNS,
    "STOLEN_BASES": MarketType.PLAYER_STOLEN_BASES,
    "BATTING_STRIKEOUTS": MarketType.PLAYER_BATTING_STRIKEOUTS,
    "BATTING_WALKS": MarketType.PLAYER_BATTING_WALKS,
    # The pitcher-side markets: Novig's unqualified WALKS / HITS_ALLOWED /
    # EARNED_RUNS are priced on the pitchers (a "Nick Martinez 0.5 WALKS"
    # RP), the batter walk being BATTING_WALKS above.
    "WALKS": MarketType.PLAYER_WALKS_ALLOWED,
    "HITS_ALLOWED": MarketType.PLAYER_HITS_ALLOWED,
    "EARNED_RUNS": MarketType.PLAYER_EARNED_RUNS,
    "PITCHER_OUTS": MarketType.PLAYER_OUTS,
}

BASEBALL: dict[str, MarketType] = {
    **GAME_LINES, **TEAM_TOTALS, **BASEBALL_F5, **BASEBALL_PROPS,
    "FIRST_INNING_TOTAL": MarketType.FIRST_INNING_TOTAL,
}

BASEBALL_IGNORED: frozenset[str] = frozenset()


# === Hockey ===
# SPREAD is the puck line, which leagues/nhl.py already models as
# POINT_SPREAD.  The prop names and strikes below were read off the live
# feed on 2026-10-06 (e.g. "Artemi Panarin 2.5 SHOTS_ON_GOAL").

HOCKEY_PROPS: dict[str, MarketType] = {
    "PLAYER_GOALS": MarketType.PLAYER_GOALS,
    "ASSISTS": MarketType.PLAYER_ASSISTS,
    "POINTS": MarketType.PLAYER_POINTS,
    "SHOTS_ON_GOAL": MarketType.PLAYER_SHOTS_ON_GOAL,
    "FIRST_GOAL_SCORER": MarketType.FIRST_GOAL_SCORER,
}

HOCKEY: dict[str, MarketType] = {**GAME_LINES, **TEAM_TOTALS, **HOCKEY_PROPS}

HOCKEY_IGNORED: frozenset[str] = frozenset()


# === Soccer ===

SOCCER_PROPS: dict[str, MarketType] = {
    "PLAYER_GOALS": MarketType.PLAYER_GOALS,
    "SHOTS_ON_TARGET": MarketType.PLAYER_SHOTS_ON_TARGET,
    "SHOTS": MarketType.PLAYER_SHOTS,
    "FOULS": MarketType.PLAYER_FOULS,
    "SAVES": MarketType.PLAYER_SAVES,
    "GOALS_ASSISTS": MarketType.PLAYER_GOALS_OR_ASSIST,
    "FIRST_GOAL_SCORER": MarketType.FIRST_GOAL_SCORER,
    # Optic prices soccer player_assists on the same fixtures (it is in
    # SOCCER_OPTIC_TABLE_TYPES), so the plain assists ladder merges.
    "ASSISTS": MarketType.PLAYER_ASSISTS,
}

SOCCER: dict[str, MarketType] = {
    **GAME_LINES, **TEAM_TOTALS, **SOCCER_PROPS,
    # Each 3-way result is its own Yes/No market: the WIN form carries
    # market.competitor (whose side the Yes leg backs), the DRAW form
    # carries none. novig.build_rows emits one affirmative row per market
    # and drops the "No" leg, which means "any other result".
    "MONEYLINE_3_WAY_WIN": MarketType.MONEYLINE_3WAY,
    "MONEYLINE_3_WAY_DRAW": MarketType.MONEYLINE_3WAY,
    "BOTH_TEAMS_TO_SCORE": MarketType.BTTS,
    "TOTAL_CORNERS": MarketType.TOTAL_CORNERS,
    "TEAM_TOTAL_CORNERS": MarketType.TEAM_TOTAL_CORNERS,
}

SOCCER_IGNORED: frozenset[str] = frozenset()


# === Tennis ===
# SPREAD is a GAMES handicap and TOTAL is total games — both verified
# against live strike ranges (see module docstring).

TENNIS: dict[str, MarketType] = {
    "MONEY": MarketType.MONEYLINE,
    "SPREAD": MarketType.POINT_SPREAD,
    "TOTAL": MarketType.MATCH_TOTAL_GAMES,
    "SET_SPREAD": MarketType.SET_HANDICAP,
    "TOTAL_SETS": MarketType.TOTAL_SETS,
    "FIRST_SET_MONEYLINE": MarketType.FIRST_SET_WINNER,
    # Games won by ONE named player (strike 7.5..13.5), not the match total
    # above.  Optic prices the same contract as ``player_games_won`` and
    # ships ``player_id`` on it, so the entity is the usual id join through
    # ``player.opticOddsId`` -- 190/192 Novig markets carry that id and all
    # 150 distinct ids matched an Optic player_games_won player on
    # 2026-08-26.  Optic's own source_ids never carry Novig here (unlike
    # SPREAD/TOTAL), so this row only exists because the matcher builds it.
    "PLAYER_GAMES_WON": MarketType.PLAYER_GAMES_WON,
}

TENNIS_IGNORED: frozenset[str] = frozenset()


# === MMA ===

MMA: dict[str, MarketType] = {
    "MONEY": MarketType.MONEYLINE,
    "TOTAL": MarketType.TOTAL_ROUNDS,
    "GO_THE_DISTANCE": MarketType.FIGHT_GOES_DISTANCE,
    # One market PER METHOD, each carrying market.competitor -- which is
    # exactly METHOD_OF_VICTORY's shape (fighter-scoped yes/no, method in
    # grouping_key), NOT the bundled WIN_BY_KO_SUB_DQ.  The method comes
    # from the TYPE via fight_props.novig_method_key and lands in
    # grouping_key, so the three do not collapse onto one key.
    "VICTORY_BY_KO_KTO_OR_DQ": MarketType.METHOD_OF_VICTORY,
    "VICTORY_BY_SUBMISSION": MarketType.METHOD_OF_VICTORY,
    "VICTORY_BY_DECISION": MarketType.METHOD_OF_VICTORY,
}

MMA_IGNORED = frozenset({
    # Draw-yes/no on a 2-way fight. Kalshi's draw_or_nc settles draw OR
    # no-contest and Optic's Draw does not, so there is no like-for-like
    # twin to merge onto -- see fight_props._NOVIG_METHOD_TYPE.
    "DRAW",
})


# === Esports ===
# UNVERIFIED: CS2 / LoL / Dota 2 had scheduled events but no open markets
# on 2026-08-14. In esports a spread is a MAP handicap and a total is a
# count of MAPS, which is how leagues/esports_markets.py models them.

ESPORTS: dict[str, MarketType] = {
    "MONEY": MarketType.MONEYLINE,
    "SPREAD": MarketType.MAP_HANDICAP,
    "TOTAL": MarketType.TOTAL_MAPS,
}

ESPORTS_IGNORED: frozenset[str] = frozenset()

_SPORT_TABLES: dict[str, tuple[dict[str, MarketType], frozenset[str]]] = {
    "baseball": (BASEBALL, BASEBALL_IGNORED),
    "basketball": (BASKETBALL, BASKETBALL_IGNORED),
    "esports": (ESPORTS, ESPORTS_IGNORED),
    "football": (FOOTBALL, FOOTBALL_IGNORED),
    "hockey": (HOCKEY, HOCKEY_IGNORED),
    "mma": (MMA, MMA_IGNORED),
    "soccer": (SOCCER, SOCCER_IGNORED),
    "tennis": (TENNIS, TENNIS_IGNORED),
}


def novig_config_for_sport(sport: str, league: str) -> NovigConfig | None:
    """Python crosswalk for one sport. Tip maps and ignores overlay this."""
    table = _SPORT_TABLES.get(sport.strip().lower())
    if table is None:
        return None
    mapped, ignored = table
    return NovigConfig(league=league, market_types=dict(mapped), ignored_types=ignored)


def classify_novig_type(sport: str, market_type: str) -> tuple[str, MarketType | None]:
    """``mapped``, ``ignored``, or ``unknown`` for one Novig ``market.type``."""
    raw = market_type.strip()
    table = _SPORT_TABLES.get(sport.strip().lower())
    if table is None or not raw:
        return "unknown", None
    mapped, ignored = table
    if raw in mapped:
        return "mapped", mapped[raw]
    if raw in ignored:
        return "ignored", None
    return "unknown", None


#: Tip league slugs whose Novig mapping is a code decision, with Novig's own
#: ``event.league`` string.  Novig files ATP Challenger events under "ATP";
#: the Optic fixture-id join keeps them in this league's pass
#: (``with_code_novig``).  A slug already wired by the tip keeps the tip's.
NOVIG_LEAGUE_NAMES: dict[str, str] = {
    "liga_mx": "Liga MX",
    "atp_challenger": "ATP",
}
