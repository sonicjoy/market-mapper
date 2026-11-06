"""NFL Huddle marketCode → Optic MarketType (1-1 only).

Unknown codes and ``*_EXC_OT`` are dropped (missing > wrong). Period 2–4
and 2H spreads have no Optic id in the NFL extras table.
"""

from __future__ import annotations

from mappers.market_types import MarketType, Shape

# huddle_us.event_mapping competitionId for NFL (probed 2026-09-21).
NFL_COMPETITION_ID = "6b3e9b3b-0b2d-4a1f-bb0d-4e87ad704738"

GAME_TYPES: dict[str, MarketType] = {
    "RESULT": MarketType.MONEYLINE,
    "POINT_HANDICAP": MarketType.POINT_SPREAD,
    "POINT_OVER_UNDER": MarketType.GAME_TOTAL,
    "TEAM_POINT_OVER_UNDER": MarketType.TEAM_TOTAL,
    "TEAM_TOUCHDOWN_OVER_UNDER": MarketType.TEAM_TOTAL_TOUCHDOWNS,
    "TEAM_FIELD_GOAL_OVER_UNDER": MarketType.TEAM_TOTAL_FIELD_GOALS,
    "TOUCHDOWN_OVER_UNDER": MarketType.TOTAL_TOUCHDOWNS,
    "TO_GO_TO_OVERTIME": MarketType.WILL_THERE_BE_OVERTIME,
    "POINT_RACE_TO_X": MarketType.RACE_TO_POINTS,
    "PLAYER_PASSING_YARDS_OVER_UNDER": MarketType.PLAYER_PASSING_YARDS,
    "PLAYER_PASSING_ATTEMPTS_OVER_UNDER": MarketType.PLAYER_PASSING_ATTEMPTS,
    "PLAYER_PASSING_COMPLETIONS_OVER_UNDER": MarketType.PLAYER_PASSING_COMPLETIONS,
    "PLAYER_PASSING_TOUCHDOWNS_OVER_UNDER": MarketType.PLAYER_PASSING_TOUCHDOWNS,
    "PLAYER_RECEIVING_YARDS_OVER_UNDER": MarketType.PLAYER_RECEIVING_YARDS,
    "PLAYER_RECEPTIONS_OVER_UNDER": MarketType.PLAYER_RECEPTIONS,
    "PLAYER_RUSHING_YARDS_OVER_UNDER": MarketType.PLAYER_RUSHING_YARDS,
    "PLAYER_RUSHING_ATTEMPTS_OVER_UNDER": MarketType.PLAYER_RUSHING_ATTEMPTS,
    "PLAYER_LONGEST_RECEPTION_YARDS": MarketType.PLAYER_LONGEST_RECEPTION,
    "PLAYER_LONGEST_RUSH_YARDS": MarketType.PLAYER_LONGEST_RUSH,
    "PLAYER_LONGEST_COMPLETION_YARDS": MarketType.PLAYER_LONGEST_PASSING_COMPLETION,
    "PLAYER_FIRST_TOUCHDOWN_SCORER": MarketType.FIRST_TOUCHDOWN_SCORER,
}

HALF1_TYPES: dict[str, MarketType] = {
    "HALF_RESULT": MarketType.FIRST_HALF_WINNER_3WAY,
    "HALF_POINT_HANDICAP": MarketType.FIRST_HALF_POINT_SPREAD,
    "HALF_POINT_OVER_UNDER": MarketType.FIRST_HALF_TOTAL,
    "TEAM_HALF_POINT_OVER_UNDER": MarketType.FIRST_HALF_TEAM_TOTAL,
}

HALF2_TYPES: dict[str, MarketType] = {
    "HALF_RESULT": MarketType.SECOND_HALF_WINNER_3WAY,
    "HALF_POINT_OVER_UNDER": MarketType.SECOND_HALF_TOTAL,
    "TEAM_HALF_POINT_OVER_UNDER": MarketType.SECOND_HALF_TEAM_TOTAL,
}

PERIOD1_TYPES: dict[str, MarketType] = {
    "PERIOD_RESULT": MarketType.FIRST_QUARTER_WINNER_3WAY,
    "PERIOD_POINT_HANDICAP": MarketType.FIRST_QUARTER_POINT_SPREAD,
    "PERIOD_POINT_OVER_UNDER": MarketType.FIRST_QUARTER_TOTAL,
}

EXC_OT_CODES: frozenset[str] = frozenset({
    "POINT_OVER_UNDER_EXC_OT",
    "POINT_HANDICAP_EXC_OT",
    "HALF_POINT_OVER_UNDER_EXC_OT",
    "HALF_POINT_HANDICAP_EXC_OT",
    "PERIOD_POINT_OVER_UNDER_EXC_OT",
    "PERIOD_POINT_HANDICAP_EXC_OT",
    "TEAM_PERIOD_POINT_OVER_UNDER_EXC_OT",
    "RESULT_EXC_OT",
    "PERIOD_RESULT_EXC_OT",
    "POINT_MARGIN_EXC_OT",
    "PERIOD_POINT_ODD_EVEN_EXC_OT",
})


def is_exc_ot(market_code: str) -> bool:
    """True when Huddle priced the selection excluding overtime."""
    return market_code.endswith("_EXC_OT") or market_code in EXC_OT_CODES


def _null_zero(value: float | None) -> float | None:
    """Treat period/half ``0`` as unset (feed sentinel, not Q1 / 1H)."""
    if value is None:
        return None
    return None if float(value) == 0.0 else value


def resolve_market_type(
    market_code: str,
    *,
    half: float | None,
    period: float | None,
    table_types: dict[str, MarketType],
) -> MarketType | None:
    """Return the Optic type for this code+period, or None to drop."""
    if is_exc_ot(market_code):
        return None
    period = _null_zero(period)
    half = _null_zero(half)
    if period is not None and float(period) != 1.0:
        return None
    if half is not None and float(half) == 2.0:
        return HALF2_TYPES.get(market_code)
    if half is not None and float(half) == 1.0:
        return HALF1_TYPES.get(market_code)
    if period is not None:
        return PERIOD1_TYPES.get(market_code)
    return table_types.get(market_code) or GAME_TYPES.get(market_code)


def needs_three_way(mt: MarketType) -> bool:
    """True when Optic's selection set includes Draw / Neither."""
    return mt.shape == Shape.THREE_WAY
