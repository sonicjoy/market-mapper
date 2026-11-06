"""Shared football Optic + Polymarket + PX + crypto.com taxonomy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.polymarket import (
    PolymarketConfig,
    _norm_name,
    mlb_moneyline_rule,
    mlb_spread_rule,
    mlb_total_rule,
)
from mappers.exchanges.px import PxConfig
from mappers.market_types import MarketType

# Shared across all football leagues (CFL included): game lines only.
FOOTBALL_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "point_spread": MarketType.POINT_SPREAD,
    "total_points": MarketType.GAME_TOTAL,
}

# NFL + NCAAF only — 1H/1Q, team total, and player Optic ids.
FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS: dict[str, MarketType] = {
    "team_total": MarketType.TEAM_TOTAL,
    "1st_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    "1st_half_moneyline_3-way": MarketType.FIRST_HALF_WINNER_3WAY,
    "1st_half_point_spread": MarketType.FIRST_HALF_POINT_SPREAD,
    "1st_half_total_points": MarketType.FIRST_HALF_TOTAL,
    "1st_quarter_moneyline_3-way": MarketType.FIRST_QUARTER_WINNER_3WAY,
    "1st_quarter_point_spread": MarketType.FIRST_QUARTER_POINT_SPREAD,
    "1st_quarter_total_points": MarketType.FIRST_QUARTER_TOTAL,
    "2nd_half_moneyline_3-way": MarketType.SECOND_HALF_WINNER_3WAY,
    "2nd_half_total_points": MarketType.SECOND_HALF_TOTAL,
    "player_passing_yards": MarketType.PLAYER_PASSING_YARDS,
    "player_interceptions": MarketType.PLAYER_INTERCEPTIONS,
    "player_passing_touchdowns": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "player_receiving_yards": MarketType.PLAYER_RECEIVING_YARDS,
    "player_receptions": MarketType.PLAYER_RECEPTIONS,
    "player_rushing_yards": MarketType.PLAYER_RUSHING_YARDS,
    "player_rushing_attempts": MarketType.PLAYER_RUSHING_ATTEMPTS,
    "player_passing_attempts": MarketType.PLAYER_PASSING_ATTEMPTS,
    "player_passing_completions": MarketType.PLAYER_PASSING_COMPLETIONS,
    "player_longest_reception": MarketType.PLAYER_LONGEST_RECEPTION,
    "player_longest_rush": MarketType.PLAYER_LONGEST_RUSH,
    "player_touchdowns": MarketType.PLAYER_TOUCHDOWNS,
    "first_touchdown_scorer": MarketType.FIRST_TOUCHDOWN_SCORER,
    "team_first_touchdown_scorer": MarketType.TEAM_FIRST_TOUCHDOWN_SCORER,
    "team_total_touchdowns": MarketType.TEAM_TOTAL_TOUCHDOWNS,
    "team_total_receiving_yards": MarketType.TEAM_TOTAL_RECEIVING_YARDS,
    "team_total_receiving_touchdowns": MarketType.TEAM_TOTAL_RECEIVING_TOUCHDOWNS,
    "team_total_field_goals": MarketType.TEAM_TOTAL_FIELD_GOALS,
    "player_rushing_+_receiving_yards": MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    "player_passing_+_rushing_yards": MarketType.PLAYER_PASSING_RUSHING_YARDS,
    "player_longest_passing_completion": MarketType.PLAYER_LONGEST_PASSING_COMPLETION,
    "player_tackles_+_assists": MarketType.PLAYER_TACKLES_ASSISTS,
    "player_kicking_points": MarketType.PLAYER_KICKING_POINTS,
    "player_sacks": MarketType.PLAYER_SACKS,
    "player_tackles": MarketType.PLAYER_TACKLES,
    "player_field_goals_made": MarketType.PLAYER_FIELD_GOALS_MADE,
    "last_touchdown_scorer": MarketType.LAST_TOUCHDOWN_SCORER,
    "team_total_sacks": MarketType.TEAM_TOTAL_SACKS,
    "team_total_first_downs": MarketType.TEAM_TOTAL_FIRST_DOWNS,
    "team_total_rushing_yards": MarketType.TEAM_TOTAL_RUSHING_YARDS,
    "team_total_rushing_touchdowns": MarketType.TEAM_TOTAL_RUSHING_TOUCHDOWNS,
    "team_total_passing_touchdowns": MarketType.TEAM_TOTAL_PASSING_TOUCHDOWNS,
    "total_touchdowns": MarketType.TOTAL_TOUCHDOWNS,
    "will_there_be_overtime": MarketType.WILL_THERE_BE_OVERTIME,
    "race_to_7_points": MarketType.RACE_TO_POINTS,
    "race_to_10_points": MarketType.RACE_TO_POINTS,
    "race_to_14_points": MarketType.RACE_TO_POINTS,
    "race_to_15_points": MarketType.RACE_TO_POINTS,
    "race_to_20_points": MarketType.RACE_TO_POINTS,
    "race_to_21_points": MarketType.RACE_TO_POINTS,
    "race_to_28_points": MarketType.RACE_TO_POINTS,
    "race_to_35_points": MarketType.RACE_TO_POINTS,
    "2nd_quarter_moneyline_3-way": MarketType.SECOND_QUARTER_WINNER_3WAY,
    "2nd_quarter_point_spread": MarketType.SECOND_QUARTER_POINT_SPREAD,
    "2nd_quarter_total_points": MarketType.SECOND_QUARTER_TOTAL,
    "3rd_quarter_moneyline_3-way": MarketType.THIRD_QUARTER_WINNER_3WAY,
    "3rd_quarter_point_spread": MarketType.THIRD_QUARTER_POINT_SPREAD,
    "3rd_quarter_total_points": MarketType.THIRD_QUARTER_TOTAL,
    "4th_quarter_moneyline_3-way": MarketType.FOURTH_QUARTER_WINNER_3WAY,
    "4th_quarter_point_spread": MarketType.FOURTH_QUARTER_POINT_SPREAD,
    "4th_quarter_total_points": MarketType.FOURTH_QUARTER_TOTAL,
    "4th_quarter_both_teams_to_score": MarketType.FOURTH_QUARTER_BOTH_SCORE,
    "2nd_half_point_spread": MarketType.SECOND_HALF_POINT_SPREAD,
    "2nd_half_team_total": MarketType.SECOND_HALF_TEAM_TOTAL,
    "team_total_passing_yards": MarketType.TEAM_TOTAL_PASSING_YARDS,
    "team_total_yards": MarketType.TEAM_TOTAL_YARDS,
    "total_passing_yards": MarketType.GAME_TOTAL_PASSING_YARDS,
    "1st_quarter_both_teams_to_score": MarketType.FIRST_QUARTER_BOTH_SCORE,
    "2nd_quarter_both_teams_to_score": MarketType.SECOND_QUARTER_BOTH_SCORE,
    "3rd_quarter_both_teams_to_score": MarketType.THIRD_QUARTER_BOTH_SCORE,
    "team_total_receptions": MarketType.TEAM_TOTAL_RECEPTIONS,
    "team_total_rushing_+_receiving_yards": MarketType.TEAM_TOTAL_SCRIMMAGE_YARDS,
    "total_passing_touchdowns": MarketType.GAME_TOTAL_PASSING_TOUCHDOWNS,
    "total_rushing_touchdowns": MarketType.GAME_TOTAL_RUSHING_TOUCHDOWNS,
    "total_rushing_yards": MarketType.GAME_TOTAL_RUSHING_YARDS,
    "first_team_to_score": MarketType.FIRST_TEAM_TO_SCORE,
    "first_team_touchdown": MarketType.FIRST_TEAM_TOUCHDOWN,
    "2nd_half_first_team_to_score": MarketType.SECOND_HALF_FIRST_TEAM_TO_SCORE,
    "halftime_fulltime": MarketType.HALFTIME_FULLTIME,
    "highest_scoring_quarter": MarketType.HIGHEST_SCORING_QUARTER,
    "most_passing_yards_player": MarketType.MOST_PASSING_YARDS,
    "successful_2_point_conversion": MarketType.SUCCESSFUL_TWO_POINT_CONVERSION,
    "will_there_be_a_safety": MarketType.WILL_THERE_BE_A_SAFETY,
}

FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    **FOOTBALL_OPTIC_TABLE_TYPES,
    **FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS,
}

NFL_NCAAF_LEAGUES = frozenset({"nfl", "ncaaf"})

# Official Polymarket question Path 2 — game lines only.
FOOTBALL_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total": MarketType.GAME_TOTAL,
    "spread": MarketType.POINT_SPREAD,
}

football_market_rules = (
    mlb_total_rule,
    mlb_spread_rule,
    mlb_moneyline_rule,
)

_STYLE = "mlb_suffix"
FOOTBALL_POLY_TEAM_NAME_ALIASES: dict[str, str] = {
    _norm_name("British Columbia Lions", _STYLE): _norm_name("BC Lions", _STYLE),
}

NFL_PX = PxConfig(
    tournament_id=31,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
    },
    # Anytime TD scorer ("<Player> To Score a Touchdown", YES/NO) = over 0.5.
    suffix=[
        (" To Score a Touchdown", MarketType.PLAYER_TOUCHDOWNS),
    ],
)

CFL_PX = PxConfig(
    tournament_id=1600000275,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
    },
    suffix=[],
)


# crypto.com NFL / NCAAF player-prop vocabulary.  Keys are the exact live
# PREDICT_CONTRACT_TYPE strings from the crypto FIX feed
# (processed_upstream_us.crypto_underlying_securities, verified 2026-09); the
# mapper keys on the raw string, so they must match byte-for-byte.  Both the
# plain "Total X" over/under contract and its "... Milestones" N+ ladder map
# to the same MarketType — the milestone line ("Milestone 60+") is parsed to
# over 59.5 at fetch time (fetch/crypto_com_underlying_flat.py), so both
# resolve as Over/Under stat lines.  "To Score a Touchdown" is the Yes-leg
# anytime-scorer threshold → over 0.5 via _FIXED_OVER_HALF in crypto_com.py
# (same pattern as MLB "To Hit A Home Run").  Every target is already wired on
# the Optic side (FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS) and priced by OpticOdds
# (player_touchdowns anytime = over 0.5; yards/receptions milestone lines sit
# on Optic's X9.5 grid).  "Total Rushing Attempts" / "Longest Reception" ship
# plain-only in the feed (no Milestones variant observed).
# Combo rush+rec / pass+rush yards map to live Optic ``player_*_+_*_yards``.
# Passing attempts / longest rush have no live crypto series.
_FOOTBALL_CRYPTO_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "Total Receiving Yards": MarketType.PLAYER_RECEIVING_YARDS,
    "Total Receiving Yards Milestones": MarketType.PLAYER_RECEIVING_YARDS,
    "Total Rushing Yards": MarketType.PLAYER_RUSHING_YARDS,
    "Total Rushing Yards Milestones": MarketType.PLAYER_RUSHING_YARDS,
    "Total Receptions": MarketType.PLAYER_RECEPTIONS,
    "Total Receptions Milestones": MarketType.PLAYER_RECEPTIONS,
    "Total Passing Yards": MarketType.PLAYER_PASSING_YARDS,
    "Total Passing Yards Milestones": MarketType.PLAYER_PASSING_YARDS,
    "Total Passing Touchdowns": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "Total Passing Touchdowns Milestones": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "Total Pass Completions": MarketType.PLAYER_PASSING_COMPLETIONS,
    "Total Pass Completions Milestones": MarketType.PLAYER_PASSING_COMPLETIONS,
    "Total Rushing Attempts": MarketType.PLAYER_RUSHING_ATTEMPTS,
    "Longest Reception": MarketType.PLAYER_LONGEST_RECEPTION,
    "Interceptions Thrown": MarketType.PLAYER_INTERCEPTIONS,
    "Interceptions Thrown Milestones": MarketType.PLAYER_INTERCEPTIONS,
    "To Score a Touchdown": MarketType.PLAYER_TOUCHDOWNS,
    "To Score 2+ Touchdowns": MarketType.PLAYER_TOUCHDOWNS,
    "To Score 3+ Touchdowns": MarketType.PLAYER_TOUCHDOWNS,
    "To Score First Touchdown": MarketType.FIRST_TOUCHDOWN_SCORER,
    "Total Rushing + Receiving Yards": MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    "Total Rushing + Receiving Yards Milestones": (
        MarketType.PLAYER_RUSHING_RECEIVING_YARDS
    ),
    "Total Passing + Rushing Yards": MarketType.PLAYER_PASSING_RUSHING_YARDS,
    "Total Passing + Rushing Yards Milestones": (
        MarketType.PLAYER_PASSING_RUSHING_YARDS
    ),
}

_FOOTBALL_CRYPTO_TEAM_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "Total Points": MarketType.TEAM_TOTAL,
}

# crypto.com publishes period-scoped game lines under the same contract_type
# strings as full game (Spread / Total Points) with a distinct
# meta_predict_period_type (1st Half, 1st Quarter, …).  Period winners are
# "Moneyline (3-Way)" (Home / Away / Draw); the rare 2-way period "Moneyline"
# (no Draw outcome) is not the 3-way market and stays unmapped.
CRYPTO_PERIOD_LINES: dict[str, dict[str, MarketType]] = {
    "1st Half": {
        "Moneyline (3-Way)": MarketType.FIRST_HALF_WINNER_3WAY,
        "Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "Total Points": MarketType.FIRST_HALF_TOTAL,
    },
    "2nd Half": {
        "Moneyline (3-Way)": MarketType.SECOND_HALF_WINNER_3WAY,
        "Spread": MarketType.SECOND_HALF_POINT_SPREAD,
        "Total Points": MarketType.SECOND_HALF_TOTAL,
    },
    "1st Quarter": {
        "Moneyline (3-Way)": MarketType.FIRST_QUARTER_WINNER_3WAY,
        "Spread": MarketType.FIRST_QUARTER_POINT_SPREAD,
        "Total Points": MarketType.FIRST_QUARTER_TOTAL,
    },
    "2nd Quarter": {
        "Moneyline (3-Way)": MarketType.SECOND_QUARTER_WINNER_3WAY,
        "Spread": MarketType.SECOND_QUARTER_POINT_SPREAD,
        "Total Points": MarketType.SECOND_QUARTER_TOTAL,
    },
    "3rd Quarter": {
        "Moneyline (3-Way)": MarketType.THIRD_QUARTER_WINNER_3WAY,
        "Spread": MarketType.THIRD_QUARTER_POINT_SPREAD,
        "Total Points": MarketType.THIRD_QUARTER_TOTAL,
    },
    "4th Quarter": {
        "Moneyline (3-Way)": MarketType.FOURTH_QUARTER_WINNER_3WAY,
        "Spread": MarketType.FOURTH_QUARTER_POINT_SPREAD,
        "Total Points": MarketType.FOURTH_QUARTER_TOTAL,
    },
}


# Optic has race_to_N_points for these N only (no race to 30), and a Neither
# leg that is its draw selection.
_RACE_LINES = (7, 10, 14, 15, 20, 21, 28, 35)


def football_crypto_config(
    league: str,
    settings: Mapping[str, Any],
) -> CryptoConfig | None:
    """Build crypto.com config for NFL / NCAAF grouping from tip settings."""
    grouping = str(settings.get("sport_grouping") or "").strip()
    if not league or not grouping:
        return None
    period = str(settings.get("period_type") or "Full-Game")
    contracts = {
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
    }
    return CryptoConfig(
        sport_grouping=grouping,
        league=league,
        period_type=period,
        contract_types=contracts,
        period_contract_types={
            key: dict(value) for key, value in CRYPTO_PERIOD_LINES.items()
        },
        # Props carry their own feed period gate (per market GROUP, not league);
        # the crypto NFL prop feed uses "Full-Game" (hyphen).  periods_match
        # normalizes hyphen/space, so this also admits a "Full Game" variant.
        prop_period_type="Full-Game",
        prop_contract_types=dict(_FOOTBALL_CRYPTO_PROP_CONTRACT_TYPES),
        team_prop_period_type="Full-Game",
        team_prop_contract_types=dict(_FOOTBALL_CRYPTO_TEAM_PROP_CONTRACT_TYPES),
        # "To Go To Overtime" is a fixture-scoped Yes/No game prop; Optic
        # prices it as will_there_be_overtime (Kalshi / Poly US / Underdog
        # rows already carry that market id).
        game_prop_period_type="Full-Game",
        game_prop_contract_types={
            "To Go To Overtime": MarketType.WILL_THERE_BE_OVERTIME,
            **{f"Race to {n} Points": MarketType.RACE_TO_POINTS for n in _RACE_LINES},
        },
        game_prop_lines={f"Race to {n} Points": float(n) for n in _RACE_LINES},
    )


NFL_CRYPTO = cast(
    CryptoConfig,
    football_crypto_config("NFL", {"sport_grouping": "NFL", "period_type": "Full Game"}),
)
NCAAF_CRYPTO = cast(
    CryptoConfig,
    football_crypto_config("CFB", {"sport_grouping": "CFB", "period_type": "Full-Game"}),
)

FOOTBALL_POLYMARKET = PolymarketConfig(
    slug_prefix="nfl",
    optic_league_id="nfl",
    market_types=FOOTBALL_MARKET_TYPES,
    question_style="mlb_suffix",
    market_rules=football_market_rules,
)
