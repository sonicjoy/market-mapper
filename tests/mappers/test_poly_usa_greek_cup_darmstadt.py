"""Polymarket US: Greek Cup league id and three pinned club names.

Team shapes copied from live ``gateway.polymarket.us`` events and Optic
fixtures (2026-10-27), abbreviations included. Each pinned club's venue code
misses Optic's (``svd`` / ``D98``, ``paa`` / ``PAO``, ``nch`` / empty), so it
binds on the pinned name or not at all.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import mappers.pipeline  # noqa: F401 - settles the vocab/polymarket import cycle
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_leagues import us_league_ids

_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})
_KICKOFF = "2026-10-27T19:45:00Z"


def test_greek_cup_reads_its_gateway_league() -> None:
    assert us_league_ids(("greece_-_cup",)) == frozenset({280})


def _event(home: tuple[str, str], away: tuple[str, str]) -> pus.UsMarket:
    obj = {
        "league_id": 280, "event_id": "e1", "event_ticker": "evt", "event_start": _KICKOFF,
        "sportradar_game_id": "", "market_id": "m1", "slug": "m1",
        "sports_market_type": "soccer_team_full_time_winner", "line": None, "metadata": {},
        "sides": [], "teams": [{"id": "h", "abbreviation": home[0], "name": home[1]},
                               {"id": "a", "abbreviation": away[0], "name": away[1]}],
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


_Side = tuple[str, str] | tuple[str, str, str]


def _fx(home: _Side, away: _Side) -> SimpleNamespace:
    """(side key, Optic name[, Optic abbreviation]) per side; the abbreviation defaults to the key."""
    return SimpleNamespace(
        fixture_id="F", home=home[0], away=away[0], home_name=home[1], away_name=away[1],
        home_optic_abbr=home[2] if len(home) > 2 else home[0],
        away_optic_abbr=away[2] if len(away) > 2 else away[0],
        start_date=_KICKOFF, sportradar_id=None,
    )


@pytest.mark.parametrize("gw_home,gw_away,optic_home,optic_away", [
    (("elv", "SV 07 Elversberg"), ("svd", "SV Darmstadt 98"),
     ("ELV", "SV 07 Elversberg"), ("D98", "SV Darmstadt 1898")),
    (("paa", "Panathinaikos Athens"), ("aris", "Aris Thessaloniki"),
     ("PAO", "Panathinaikos FC"), ("ARI", "Aris Thessaloniki FC")),
    (("nch", "Nestos Chrysoupoli FC"), ("kal", "PAE PS Kalamata"),
     ("nestos", "AS Nestos Chrysoupolis", ""), ("KAL", "PS PAE Kalamata")),  # Optic has no abbreviation
])
def test_pinned_clubs_bind_their_fixture(gw_home, gw_away, optic_home, optic_away) -> None:
    bind, via = pus.bind_event(_event(gw_home, gw_away), [_fx(optic_home, optic_away)], _NO_ALIASES, set())
    assert via == "teams_kickoff" and bind is not None
    assert bind.team_sides == {"h": optic_home[0], "a": optic_away[0]}


def test_greek_cup_unpinned_pairs_bind_on_their_own() -> None:
    """The other cup ties need no pin: Asteras–Kifisia binds on codes and names as listed."""
    m = _event(("ast", "Asteras Tripolis"), ("kif", "AE Kifisia FC"))
    fx = _fx(("AST", "Asteras Tripolis FC"), ("KIF", "Kifisias FC"))
    bind, via = pus.bind_event(m, [fx], _NO_ALIASES, set())
    assert via == "teams_kickoff" and bind is not None
