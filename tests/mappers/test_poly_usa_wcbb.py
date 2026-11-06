"""Polymarket US: women's college basketball (WCBB) maps onto Optic ``ncaaw``.

Team shapes copied from live ``gateway.polymarket.us`` WCBB events and Optic
``ncaaw`` fixtures (2026-11-03). The gateway suffixes every team "(W)".
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import mappers.pipeline  # noqa: F401 - settles the vocab/polymarket import cycle
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_leagues import us_league_ids

_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})
_KICKOFF = "2026-11-06T00:00:00Z"


def test_ncaaw_reads_the_wcbb_gateway_league() -> None:
    assert us_league_ids(("ncaaw",)) == frozenset({17})


def test_men_and_women_stay_on_separate_gateway_leagues() -> None:
    assert us_league_ids(("ncaab",)) == frozenset({4})


def _event(home: tuple[str, str], away: tuple[str, str]) -> pus.UsMarket:
    obj = {
        "league_id": 17,
        "event_id": "e1",
        "event_ticker": "evt",
        "event_start": _KICKOFF,
        "sportradar_game_id": "",
        "market_id": "m1",
        "slug": "m1",
        "sports_market_type": "basketball_team_full_game_winner",
        "line": None,
        "metadata": {},
        "sides": [],
        "teams": [
            {"id": "h", "abbreviation": home[0], "name": home[1]},
            {"id": "a", "abbreviation": away[0], "name": away[1]},
        ],
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _fx(home: tuple[str, str], away: tuple[str, str], start: str = _KICKOFF) -> SimpleNamespace:
    return SimpleNamespace(
        fixture_id="F",
        home=home[0],
        away=away[0],
        home_name=home[1],
        away_name=away[1],
        home_optic_abbr=home[0],
        away_optic_abbr=away[0],
        start_date=start,
        sportradar_id=None,
    )


def test_wcbb_event_binds_its_optic_fixture() -> None:
    m = _event(("drexel", "Drexel (W)"), ("penn", "Penn (W)"))
    fx = _fx(("PENN", "Pennsylvania"), ("DREX", "Drexel"))
    bind, via = pus.bind_event(m, [fx], _NO_ALIASES, set())
    assert via == "teams_kickoff" and bind is not None
    assert bind.team_sides == {"h": "DREX", "a": "PENN"}


def test_placeholder_optic_kickoff_stays_unbound() -> None:
    """Optic files some WCBB games at a 05:00Z placeholder; no kickoff, no bind."""
    m = _event(("gmsn", "George Mason (W)"), ("mary", "Maryland (W)"))
    fx = _fx(("MD", "Maryland"), ("GMU", "George Mason"), start="2026-11-08T05:00:00Z")
    assert pus.bind_event(m, [fx], _NO_ALIASES, set())[0] is None
