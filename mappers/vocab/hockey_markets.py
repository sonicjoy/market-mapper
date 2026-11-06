"""Shared hockey Optic + crypto.com taxonomy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.market_types import MarketType

HOCKEY_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "puck_line": MarketType.POINT_SPREAD,
    "total_goals": MarketType.GAME_TOTAL,
    "1st_period_total_goals": MarketType.FIRST_PERIOD_TOTAL,
    "1st_period_team_total": MarketType.FIRST_PERIOD_TEAM_TOTAL,
    "2nd_period_total_goals": MarketType.SECOND_PERIOD_TOTAL,
    "2nd_period_team_total": MarketType.SECOND_PERIOD_TEAM_TOTAL,
    "3rd_period_total_goals": MarketType.THIRD_PERIOD_TOTAL,
    "3rd_period_team_total": MarketType.THIRD_PERIOD_TEAM_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    # Regulation 3-way (Optic moneyline_3-way; the 2-way "moneyline" above
    # includes overtime and the shootout).
    "moneyline_3-way": MarketType.MONEYLINE_3WAY,
    "will_there_be_overtime": MarketType.WILL_THERE_BE_OVERTIME,
    # OT counts, the shootout does not; the team-less "Neither" is the tie.
    "first_team_to_score_3-way": MarketType.FIRST_TEAM_TO_SCORE,
    "1st_10_minutes_total_goals": MarketType.FIRST_10_MINUTES_TOTAL,
    "1st_period_moneyline_3-way": MarketType.FIRST_PERIOD_WINNER_3WAY,
    "2nd_period_moneyline_3-way": MarketType.SECOND_PERIOD_WINNER_3WAY,
    "3rd_period_moneyline_3-way": MarketType.THIRD_PERIOD_WINNER_3WAY,
    "1st_period_puck_line": MarketType.FIRST_PERIOD_POINT_SPREAD,
    "2nd_period_puck_line": MarketType.SECOND_PERIOD_POINT_SPREAD,
    "3rd_period_puck_line": MarketType.THIRD_PERIOD_POINT_SPREAD,
    "both_teams_to_score_reg_time": MarketType.BTTS_REG_TIME,
    # Skater / goalie props.  Overtime counts toward these; the shootout
    # never does.
    "player_goals": MarketType.PLAYER_GOALS,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_points": MarketType.PLAYER_POINTS,
    "player_shots_on_goal": MarketType.PLAYER_SHOTS_ON_GOAL,
    "player_power_play_points": MarketType.PLAYER_POWER_PLAY_POINTS,
    "player_saves": MarketType.PLAYER_SAVES,
    "first_goal_scorer": MarketType.FIRST_GOAL_SCORER,
}

# crypto.com NHL player props (market group "Player Prop", period
# "Full-Game" with a hyphen, unlike the "Full Game" game lines).  Same shape
# as the football props: "Total X" Over/Under stat lines plus their
# "... Milestones" N+ ladder share one MarketType; "To Score a Goal" is the
# Yes-leg anytime scorer (player_goals over 0.5 via _FIXED_OVER_HALF);
# "First Goal Scorer" is a per-player Yes question like Optic's.  Every target
# is an Optic market above.
_HOCKEY_CRYPTO_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "To Score a Goal": MarketType.PLAYER_GOALS,
    "Total Goals": MarketType.PLAYER_GOALS,
    "Total Goals Milestones": MarketType.PLAYER_GOALS,
    "Total Assists": MarketType.PLAYER_ASSISTS,
    "Total Assists Milestones": MarketType.PLAYER_ASSISTS,
    "Total Points": MarketType.PLAYER_POINTS,
    "Total Points Milestones": MarketType.PLAYER_POINTS,
    "Total Shots on Goal": MarketType.PLAYER_SHOTS_ON_GOAL,
    "Total Shots on Goal Milestones": MarketType.PLAYER_SHOTS_ON_GOAL,
    "Total Saves": MarketType.PLAYER_SAVES,
    "Total Saves Milestones": MarketType.PLAYER_SAVES,
    "First Goal Scorer": MarketType.FIRST_GOAL_SCORER,
}


def hockey_crypto_config(
    league: str,
    settings: Mapping[str, Any],
) -> CryptoConfig | None:
    """Build crypto.com config for NHL grouping from tip settings."""
    grouping = str(settings.get("sport_grouping") or "").strip()
    if not league or not grouping:
        return None
    period = str(settings.get("period_type") or "Full Game")
    return CryptoConfig(
        sport_grouping=grouping,
        league=league,
        period_type=period,
        contract_types={
            "Moneyline": MarketType.MONEYLINE,
            "Puck Line": MarketType.POINT_SPREAD,
            "Spread": MarketType.POINT_SPREAD,
            "Total Goals": MarketType.GAME_TOTAL,
        },
        prop_period_type="Full-Game",
        prop_contract_types=dict(_HOCKEY_CRYPTO_PROP_CONTRACT_TYPES),
    )


NHL_CRYPTO = cast(
    CryptoConfig,
    hockey_crypto_config("NHL", {"sport_grouping": "NHL", "period_type": "Full Game"}),
)
