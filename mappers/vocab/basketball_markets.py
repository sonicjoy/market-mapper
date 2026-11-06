"""Shared basketball Optic + Polymarket + PX + crypto.com taxonomy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.polymarket import (
    MarketRule,
    basketball_player_assists_rule,
    basketball_player_points_rule,
    basketball_player_rebounds_rule,
    mlb_moneyline_rule,
    mlb_spread_rule,
    mlb_total_rule,
)
from mappers.exchanges.px import PxConfig
from mappers.market_types import MarketType
from mappers.vocab.football_markets import CRYPTO_PERIOD_LINES

BASKETBALL_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "point_spread": MarketType.POINT_SPREAD,
    "total_points": MarketType.GAME_TOTAL,
    "1st_half_moneyline": MarketType.FIRST_HALF_MONEYLINE,
    "1st_half_point_spread": MarketType.FIRST_HALF_POINT_SPREAD,
    "1st_half_total_points": MarketType.FIRST_HALF_TOTAL,
    "1st_half_moneyline_3-way": MarketType.FIRST_HALF_WINNER_3WAY,
    "2nd_half_moneyline_3-way": MarketType.SECOND_HALF_WINNER_3WAY,
    "1st_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    "2nd_half_point_spread": MarketType.SECOND_HALF_POINT_SPREAD,
    "2nd_half_total_points": MarketType.SECOND_HALF_TOTAL,
    "2nd_half_team_total": MarketType.SECOND_HALF_TEAM_TOTAL,
    "1st_quarter_moneyline_3-way": MarketType.FIRST_QUARTER_WINNER_3WAY,
    "1st_quarter_point_spread": MarketType.FIRST_QUARTER_POINT_SPREAD,
    "1st_quarter_total_points": MarketType.FIRST_QUARTER_TOTAL,
    "2nd_quarter_moneyline_3-way": MarketType.SECOND_QUARTER_WINNER_3WAY,
    "2nd_quarter_point_spread": MarketType.SECOND_QUARTER_POINT_SPREAD,
    "2nd_quarter_total_points": MarketType.SECOND_QUARTER_TOTAL,
    "3rd_quarter_moneyline_3-way": MarketType.THIRD_QUARTER_WINNER_3WAY,
    "3rd_quarter_point_spread": MarketType.THIRD_QUARTER_POINT_SPREAD,
    "3rd_quarter_total_points": MarketType.THIRD_QUARTER_TOTAL,
    # Optic's plain 4th_quarter_* stop at the end of regulation (grader,
    # 2026-10-23: four NBA overtime games, Q4 graded without the overtime).
    "4th_quarter_moneyline_3-way": MarketType.FOURTH_QUARTER_WINNER_3WAY,
    "4th_quarter_point_spread": MarketType.FOURTH_QUARTER_POINT_SPREAD,
    "4th_quarter_total_points": MarketType.FOURTH_QUARTER_TOTAL,
    "will_there_be_overtime": MarketType.WILL_THERE_BE_OVERTIME,
    # Two-way on Optic's NBA books (no "Neither").
    "race_to_10_points": MarketType.RACE_TO_POINTS,
    "race_to_20_points": MarketType.RACE_TO_POINTS,
    # Full game incl. OT; one Yes per (team, band), e.g. Fanatics "Atlanta Hawks 11-20".
    "winning_margin": MarketType.WINNING_MARGIN,
    # These count OT.
    "2nd_half_team_total_incl_ot": MarketType.SECOND_HALF_TEAM_TOTAL_INCL_OT,
    "4th_quarter_moneyline_incl_ot": MarketType.FOURTH_QUARTER_MONEYLINE_INCL_OT,
    "4th_quarter_point_spread_incl_ot": MarketType.FOURTH_QUARTER_POINT_SPREAD_INCL_OT,
    "4th_quarter_total_points_incl_ot": MarketType.FOURTH_QUARTER_TOTAL_INCL_OT,
    "team_total": MarketType.TEAM_TOTAL,
    "player_points": MarketType.PLAYER_POINTS,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_rebounds": MarketType.PLAYER_REBOUNDS,
    "player_made_threes": MarketType.PLAYER_THREES,
    "player_blocks": MarketType.PLAYER_BLOCKS,
    "player_steals": MarketType.PLAYER_STEALS,
    "player_turnovers": MarketType.PLAYER_TURNOVERS,
    "player_double_double": MarketType.PLAYER_DOUBLE_DOUBLE,
    "player_triple_double": MarketType.PLAYER_TRIPLE_DOUBLE,
    "player_steals_+_blocks": MarketType.PLAYER_STEALS_BLOCKS,
    "player_points_+_assists": MarketType.PLAYER_PTS_AST,
    "player_points_+_rebounds": MarketType.PLAYER_PTS_REB,
    "player_points_+_rebounds_+_assists": MarketType.PLAYER_PTS_REB_AST,
    "player_rebounds_+_assists": MarketType.PLAYER_REB_AST,
    "player_assists_h2h_moneyline": MarketType.PLAYER_ASSISTS_H2H,
    "first_basket": MarketType.FIRST_BASKET,
}

BASKETBALL_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total": MarketType.GAME_TOTAL,
    "spread": MarketType.POINT_SPREAD,
    "player_points": MarketType.PLAYER_POINTS,
    "player_rebounds": MarketType.PLAYER_REBOUNDS,
    "player_assists": MarketType.PLAYER_ASSISTS,
}

basketball_market_rules: tuple[MarketRule, ...] = (
    mlb_total_rule,
    mlb_spread_rule,
    basketball_player_points_rule,
    basketball_player_rebounds_rule,
    basketball_player_assists_rule,
    mlb_moneyline_rule,
)

BASKETBALL_POLY_TEAM_NAME_ALIASES: dict[str, str] = {
    "portlandfire": "portland fire",
    "megan_dileo": "megan_gustafson",
}

NBA_PX = PxConfig(
    tournament_id=132,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
        "First Half Moneyline": MarketType.FIRST_HALF_MONEYLINE,
        "First Half Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "First Half Total Points": MarketType.FIRST_HALF_TOTAL,
    },
    suffix=[
        (" Total Points, Rebounds & Assists", MarketType.PLAYER_PTS_REB_AST),
        (" To Record a Triple Double", MarketType.PLAYER_TRIPLE_DOUBLE),
        (" To Record a Double Double", MarketType.PLAYER_DOUBLE_DOUBLE),
        (" Total Three Pointers Made", MarketType.PLAYER_THREES),
        (" Total Rebounds & Assists", MarketType.PLAYER_REB_AST),
        (" Total Points & Rebounds", MarketType.PLAYER_PTS_REB),
        (" Total Points & Assists", MarketType.PLAYER_PTS_AST),
        (" Total Steals & Blocks", MarketType.PLAYER_STEALS_BLOCKS),
        (": Team Total Points", MarketType.TEAM_TOTAL),
        (" Total Turnovers", MarketType.PLAYER_TURNOVERS),
        (" Total Rebounds", MarketType.PLAYER_REBOUNDS),
        (" Total Assists", MarketType.PLAYER_ASSISTS),
        (" Total Blocks", MarketType.PLAYER_BLOCKS),
        (" Total Points", MarketType.PLAYER_POINTS),
        (" Total Steals", MarketType.PLAYER_STEALS),
        (" Made Threes", MarketType.PLAYER_THREES),
        (" Rebounds", MarketType.PLAYER_REBOUNDS),
        (" Assists", MarketType.PLAYER_ASSISTS),
        (" Points", MarketType.PLAYER_POINTS),
    ],
)

NCAAB_PX = PxConfig(
    tournament_id=648,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
        "First Half Moneyline": MarketType.FIRST_HALF_MONEYLINE,
        "First Half Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "First Half Total Points": MarketType.FIRST_HALF_TOTAL,
    },
    suffix=[
        (" Total Points, Rebounds & Assists", MarketType.PLAYER_PTS_REB_AST),
        (" Total Three Pointers Made", MarketType.PLAYER_THREES),
        (" To Record a Triple Double", MarketType.PLAYER_TRIPLE_DOUBLE),
        (" To Record a Double Double", MarketType.PLAYER_DOUBLE_DOUBLE),
        (" Total Rebounds & Assists", MarketType.PLAYER_REB_AST),
        (" Total Points & Rebounds", MarketType.PLAYER_PTS_REB),
        (" Total Points & Assists", MarketType.PLAYER_PTS_AST),
        (" Total Steals & Blocks", MarketType.PLAYER_STEALS_BLOCKS),
        (": Team Total Points", MarketType.TEAM_TOTAL),
        (" Total Turnovers", MarketType.PLAYER_TURNOVERS),
        (" Total Rebounds", MarketType.PLAYER_REBOUNDS),
        (" Total Assists", MarketType.PLAYER_ASSISTS),
        (" Total Points", MarketType.PLAYER_POINTS),
        (" Total Blocks", MarketType.PLAYER_BLOCKS),
        (" Total Steals", MarketType.PLAYER_STEALS),
    ],
)

WNBA_PX = PxConfig(
    tournament_id=1600000176,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
        "First Half Moneyline": MarketType.FIRST_HALF_MONEYLINE,
        "First Half Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "First Half Total Points": MarketType.FIRST_HALF_TOTAL,
    },
    suffix=[
        (" Total Points, Rebounds & Assists", MarketType.PLAYER_PTS_REB_AST),
        (" To Record a Triple Double", MarketType.PLAYER_TRIPLE_DOUBLE),
        (" To Record a Double Double", MarketType.PLAYER_DOUBLE_DOUBLE),
        (" Total Three Pointers Made", MarketType.PLAYER_THREES),
        (" Total Rebounds & Assists", MarketType.PLAYER_REB_AST),
        (" Total Points & Rebounds", MarketType.PLAYER_PTS_REB),
        (" Total Points & Assists", MarketType.PLAYER_PTS_AST),
        (" Total Steals & Blocks", MarketType.PLAYER_STEALS_BLOCKS),
        (": Team Total Points", MarketType.TEAM_TOTAL),
        (" Total Turnovers", MarketType.PLAYER_TURNOVERS),
        (" Total Rebounds", MarketType.PLAYER_REBOUNDS),
        (" Total Assists", MarketType.PLAYER_ASSISTS),
        (" Total Blocks", MarketType.PLAYER_BLOCKS),
        (" Total Points", MarketType.PLAYER_POINTS),
        (" Total Steals", MarketType.PLAYER_STEALS),
        (" Made Threes", MarketType.PLAYER_THREES),
        (" Rebounds", MarketType.PLAYER_REBOUNDS),
        (" Assists", MarketType.PLAYER_ASSISTS),
        (" Points", MarketType.PLAYER_POINTS),
    ],
)


_CRYPTO_GAME_CONTRACTS: dict[str, MarketType] = {
    "Moneyline": MarketType.MONEYLINE,
    "Spread": MarketType.POINT_SPREAD,
    "Total Points": MarketType.GAME_TOTAL,
}

_CRYPTO_PROPS: dict[str, MarketType] = {
    "Total Points": MarketType.PLAYER_POINTS,
    "Total Rebounds": MarketType.PLAYER_REBOUNDS,
    "Total Assists": MarketType.PLAYER_ASSISTS,
    "Total 3-Pointers Made": MarketType.PLAYER_THREES,
}

# Not in the WNBA feed (checked 2026-10-19), so WNBA and its Milestones
# copies leave them out. "First Field Goal Scorer" stays unmapped: Optic's
# first basket counts free throws.
_CRYPTO_NBA_PROPS: dict[str, MarketType] = {
    "Total Points, Rebounds, & Assists": MarketType.PLAYER_PTS_REB_AST,
    "Total Steals": MarketType.PLAYER_STEALS,
    "Total Blocks": MarketType.PLAYER_BLOCKS,
    "To Record a Double Double": MarketType.PLAYER_DOUBLE_DOUBLE,
}

# WNBA also publishes a "Milestones" variant of each prop contract.
_CRYPTO_WNBA_PROPS: dict[str, MarketType] = {
    **_CRYPTO_PROPS,
    **{f"{name} Milestones": mt for name, mt in _CRYPTO_PROPS.items()},
}

_CRYPTO_WNBA_PERIODS: dict[str, dict[str, MarketType]] = {
    "1st Half": {
        "Moneyline": MarketType.FIRST_HALF_MONEYLINE,
        "Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "Total Points": MarketType.FIRST_HALF_TOTAL,
    },
}

# NCAAB (crypto grouping "CBB"), checked against the live crypto_security_def
# feed 2026-10-31: periods are "1st Half" / "2nd Half" with the full-game
# contract strings; the half winner is "Moneyline (3-Way)" (Home / Away /
# Draw), no 2-way half Moneyline is listed.
_CRYPTO_NCAAB_PERIODS: dict[str, dict[str, MarketType]] = {
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
}


# NBA lists halves and quarters under the full-game contract strings
# (checked against crypto_underlying_securities 2026-11-05). The 2nd Half
# and 4th Quarter stay unmapped: Optic's plain markets stop at regulation
# and the venue's overtime treatment is not published.
_CRYPTO_NBA_PERIODS = {
    k: v for k, v in CRYPTO_PERIOD_LINES.items()
    if k not in ("2nd Half", "4th Quarter")
}

# "Team Total" is a Team Prop (one team, Over/Under); the team comes
# from the typed meta_team_id.
_CRYPTO_TEAM_PROPS: dict[str, MarketType] = {"Team Total": MarketType.TEAM_TOTAL}


def basketball_crypto_config(
    league: str,
    settings: Mapping[str, Any],
) -> CryptoConfig | None:
    """Build crypto.com config for NBA / NCAAB / WNBA from tip settings."""
    grouping = str(settings.get("sport_grouping") or "").strip()
    if not league or not grouping:
        return None
    is_wnba = grouping == "WNBA"
    periods = (
        _CRYPTO_WNBA_PERIODS if is_wnba
        else _CRYPTO_NCAAB_PERIODS if grouping == "CBB"
        else _CRYPTO_NBA_PERIODS if grouping == "NBA"
        else {}
    )
    return CryptoConfig(
        sport_grouping=grouping,
        league=league,
        period_type=str(settings.get("period_type") or "Full-Game"),
        contract_types=dict(_CRYPTO_GAME_CONTRACTS),
        period_contract_types={k: dict(v) for k, v in periods.items()},
        team_prop_period_type=None if is_wnba else "Full-Game",
        team_prop_contract_types={} if is_wnba else dict(_CRYPTO_TEAM_PROPS),
        prop_period_type=str(settings.get("prop_period_type") or "Full-Game"),
        prop_contract_types=dict(
            _CRYPTO_WNBA_PROPS if is_wnba else {**_CRYPTO_PROPS, **_CRYPTO_NBA_PROPS}),
    )


NBA_CRYPTO = cast(
    CryptoConfig,
    basketball_crypto_config("NBA", {"sport_grouping": "NBA", "period_type": "Full Game"}),
)
NCAAB_CRYPTO = cast(
    CryptoConfig,
    basketball_crypto_config("CBB", {"sport_grouping": "CBB", "period_type": "Full-Game"}),
)
WNBA_CRYPTO = cast(
    CryptoConfig,
    basketball_crypto_config("WNBA", {"sport_grouping": "WNBA", "period_type": "Full-Game"}),
)
