"""Polymarket US soccer player props count extra time; Optic's player markets do not.

Every soccer player prop on the venue reads, since 2026-10-21: "Extra time is
included if played. Penalty shootouts are not included if played." Optic's
``player_goals`` / ``player_assists`` / ``first_goal_scorer`` … settle on 90
minutes plus stoppage. The two agree only where extra time cannot be played,
so a player prop maps only on such a fixture. Anywhere else it stays unmapped
and Optic's own passthrough onto the 90-minute market is stripped: Optic lists
``*_incl_et`` twins, but no book quoted one on the eight knockout fixtures
probed on 2026-10-21. Team markets are unaffected; the venue still settles them
on 90 minutes plus stoppage. Terms: docs/polymarket-us-contract-terms.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mappers.market_types import MarketType, Scope

# Optic (league id → season_type labels) whose matches cannot go to extra time.
# A league or label not listed counts as "extra time possible" (missing beats
# wrong), so a new stage label (playoffs, a relegation tie) unmaps props until
# someone checks its format and lists it here. Labels as Optic's
# /fixtures/active returned them on 2026-10-21.
REGULATION_ONLY_STAGES: dict[str, frozenset[str]] = {
    # Domestic league rounds; a draw stands.
    "england_-_premier_league": frozenset({"Regular Season"}),
    "spain_-_la_liga": frozenset({"Regular Season"}),
    "germany_-_bundesliga": frozenset({"Regular Season"}),
    "italy_-_serie_a": frozenset({"Regular Season"}),
    "france_-_ligue_1": frozenset({"Regular Season"}),
    "usa_-_major_league_soccer": frozenset({"Regular Season"}),
    # Liga MX regular phase; the Liguilla arrives as "Quarterfinals" etc.
    "mexico_-_liga_mx": frozenset({"Apertura", "Clausura"}),
    # UEFA league phase (Optic: "Group Stage"); knockout rounds are not listed.
    "uefa_-_champions_league": frozenset({"Group Stage"}),
    "uefa_-_europa_league": frozenset({"Group Stage"}),
    "uefa_-_europa_conference_league": frozenset({"Group Stage"}),
    # Nations League league phase, one label per league (A–D).
    "uefa_-_nations_league": frozenset({"Group A", "Group B", "Group C", "Group D"}),
}

# Optic markets books list only around a tie that can be settled after 90'.
_TIE_MARKET = "to_advance"


def _ties_quoted(fx: Any) -> bool:
    """True when any odd on the fixture is a to-advance or extra-time market."""
    for odd in getattr(fx, "odds", None) or ():
        mid = str(getattr(odd, "market_id", "") or "")
        if mid == _TIE_MARKET or mid.endswith("_incl_et") or mid.startswith("extra_time_"):
            return True
    return False


def extra_time_possible(fx: Any) -> bool:
    """False only for a listed league stage with no tie market quoted on it."""
    stages = REGULATION_ONLY_STAGES.get(str(getattr(fx, "league_id", "") or ""))
    if not stages or str(getattr(fx, "season_type", "") or "") not in stages:
        return True
    return _ties_quoted(fx)


def blocks_player_prop(sports_market_type: str, fx: Any) -> bool:
    """True for a soccer player prop on a fixture that may reach extra time."""
    return (sports_market_type or "").startswith("soccer_player_") and extra_time_possible(fx)


def held_fixture_keys(fixtures: Iterable[Any]) -> frozenset[tuple[str, str, str]]:
    """(start_date, home, away) of the soccer fixtures whose player props are held."""
    return frozenset((fx.start_date, fx.home, fx.away) for fx in fixtures if extra_time_possible(fx))


def is_player_type(market_type: str) -> bool:
    """True for a player-scope canonical market type."""
    try:
        return MarketType(market_type).scope is Scope.PLAYER
    except ValueError:
        return False
