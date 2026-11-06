"""Polymarket US football (NFL/NCAAF) ``sportsMarketType`` → MarketType + kind.

Half of ``mappers.vocab.poly_usa_smt``, split for size. Settlement notes
come from the gateway market ``description`` / ``rulesDisclaimer``.
"""

from __future__ import annotations

from mappers.market_types import MarketType as M

FOOTBALL_SMT: dict[str, tuple[M, str]] = {
    "football_team_full_game_winner": (M.MONEYLINE, "winner"),
    "football_team_full_game_spread": (M.POINT_SPREAD, "spread"),
    "football_team_full_game_total": (M.GAME_TOTAL, "total"),
    "football_team_points_full_game_total": (M.TEAM_TOTAL, "team_total"),
    "football_team_first_half_winner": (M.FIRST_HALF_WINNER_3WAY, "winner"),
    "football_team_first_half_spread": (M.FIRST_HALF_POINT_SPREAD, "spread"),
    "football_game_first_half_total": (M.FIRST_HALF_TOTAL, "total"),
    # ``football_team_first_half_total`` is the TEAM 1H total (docs trap).
    "football_team_first_half_total": (M.FIRST_HALF_TEAM_TOTAL, "team_total"),
    "football_team_first_quarter_winner": (M.FIRST_QUARTER_WINNER_3WAY, "winner"),
    "football_team_first_quarter_spread": (M.FIRST_QUARTER_POINT_SPREAD, "spread"),
    "football_game_first_quarter_total": (M.FIRST_QUARTER_TOTAL, "total"),
    # 2H and 4Q: the venue excludes OT ("Overtime does not count for 2H and
    # 4Q markets"); Optic's US-book lines usually include it. Mapped anyway
    # (ruled 2026-09-26): whether to trade them is a trading decision.
    "football_team_second_half_winner": (M.SECOND_HALF_WINNER_3WAY, "winner"),
    "football_team_second_half_spread": (M.SECOND_HALF_POINT_SPREAD, "spread"),
    "football_game_second_half_total": (M.SECOND_HALF_TOTAL, "total"),
    "football_team_second_half_total": (M.SECOND_HALF_TEAM_TOTAL, "team_total"),
    "football_team_fourth_quarter_winner": (M.FOURTH_QUARTER_WINNER_3WAY, "winner"),
    "football_team_fourth_quarter_spread": (M.FOURTH_QUARTER_POINT_SPREAD, "spread"),
    "football_game_fourth_quarter_total": (M.FOURTH_QUARTER_TOTAL, "total"),
    "football_game_fourth_quarter_both_teams_score_points": (
        M.FOURTH_QUARTER_BOTH_SCORE, "game_yn",
    ),
    "football_team_second_quarter_winner": (M.SECOND_QUARTER_WINNER_3WAY, "winner"),
    "football_team_second_quarter_spread": (M.SECOND_QUARTER_POINT_SPREAD, "spread"),
    "football_game_second_quarter_total": (M.SECOND_QUARTER_TOTAL, "total"),
    "football_team_third_quarter_winner": (M.THIRD_QUARTER_WINNER_3WAY, "winner"),
    "football_team_third_quarter_spread": (M.THIRD_QUARTER_POINT_SPREAD, "spread"),
    "football_game_third_quarter_total": (M.THIRD_QUARTER_TOTAL, "total"),
    "football_game_first_quarter_both_teams_score_points": (
        M.FIRST_QUARTER_BOTH_SCORE, "game_yn",
    ),
    "football_game_second_quarter_both_teams_score_points": (
        M.SECOND_QUARTER_BOTH_SCORE, "game_yn",
    ),
    "football_game_third_quarter_both_teams_score_points": (
        M.THIRD_QUARTER_BOTH_SCORE, "game_yn",
    ),
    "football_game_total_touchdowns": (M.TOTAL_TOUCHDOWNS, "total"),
    "football_game_total_pass_touchdowns": (M.GAME_TOTAL_PASSING_TOUCHDOWNS, "total"),
    "football_game_total_rush_touchdowns": (M.GAME_TOTAL_RUSHING_TOUCHDOWNS, "total"),
    "football_game_total_rush_yards": (M.GAME_TOTAL_RUSHING_YARDS, "total"),
    "football_game_total_pass_yards": (M.GAME_TOTAL_PASSING_YARDS, "total"),
    "football_game_both_teams_score_touchdown": (M.BOTH_TEAMS_SCORE_TD, "game_yn"),
    "football_game_overtime": (M.WILL_THERE_BE_OVERTIME, "game_yn"),
    "football_game_pick_six": (M.PICK_SIX, "game_yn"),
    "football_game_race_to_points": (M.RACE_TO_POINTS, "race"),
    # Per-team Yes only; the "neither" leg stays unmapped.
    "football_game_first_score": (M.FIRST_TEAM_TO_SCORE, "team_outcome"),
    "football_game_first_touchdown": (M.FIRST_TEAM_TOUCHDOWN, "team_outcome"),
    # Regulation only on the venue ("overtime is not included").
    "football_game_second_half_first_score": (
        M.SECOND_HALF_FIRST_TEAM_TO_SCORE, "team_outcome",
    ),
    # Title-parsed (polymarket_usa_titles): "ARI 1H / NYG Game", "1H Tie /
    # Tie" → Optic halftime_fulltime. Full time includes overtime on both.
    "football_game_double_result": (M.HALFTIME_FULLTIME, "double_result"),
    # Title-parsed: "1st Quarter" … "4th Quarter"; regulation quarters,
    # dead heat on a tie.
    "football_game_highest_scoring_quarter": (M.HIGHEST_SCORING_QUARTER, "hsq"),
    # Yes/No at 0.5 only ("at least one"); overtime counts.
    "football_game_safety": (M.WILL_THERE_BE_A_SAFETY, "any_yn"),
    "football_game_total_two_point_conversions": (
        M.SUCCESSFUL_TWO_POINT_CONVERSION, "any_yn",
    ),
    "football_team_total_touchdowns": (M.TEAM_TOTAL_TOUCHDOWNS, "team_total"),
    "football_team_total_field_goals_made": (M.TEAM_TOTAL_FIELD_GOALS, "team_total"),
    "football_team_total_pass_touchdowns": (
        M.TEAM_TOTAL_PASSING_TOUCHDOWNS, "team_total",
    ),
    "football_team_total_rush_touchdowns": (
        M.TEAM_TOTAL_RUSHING_TOUCHDOWNS, "team_total",
    ),
    "football_team_total_rush_yards": (M.TEAM_TOTAL_RUSHING_YARDS, "team_total"),
    "football_team_total_first_downs": (M.TEAM_TOTAL_FIRST_DOWNS, "team_total"),
    "football_team_total_sacks": (M.TEAM_TOTAL_SACKS, "team_total"),
    "football_team_total_receptions": (M.TEAM_TOTAL_RECEPTIONS, "team_total"),
    # Rushing + receiving yards.
    "football_team_total_scrimmage_yards": (M.TEAM_TOTAL_SCRIMMAGE_YARDS, "team_total"),
    # The venue counts gross pass yards ("sack yardage not subtracted");
    # Optic's may be net. Mapped anyway (ruled 2026-09-26), as is offensive
    # yards onto Optic team_total_yards.
    "football_team_total_pass_yards": (M.TEAM_TOTAL_PASSING_YARDS, "team_total"),
    "football_team_total_offensive_yards": (M.TEAM_TOTAL_YARDS, "team_total"),
    "football_player_passing_yards": (M.PLAYER_PASSING_YARDS, "player_ou"),
    "football_player_passing_touchdowns": (M.PLAYER_PASSING_TOUCHDOWNS, "player_ou"),
    "football_player_rushing_yards": (M.PLAYER_RUSHING_YARDS, "player_ou"),
    "football_player_receiving_yards": (M.PLAYER_RECEIVING_YARDS, "player_ou"),
    "football_player_receptions": (M.PLAYER_RECEPTIONS, "player_ou"),
    "football_player_touchdowns": (M.PLAYER_TOUCHDOWNS, "player_ou"),
    "football_player_interceptions_thrown": (M.PLAYER_INTERCEPTIONS, "player_ou"),
    "football_player_first_touchdown": (M.FIRST_TOUCHDOWN_SCORER, "player_yn"),
    # The player's own team's first TD (rushing, receiving or return).
    "football_player_team_first_touchdown": (M.TEAM_FIRST_TOUCHDOWN_SCORER, "player_yn"),
    # Per-player Yes only; a tie dead-heats (venue: $1 / tied players).
    "football_player_most_passing_yards": (M.MOST_PASSING_YARDS, "player_yn"),
    "football_player_passing_attempts": (M.PLAYER_PASSING_ATTEMPTS, "player_ou"),
    "football_player_rushing_attempts": (M.PLAYER_RUSHING_ATTEMPTS, "player_ou"),
    "football_player_passing_completions": (M.PLAYER_PASSING_COMPLETIONS, "player_ou"),
    "football_player_longest_reception": (M.PLAYER_LONGEST_RECEPTION, "player_ou"),
    "football_player_longest_rush": (M.PLAYER_LONGEST_RUSH, "player_ou"),
    "football_player_longest_passing_completion": (
        M.PLAYER_LONGEST_PASSING_COMPLETION, "player_ou",
    ),
    "football_player_scrimmage_yards": (M.PLAYER_RUSHING_RECEIVING_YARDS, "player_ou"),
    "football_player_passing_rushing_yards": (
        M.PLAYER_PASSING_RUSHING_YARDS, "player_ou",
    ),
}
