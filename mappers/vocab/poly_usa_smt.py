"""Polymarket US ``sportsMarketType`` → canonical MarketType + binding kind.

The gateway types every sports market with ``sportsMarketType`` (docs:
"map on this alone", never on the symbol). This table is the only place
that knows which MarketType each enum is, and how its venue sides bind onto
Optic selections. It does not read Polymarket (CLOB) or the tip: switching
an enum off or onto another MarketType is a change to this table.

Kinds (see ``mappers.exchanges.polymarket_usa_structured``):

* ``winner``       two team sides (``aec``) → one row per team; or a
                   per-outcome group (``atc``: team Yes / team-less draw)
* ``spread``       long team at the signed line, short team at its negation
* ``total``        Over/Yes → over, Under/No → under (game-wide)
* ``team_total``   as ``total`` with the sides' team as entity
* ``team_outcome`` per-team Yes/No market (set winner, map winner) → team, Yes only
* ``game_yn``      game-wide Yes/No
* ``any_yn``       game-wide Yes/No "at least one", its 0.5 rung only
* ``player_ou``    ``metadata.playerName`` at the line; ``N+`` is over N−0.5
* ``player_yn``    ``metadata.playerName`` Yes only
* ``at_least``     game-wide Yes/No "at least ``line``" → over/under line−0.5
* ``race``         per-team "first to ``line``" market → team side at the
                   line; the group's team-less market (neither) → tie
* ``mov`` / ``mof`` / ``rov`` / ``rof`` / ``exact_score`` / ``exact_score_1h`` /
  ``tennis_exact_score`` / ``double_result`` / ``hsq`` / ``odd_even``
                   per-outcome groups (odd/even: one fixed outcome) with NO typed outcome: identity is
                   read from ``title`` under a closed grammar, names checked
                   against the typed teams, Yes only — the one exception to
                   "typed fields only", see ``polymarket_usa_titles``

Per-outcome groups map their Yes side only: a No is the union of the other
outcomes, never one Optic selection. An enum not listed here is dropped
(missing > wrong). Generic ``<sport>_player_<stat>`` props fall back to the
MarketType valued ``player_<stat>`` — see :func:`smt_spec`.
"""

from __future__ import annotations

from mappers.market_types import MarketType as M
from mappers.market_types import Shape
from mappers.vocab.poly_usa_smt_football import FOOTBALL_SMT

SmtSpec = tuple[M, str]  # (canonical MarketType, kind)

_FULL_GAME_SPORTS = ("baseball", "basketball", "hockey")

_SMT: dict[str, SmtSpec] = {
    # --- baseball ---
    "baseball_team_total_runs": (M.TEAM_TOTAL, "team_total"),
    "baseball_team_first_five_winner": (M.FIRST_FIVE_MONEYLINE_3WAY, "winner"),
    "baseball_team_first_five_spread": (M.FIRST_FIVE_POINT_SPREAD, "spread"),
    "baseball_team_first_five_total": (M.FIRST_FIVE_TOTAL, "total"),
    "baseball_game_extra_innings": (M.EXTRA_INNINGS, "game_yn"),
    # YRFI: "either team scores at least one run in the 1st" = Optic
    # 1st_inning_total_runs over 0.5 (No = under 0.5).
    "baseball_team_first_inning_run": (M.FIRST_INNING_TOTAL, "at_least"),
    "baseball_player_total_bases": (M.PLAYER_BASES, "player_ou"),
    "baseball_player_earned_runs_allowed": (M.PLAYER_EARNED_RUNS, "player_ou"),
    # --- basketball periods ---
    # Away / Tie / home, the Tie the group's team-less member. Overtime can't
    # reach a first half or Q1-Q3, and the venue's 4Q excludes it, as Optic's
    # grader settles 4th_quarter_moneyline_3-way (2026-10-23). The 2H counts
    # overtime and is held (NOT_EQUIVALENT).
    "basketball_team_first_half_winner": (M.FIRST_HALF_WINNER_3WAY, "winner"),
    "basketball_team_first_quarter_winner": (M.FIRST_QUARTER_WINNER_3WAY, "winner"),
    "basketball_team_second_quarter_winner": (M.SECOND_QUARTER_WINNER_3WAY, "winner"),
    "basketball_team_third_quarter_winner": (M.THIRD_QUARTER_WINNER_3WAY, "winner"),
    "basketball_team_fourth_quarter_winner": (M.FOURTH_QUARTER_WINNER_3WAY, "winner"),
    # ``*_team_total_points*`` are per-team totals; ``*_team_<period>_total``
    # is COMBINED points despite the ``team`` (docs trap, as soccer).
    "basketball_team_total_points": (M.TEAM_TOTAL, "team_total"),
    "basketball_team_total_points_first_half": (M.FIRST_HALF_TEAM_TOTAL, "team_total"),
    # 2H counts overtime on the venue ("Overtime is included if played"), so
    # it is Optic's 2nd_half_team_total_incl_ot, not the plain 2nd_half_*.
    "basketball_team_total_points_second_half": (
        M.SECOND_HALF_TEAM_TOTAL_INCL_OT, "team_total",
    ),
    "basketball_team_first_half_total": (M.FIRST_HALF_TOTAL, "total"),
    "basketball_team_first_half_spread": (M.FIRST_HALF_POINT_SPREAD, "spread"),
    "basketball_team_first_quarter_spread": (M.FIRST_QUARTER_POINT_SPREAD, "spread"),
    "basketball_team_second_quarter_spread": (M.SECOND_QUARTER_POINT_SPREAD, "spread"),
    "basketball_team_third_quarter_spread": (M.THIRD_QUARTER_POINT_SPREAD, "spread"),
    # 4Q excludes overtime on the venue, as Optic's plain 4th_quarter_*.
    "basketball_team_fourth_quarter_spread": (M.FOURTH_QUARTER_POINT_SPREAD, "spread"),
    "basketball_team_first_quarter_total": (M.FIRST_QUARTER_TOTAL, "total"),
    "basketball_team_second_quarter_total": (M.SECOND_QUARTER_TOTAL, "total"),
    "basketball_team_third_quarter_total": (M.THIRD_QUARTER_TOTAL, "total"),
    "basketball_team_fourth_quarter_total": (M.FOURTH_QUARTER_TOTAL, "total"),
    "basketball_game_overtime": (M.WILL_THERE_BE_OVERTIME, "game_yn"),
    # One symbol per team at 10 / 20 / 30, OT included; only its Yes maps.
    "basketball_game_race_to_points": (M.RACE_TO_POINTS, "race"),
    # The generic player_<stat> fallback needs the stat to BE the MarketType
    # value; PRA's is ``player_pts_reb_ast``, so it is named here.
    "basketball_player_points_rebounds_assists": (M.PLAYER_PTS_REB_AST, "player_ou"),
    # --- hockey ---
    # Game-wide Yes/No (its ``teamId`` is only the home team); Optic
    # will_there_be_overtime, as football_game_overtime.
    "hockey_game_overtime": (M.WILL_THERE_BE_OVERTIME, "game_yn"),
    # OT included; a shootout win counts one goal (the books' NHL team total).
    "hockey_team_total_goals": (M.TEAM_TOTAL, "team_total"),
    # 60 minutes, Tie is the group's team-less member (Optic moneyline_3-way).
    "hockey_team_regulation_winner": (M.MONEYLINE_3WAY, "winner"),
    # OT included, shootout not; "Neither" is the team-less member.
    "hockey_game_first_team_to_score": (M.FIRST_TEAM_TO_SCORE, "team_outcome"),
    # Periods end at the horn: OT never reaches them. ``*_total`` is
    # combined goals despite the ``team`` in the enum.
    "hockey_team_first_period_total": (M.FIRST_PERIOD_TOTAL, "total"),
    "hockey_team_second_period_total": (M.SECOND_PERIOD_TOTAL, "total"),
    "hockey_team_third_period_total": (M.THIRD_PERIOD_TOTAL, "total"),
    "hockey_team_first_period_spread": (M.FIRST_PERIOD_POINT_SPREAD, "spread"),
    "hockey_team_second_period_spread": (M.SECOND_PERIOD_POINT_SPREAD, "spread"),
    "hockey_team_third_period_spread": (M.THIRD_PERIOD_POINT_SPREAD, "spread"),
    "hockey_team_first_period_winner": (M.FIRST_PERIOD_WINNER_3WAY, "winner"),
    "hockey_team_second_period_winner": (M.SECOND_PERIOD_WINNER_3WAY, "winner"),
    "hockey_team_third_period_winner": (M.THIRD_PERIOD_WINNER_3WAY, "winner"),
    # --- soccer: team markets settle on 90' plus stoppage; player props
    # count extra time (polymarket_usa_extra_time holds them on ties) ---
    "soccer_team_full_time_winner": (M.MONEYLINE_3WAY, "winner"),
    "soccer_team_first_half_winner": (M.FIRST_HALF_WINNER_3WAY, "winner"),
    "soccer_team_second_half_winner": (M.SECOND_HALF_WINNER_3WAY, "winner"),
    "soccer_team_full_game_spread": (M.POINT_SPREAD, "spread"),
    "soccer_team_first_half_spread": (M.FIRST_HALF_POINT_SPREAD, "spread"),
    "soccer_team_second_half_spread": (M.SECOND_HALF_POINT_SPREAD, "spread"),
    # ``soccer_team_*_total`` is COMBINED goals despite the prefix (docs trap).
    "soccer_team_full_game_total": (M.GAME_TOTAL, "total"),
    "soccer_team_first_half_total": (M.FIRST_HALF_TOTAL, "total"),
    "soccer_team_second_half_total": (M.SECOND_HALF_TOTAL, "total"),
    "soccer_team_total_goals": (M.TEAM_TOTAL, "team_total"),
    "soccer_team_total_goals_first_half": (M.FIRST_HALF_TEAM_TOTAL, "team_total"),
    "soccer_team_total_goals_second_half": (M.SECOND_HALF_TEAM_TOTAL, "team_total"),
    "soccer_game_btts": (M.BTTS, "game_yn"),
    "soccer_game_first_half_btts": (M.FIRST_HALF_BTTS, "game_yn"),
    # Title-parsed (polymarket_usa_titles): "POR wins 2-1", "Draw 1-1"
    # (+ " in 1st half"); "Other" is never mapped. Regulation only on both.
    "soccer_game_exact_score": (M.CORRECT_SCORE, "exact_score"),
    "soccer_game_first_half_exact_score": (M.FIRST_HALF_CORRECT_SCORE, "exact_score_1h"),
    "soccer_game_second_half_btts": (M.SECOND_HALF_BTTS, "game_yn"),
    # Corners taken in 90'; Optic total_corners counts the same (ruled
    # 2026-09-26, reversing the "awarded" exclusion of b18d448c).
    "soccer_game_total_corners": (M.TOTAL_CORNERS, "total"),
    "soccer_game_first_team_to_score": (M.FIRST_TEAM_TO_SCORE, "team_outcome"),
    "soccer_game_first_half_first_team_to_score": (
        M.FIRST_HALF_FIRST_TEAM_TO_SCORE, "team_outcome",
    ),
    "soccer_game_second_half_first_team_to_score": (
        M.SECOND_HALF_FIRST_TEAM_TO_SCORE, "team_outcome",
    ),
    # Own goals do not count on either side; "no goal" is never mapped.
    "soccer_player_first_goal": (M.FIRST_GOAL_SCORER, "player_yn"),
    "soccer_player_goals_plus_assists": (M.PLAYER_GOALS_OR_ASSIST, "player_ou"),
    "soccer_player_goalkeeper_saves": (M.PLAYER_SAVES, "player_ou"),
    # --- tennis ---
    "tennis_match_winner": (M.MONEYLINE, "winner"),
    "tennis_match_total_games": (M.MATCH_TOTAL_GAMES, "total"),
    "tennis_match_total_sets": (M.TOTAL_SETS, "total"),
    "tennis_match_sets_spread": (M.SET_HANDICAP, "spread"),
    # Games won over the full match (Optic game_spread).
    "tennis_match_games_spread": (M.POINT_SPREAD, "spread"),
    "tennis_set_1_winner": (M.FIRST_SET_WINNER, "team_outcome"),
    "tennis_set_2_winner": (M.SECOND_SET_WINNER, "team_outcome"),
    "tennis_set_1_total_games": (M.FIRST_SET_TOTAL_GAMES, "total"),
    "tennis_set_2_total_games": (M.SECOND_SET_TOTAL_GAMES, "total"),
    # Title-parsed (polymarket_usa_titles): "Rublev wins 2-0" → Optic
    # correct_score "2:0" on Rublev. The venue lists no per-set exact score.
    "tennis_match_exact_score": (M.CORRECT_SCORE, "tennis_exact_score"),
    # --- esports ---
    "esports_match_winner": (M.MONEYLINE, "winner"),
    "esports_series_map_handicap": (M.MAP_HANDICAP, "spread"),
    "esports_series_total_maps": (M.TOTAL_MAPS, "total"),
    # Series "games" are maps (Dota/LoL call a map a game).
    "esports_series_game_handicap": (M.MAP_HANDICAP, "spread"),
    "esports_series_total_games": (M.TOTAL_MAPS, "total"),
    # --- combat ---
    "ufc_fight_winner": (M.MONEYLINE, "winner"),
    "ufc_go_the_distance": (M.FIGHT_GOES_DISTANCE, "game_yn"),
    # Title-parsed (polymarket_usa_titles): "B. Hiestand by KO/TKO/DQ" →
    # Optic "Brady Hiestand - KO/TKO/DQ"; MOF "Submission" → method_of_ending.
    "ufc_method_of_victory": (M.METHOD_OF_VICTORY, "mov"),
    "ufc_method_of_finish": (M.METHOD_OF_FINISH, "mof"),
    # Title-parsed: "Hiestand in Round 1" → Optic round_betting
    # "Brady Hiestand :: 1st Round" (Yes only). A technical decision, draw
    # or no contest is no round win on either side. The group's
    # "Decision / Draw / No Contest" leg has no single Optic selection.
    "ufc_round_of_victory": (M.ROUND_BETTING, "rov"),
    # Title-parsed: "Fight ends before Round N begins" is exactly Optic
    # to_start_round_N with Yes and No swapped — a true binary, so both
    # sides map (venue Yes → Optic No, venue No → Optic Yes). The listed
    # type is round 2's; the title's N picks TO_START_ROUND_N.
    "ufc_round_of_finish": (M.TO_START_ROUND_2, "rof"),
    # Draw, technical draw or no contest settles at $0.50 (push), as Optic's
    # two-way boxing moneyline voids it.
    "boxing_match_winner": (M.MONEYLINE, "winner"),
    # --- darts --- two players, no draw (Optic 2-way moneyline).
    "darts_match_winner": (M.MONEYLINE, "winner"),
    # --- cricket ---
    "cricket_match_winner": (M.MONEYLINE, "winner"),
    **FOOTBALL_SMT,
}

for _sport in _FULL_GAME_SPORTS:
    _SMT.setdefault(f"{_sport}_team_full_game_winner", (M.MONEYLINE, "winner"))
    _SMT.setdefault(f"{_sport}_team_full_game_spread", (M.POINT_SPREAD, "spread"))
    _SMT.setdefault(f"{_sport}_team_full_game_total", (M.GAME_TOTAL, "total"))

# Single-inning 3-way, innings 1–8 (Optic Nth_inning_moneyline_3-way). The 9th
# is left out: its home half may not be played, yet the venue still settles.
for _n in range(1, 9):
    _SMT[f"baseball_team_inning{_n}_winner"] = (
        M[f"INNING_{_n}_WINNER_3WAY"], "winner",
    )

# Single-inning combined runs (Optic Nth_inning_total_runs). The venue settles
# on the inning's official result "regardless of whether both teams come to
# bat", so the 9th is wired too; an unplayed home half is trading's call.
_SMT["baseball_team_inning1_total"] = (M.FIRST_INNING_TOTAL, "total")
for _n in range(2, 10):
    _SMT[f"baseball_team_inning{_n}_total"] = (M[f"INNING_{_n}_TOTAL"], "total")

# Single-map winner, per-team Yes only (Optic Nth_map_moneyline). Dota/LoL
# call a map a game.
for _n in range(1, 6):
    _SMT[f"esports_map_winner_{_n}"] = (M[f"MAP_{_n}_WINNER"], "team_outcome")
    _SMT[f"esports_game_winner_{_n}"] = (M[f"MAP_{_n}_WINNER"], "team_outcome")
    # LoL/Dota first blood, per-team Yes only; kills odd/even is a true
    # binary (Yes = odd), its title checked under a closed grammar.
    _SMT[f"esports_game_first_blood_{_n}"] = (M[f"MAP_{_n}_FIRST_BLOOD"], "team_outcome")
    _SMT[f"esports_game_kills_odd_even_{_n}"] = (M[f"MAP_{_n}_KILLS_ODD"], "odd_even")

# CS2 per-map round handicap / total rounds (Optic lists maps 1–3).
for _n in range(1, 4):
    _SMT[f"esports_map_rounds_handicap_{_n}"] = (M[f"MAP_{_n}_ROUND_HANDICAP"], "spread")
    _SMT[f"esports_map_total_rounds_{_n}"] = (M[f"MAP_{_n}_TOTAL_ROUNDS"], "total")

KINDS = frozenset(spec[1] for spec in _SMT.values())

_PLAYER_SPORTS = ("baseball_", "basketball_", "hockey_", "soccer_", "football_")

# Enums whose settlement differs from, or is not confirmed equal to, the
# Optic market they resemble (owner 2026-10-22: never map unconfirmed), each
# with that market: an Optic passthrough carrying one is stripped, not kept.
# (``ufc_round_of_finish`` sat here against total_rounds until 2026-09-27;
# it now maps onto Optic to_start_round_N.)
NOT_EQUIVALENT: dict[str, M] = {
    # The venue's 2H counts overtime ("Overtime is included if played"); Optic
    # grades its 2nd_half_* winner, spread and total on regulation (grader,
    # 2026-10-22/23, every NBA overtime game where the two readings differ).
    "basketball_team_second_half_winner": M.SECOND_HALF_WINNER_3WAY,
    "basketball_team_second_half_spread": M.SECOND_HALF_POINT_SPREAD,
    "basketball_team_second_half_total": M.SECOND_HALF_TOTAL,
}

# Per-outcome markets with exactly two outcomes (a set, a map, first
# blood): one symbol per team, and its No is the other team outright.
TWO_WAY_OUTCOME_TYPES: frozenset[str] = frozenset(
    mt.value for mt, kind in _SMT.values()
    if kind == "team_outcome" and mt.shape is Shape.MONEYLINE
)

# Per-outcome market types whose No is the union of the other outcomes:
# only the Yes is stamped, and the complement pass never completes them.
YES_ONLY_TYPES = frozenset({
    M.METHOD_OF_VICTORY.value,
    M.METHOD_OF_FINISH.value,
    M.ROUND_BETTING.value,
    M.CORRECT_SCORE.value,
    M.FIRST_HALF_CORRECT_SCORE.value,
    M.HALFTIME_FULLTIME.value,
    M.HIGHEST_SCORING_QUARTER.value,
    M.MOST_PASSING_YARDS.value,
    M.TEAM_FIRST_TOUCHDOWN_SCORER.value,
})


def smt_spec(smt: str) -> SmtSpec | None:
    """(MarketType, kind) for this enum; None for an enum this table does not know."""
    text = (smt or "").strip()
    if not text or text in NOT_EQUIVALENT:
        return None
    return _code_spec(text)


def _code_spec(text: str) -> SmtSpec | None:
    spec = _SMT.get(text)
    if spec is not None:
        return spec
    for prefix in _PLAYER_SPORTS:
        head = f"{prefix}player_"
        if text.startswith(head):
            try:
                return (M(f"player_{text[len(head):]}"), "player_ou")
            except ValueError:
                return None
    return None


def not_equivalent_types(sport: str) -> frozenset[str]:
    """MarketType values a NOT_EQUIVALENT enum of ``sport`` resembles."""
    return frozenset(
        mt.value for smt, mt in NOT_EQUIVALENT.items() if smt.startswith(f"{sport}_")
    )


def known_smts() -> frozenset[str]:
    """Every explicitly wired enum (tests / coverage reporting)."""
    return frozenset(_SMT)
