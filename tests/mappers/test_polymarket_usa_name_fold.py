"""PolyUS UEL Lillestrøm v Real Sociedad (2026-10-22): the ø kept both teams unbound.

Gateway records trimmed from prod ``raw_ingestion_us.polymarket_usa_fetch_raw``
(snapshot 2026-10-22T10:00). With "Lillestrøm" read as ``Lillestr`` + ``m``
neither team fit Optic's sides, the event bound by passthrough alone with no
team sides, and the per-team ``atc`` symbols got no YES row (259,648 RFQ legs
unmapped that day). One fitting team now binds the other by elimination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_sides import venue_side

_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})
_LSK_RSO_FIXTURE = "20261022FC16F236"
_TEAMS = [
    {"abbreviation": "lms", "id": "17673", "league": "uel", "name": "Lillestrøm SK",
     "sportradar_id": "sr:competitor:664"},
    {"abbreviation": "rsss", "alias": "Real Sociedad San Sebastian", "id": "30642",
     "league": "uel", "name": "Real Sociedad San Sebastian",
     "safe_name": "Real Sociedad San Sebastian", "sportradar_id": "sr:competitor:2824"},
]


@dataclass
class _FX:
    fixture_id: str = _LSK_RSO_FIXTURE
    home: str = "LSK"
    away: str = "RSO"
    home_name: str = "Lillestrom SK"
    away_name: str = "Real Sociedad de Fútbol"
    start_date: str = "2026-10-22T19:00:00Z"
    sportradar_id: str | None = None
    home_optic_abbr: str = "LSK"
    away_optic_abbr: str = "RSO"


def _atc(slug: str, market_id: str, team_id: str) -> pus.UsMarket:
    obj: dict[str, Any] = {
        "event_id": "157281", "event_start": "2026-10-22T19:00:00Z",
        "event_ticker": "uel-lms-rsss-2026-10-22", "league_id": 106, "line": None,
        "market_id": market_id, "metadata": {}, "slug": slug,
        "sportradar_game_id": "sr:sport_event:74173012",
        "sports_market_type": "soccer_team_full_time_winner", "teams": _TEAMS,
        "sides": [
            {"description": "Yes", "id": f"{market_id}-y", "long": True, "team_id": team_id},
            {"description": "No", "id": f"{market_id}-n", "long": False, "team_id": team_id},
        ],
    }
    market = pus.parse_market(obj)
    assert market is not None
    return market


_RSSS = _atc("atc-uel-lms-rsss-2026-10-22-rsss", "1401632", "30642")
_LMS = _atc("atc-uel-lms-rsss-2026-10-22-lms", "1401630", "17673")
_DRAW = _atc("atc-uel-lms-rsss-2026-10-22-draw", "1401631", "")


def test_lillestrom_binds_despite_the_o_slash():
    team = next(t for t in _RSSS.teams if t.team_id == "17673")
    assert pus.team_side(team, _FX(), _NO_ALIASES, person=False) == "LSK"


def test_event_binds_both_teams_by_elimination():
    bind, via = pus.bind_event(_RSSS, [_FX()], _NO_ALIASES, {_LSK_RSO_FIXTURE})
    assert via == "optic_passthrough"
    assert bind is not None
    assert bind.team_sides == {"17673": "LSK", "30642": "RSO"}


def test_team_symbols_price_their_team_on_the_yes_side():
    bind, _ = pus.bind_event(_RSSS, [_FX()], _NO_ALIASES, {_LSK_RSO_FIXTURE})
    assert bind is not None
    draws = pus.draw_market_ids([_RSSS, _LMS, _DRAW])
    for market, team in ((_RSSS, "RSO"), (_LMS, "LSK")):
        bets = pus.market_bets(market, bind, draws)
        assert bets == [("moneyline_3way", None, None, team)]
        assert venue_side(market, bind, bets[0]) == "yes"
