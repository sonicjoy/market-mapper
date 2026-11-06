"""Polymarket US: basketball periods, MLB inning totals, pinned club names.

Shapes copied from live ``gateway.polymarket.us`` payloads (2026-10-19).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import mappers.pipeline  # noqa: F401 - settles the vocab/polymarket import cycle
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.market_types import MarketType as M
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.poly_usa_smt import smt_spec

_BOS = {"id": "1", "abbreviation": "bos", "name": "Boston Celtics"}
_DET = {"id": "2", "abbreviation": "det", "name": "Detroit Pistons"}
_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})


def _market(smt: str, sides: list[dict[str, Any]], line: float | None,
            teams: list[dict[str, Any]] | None = None, start: str = "2026-10-20T19:00:00Z",
            ) -> pus.UsMarket:
    obj = {
        "league_id": 2, "event_id": "e1", "event_ticker": "evt", "event_start": start,
        "sportradar_game_id": "", "teams": teams or [_BOS, _DET], "market_id": "m1",
        "slug": "m1", "sports_market_type": smt, "line": line, "metadata": {},
        "sides": sides,
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _bind() -> pus.EventBind:
    fx = SimpleNamespace(home="DET", away="BOS", fixture_id="F")
    return pus.EventBind(fixture=fx, team_sides={"1": "BOS", "2": "DET"})


def _yn(team: str = "") -> list[dict[str, Any]]:
    extra = {"team_id": team} if team else {}
    return [{"id": "a", "long": True, "description": "Yes", **extra},
            {"id": "b", "long": False, "description": "No", **extra}]


@pytest.mark.parametrize("smt,mt,kind", [
    ("basketball_team_total_points", M.TEAM_TOTAL, "team_total"),
    ("basketball_team_total_points_first_half", M.FIRST_HALF_TEAM_TOTAL, "team_total"),
    ("basketball_team_total_points_second_half", M.SECOND_HALF_TEAM_TOTAL_INCL_OT, "team_total"),
    ("basketball_team_first_half_total", M.FIRST_HALF_TOTAL, "total"),
    ("basketball_team_first_half_spread", M.FIRST_HALF_POINT_SPREAD, "spread"),
    ("basketball_team_first_quarter_spread", M.FIRST_QUARTER_POINT_SPREAD, "spread"),
    ("basketball_team_fourth_quarter_total", M.FOURTH_QUARTER_TOTAL, "total"),
    ("basketball_game_overtime", M.WILL_THERE_BE_OVERTIME, "game_yn"),
    ("baseball_team_inning1_total", M.FIRST_INNING_TOTAL, "total"),
    ("baseball_team_inning5_total", M.INNING_5_TOTAL, "total"),
    ("baseball_team_inning9_total", M.INNING_9_TOTAL, "total"),
])
def test_smt_wired(smt: str, mt: M, kind: str) -> None:
    assert smt_spec(smt) == (mt, kind)


def test_every_wired_period_type_has_an_optic_side() -> None:
    """A MarketType no Optic table loads has no selection to bind onto."""
    optic_types = set(BASKETBALL_OPTIC_TABLE_TYPES.values())
    for smt in ("basketball_team_total_points", "basketball_team_first_half_total",
                "basketball_team_fourth_quarter_spread", "basketball_game_overtime",
                "basketball_team_third_quarter_total"):
        spec = smt_spec(smt)
        assert spec is not None and spec[0] in optic_types


def test_basketball_team_total_names_the_team_entity() -> None:
    m = _market("basketball_team_total_points", [
        {"id": "a", "long": True, "description": "Yes", "team_id": "1"},
        {"id": "b", "long": False, "description": "No", "team_id": "1"}], 100.5)
    assert pus.market_bets(m, _bind()) == [
        ("team_total", "BOS", 100.5, "over"), ("team_total", "BOS", 100.5, "under"),
    ]


def test_basketball_combined_half_total_has_no_team() -> None:
    sides = [{"id": "a", "long": True, "description": "Over"},
             {"id": "b", "long": False, "description": "Under"}]
    m = _market("basketball_team_first_half_total", sides, 106.5)
    assert pus.market_bets(m, _bind()) == [
        ("1h_total", None, 106.5, "over"), ("1h_total", None, 106.5, "under"),
    ]


def test_basketball_overtime_yes_no() -> None:
    m = _market("basketball_game_overtime", _yn(), 0.5)
    assert pus.market_bets(m, _bind()) == [
        ("will_there_be_overtime", None, None, "yes"),
        ("will_there_be_overtime", None, None, "no"),
    ]


def test_inning_total_over_under_at_half_line() -> None:
    sides = [{"id": "a", "long": True, "description": "Over"},
             {"id": "b", "long": False, "description": "Under"}]
    m = _market("baseball_team_inning5_total", sides, 0.5)
    assert pus.market_bets(m, _bind()) == [
        ("i5_total", None, 0.5, "over"), ("i5_total", None, 0.5, "under"),
    ]


def _fx(home: str, away: str) -> SimpleNamespace:
    return SimpleNamespace(
        fixture_id="F", home=home[:3].upper(), away=away[:3].upper(),
        home_name=home, away_name=away, start_date="2026-10-19T17:00:00Z",
        sportradar_id=None, home_optic_abbr="", away_optic_abbr="",
    )


@pytest.mark.parametrize("gw_home,gw_away,optic_home,optic_away", [
    ("Trabzonspor", "Beşiktaş JK", "Trabzonspor Kulübü", "Beşiktaş Jimnastik Kulübü"),
    ("Boluspor", "Van Spor FK", "Boluspor Kulübü", "Van Spor Futbol Kulübü"),
    ("LKP Motor Lublin", "Zaglebie Lubin", "Motor Lublin SA", "KGHM Zagłębie Lubin"),
    ("FK Rodina Moskva", "FK Orenburg", "Rodina Moscow", "FK Orenburg"),
    ("El Ahly SC", "El Qanah Club", "Al Ahly FC", "Alqana"),
])
def test_pinned_club_names_bind_the_event(gw_home, gw_away, optic_home, optic_away) -> None:
    teams = [{"id": "a", "abbreviation": "zzz", "name": gw_home},
             {"id": "b", "abbreviation": "yyy", "name": gw_away}]
    m = _market("soccer_team_full_time_winner", [], None, teams=teams,
                start="2026-10-19T17:00:00Z")
    bind, via = pus.bind_event(m, [_fx(optic_home, optic_away)], _NO_ALIASES, set())
    assert via == "teams_kickoff" and bind is not None
    assert set(bind.team_sides) == {"a", "b"}


def test_unpinned_name_still_does_not_bind() -> None:
    """The table is exact pairs: a near name that is not pinned stays unmapped."""
    teams = [{"id": "a", "abbreviation": "zzz", "name": "Beşiktaş Spor"},
             {"id": "b", "abbreviation": "yyy", "name": "Trabzonspor"}]
    m = _market("soccer_team_full_time_winner", [], None, teams=teams,
                start="2026-10-19T17:00:00Z")
    fx = _fx("Trabzonspor Kulübü", "Beşiktaş Jimnastik Kulübü")
    assert pus.bind_event(m, [fx], _NO_ALIASES, set())[0] is None
