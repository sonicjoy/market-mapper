"""Soccer anytime goalscorer: ``player_goals`` over 0.5 is its own market.

Every venue prices "to score anytime" as a 0.5 line on the goals ladder (or,
on Optic, as ``anytime_goal_scorer``).  One yes/no question per player has no
line, so the canonical row is ``anytime_goal_scorer`` (line None, side
yes).  The "no" leg stays on ``player_goals`` under 0.5, and the 1.5 / 2.5
rungs stay on ``player_goals``.  Rewriting at the row keeps every venue and
Optic on the same key without per-venue rules.

Soccer only: hockey's ``player_goals`` ladder is a different product.
"""

from __future__ import annotations

from mappers.market_types import MarketType
from mappers.sport import Sport, sport_for_league

_ANYTIME_LINE = 0.5
_AFFIRMATIVE_SIDES = frozenset({"over", "yes"})


def fold_anytime_goalscorer(
    league: str, market_type: str, line: float | None, side: str,
) -> tuple[str, float | None, str] | None:
    """(market_type, line, side) of the anytime row, or None when not one."""
    if market_type != MarketType.PLAYER_GOALS.value or line != _ANYTIME_LINE:
        return None
    if sport_for_league(league) != Sport.SOCCER:
        return None
    if side not in _AFFIRMATIVE_SIDES:
        return None
    return MarketType.ANYTIME_GOAL_SCORER.value, None, "yes"
