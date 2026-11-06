"""Polymarket US per-outcome enums whose outcome lives only in ``title``.

Titles are copied from the 2026-09-26 gateway snapshot. The stale-title
cases are real: a late opponent change left "V. Machado by …" on an Amaya
vs Black group and "Cardozo wins 2-0" on an Aguilar vs Barrena match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mappers.exchanges import polymarket_usa_structured as pus
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE

_YES_NO = [
    {"id": "y", "long": True, "description": "Yes"},
    {"id": "n", "long": False, "description": "No"},
]
_HIESTAND = {"id": "29622", "abbreviation": "brahie", "name": "Brady Hiestand"}
_NAKAMURA = {"id": "29619", "abbreviation": "rinnak", "name": "Rinya Nakamura"}
_POR = {"id": "501", "abbreviation": "por", "name": "Portugal"}
_ALB = {"id": "502", "abbreviation": "alb", "name": "Albania"}
_RUBLEV = {"id": "701", "abbreviation": "andrub", "name": "Andrey Rublev"}
_HURKACZ = {"id": "702", "abbreviation": "hubhur", "name": "Hubert Hurkacz"}


@dataclass
class _FX:
    fixture_id: str = "F1"
    home: str = "H"
    away: str = "A"
    home_name: str = "Brady Hiestand"
    away_name: str = "Rinya Nakamura"
    start_date: str = "2026-09-27T00:00:00Z"


def _market(smt: str, title: str, teams: list[dict[str, Any]]) -> pus.UsMarket:
    obj = {
        "inner": "x", "event_id": "1", "event_ticker": "evt",
        "event_start": "2026-09-27T00:00:00Z", "sportradar_game_id": "",
        "teams": teams, "market_id": "m1", "slug": f"astatc-{title}",
        "sports_market_type": smt, "line": None, "metadata": {},
        "sides": _YES_NO, "title": title,
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _bets(smt: str, title: str, teams: list[dict[str, Any]]) -> list[pus.Bet]:
    bind = pus.EventBind(
        fixture=_FX(), team_sides={t["id"]: s for t, s in zip(teams, ("H", "A"), strict=True)},
    )
    return pus.market_bets(_market(smt, title, teams), bind)


_FIGHT = [_HIESTAND, _NAKAMURA]
_MOV = MarketType.METHOD_OF_VICTORY.value
_MOF = MarketType.METHOD_OF_FINISH.value


def test_method_of_victory_is_fighter_plus_method_yes_only():
    smt = "ufc_method_of_victory"
    assert _bets(smt, "B. Hiestand by KO/TKO/DQ", _FIGHT) == [
        (_MOV, "H", None, "yes", "ko_tko_dq"),
    ]
    assert _bets(smt, "R. Nakamura by Decision", _FIGHT) == [
        (_MOV, "A", None, "yes", "decision"),
    ]
    assert _bets(smt, "R. Nakamura by Submission", _FIGHT) == [
        (_MOV, "A", None, "yes", "submission"),
    ]


def test_method_of_victory_drops_draw_stale_names_and_unknown_methods():
    smt = "ufc_method_of_victory"
    assert _bets(smt, "Draw", _FIGHT) == []  # Optic emits no MOV draw row
    assert _bets(smt, "V. Machado by Decision", _FIGHT) == []  # not on this card
    assert _bets(smt, "R. Hiestand by Decision", _FIGHT) == []  # initial mismatch
    assert _bets(smt, "B. Hiestand by KO/TKO", _FIGHT) == []  # not the venue's bucket
    assert _bets(smt, "Hiestand wins by Decision", _FIGHT) == []


def test_method_of_finish_is_the_bare_method():
    smt = "ufc_method_of_finish"
    assert _bets(smt, "Submission", _FIGHT) == [(_MOF, None, None, "yes", "submission")]
    assert _bets(smt, "KO/TKO/DQ", _FIGHT) == [(_MOF, None, None, "yes", "ko_tko_dq")]
    assert _bets(smt, "Decision", _FIGHT) == [(_MOF, None, None, "yes", "decision")]
    assert _bets(smt, "Draw", _FIGHT) == []


def test_soccer_exact_score_by_abbreviation_and_draw():
    smt, cs = "soccer_game_exact_score", MarketType.CORRECT_SCORE.value
    teams = [_POR, _ALB]
    assert _bets(smt, "POR wins 2-1", teams) == [(cs, None, 2.01, "H")]
    assert _bets(smt, "ALB wins 3-0", teams) == [(cs, None, 3.0, "A")]
    assert _bets(smt, "Draw 1-1", teams) == [(cs, None, 1.01, TIE_SIDE)]
    assert _bets(smt, "Other", teams) == []
    assert _bets(smt, "POR wins 1-2", teams) == []  # winner must lead
    assert _bets(smt, "Draw 2-1", teams) == []
    assert _bets(smt, "ESP wins 1-0", teams) == []
    # The period suffix must match the enum.
    assert _bets(smt, "POR wins 1-0 in 1st half", teams) == []


def test_soccer_first_half_exact_score_needs_the_suffix():
    smt, cs = "soccer_game_first_half_exact_score", MarketType.FIRST_HALF_CORRECT_SCORE.value
    teams = [_POR, _ALB]
    assert _bets(smt, "POR wins 2-0 in 1st half", teams) == [(cs, None, 2.0, "H")]
    assert _bets(smt, "Draw 0-0 in 1st half", teams) == [(cs, None, 0.0, TIE_SIDE)]
    assert _bets(smt, "Other in 1st half", teams) == []
    assert _bets(smt, "POR wins 2-0", teams) == []


def test_tennis_exact_score_by_surname():
    smt, cs = "tennis_match_exact_score", MarketType.CORRECT_SCORE.value
    teams = [_RUBLEV, _HURKACZ]
    assert _bets(smt, "Rublev wins 2-0", teams) == [(cs, None, 2.0, "H")]
    assert _bets(smt, "Hurkacz wins 2-1", teams) == [(cs, None, 2.01, "A")]
    assert _bets(smt, "Cardozo wins 2-0", teams) == []  # stale: not in this match
    assert _bets(smt, "Andrey wins 2-0", teams) == []  # given name is not a surname


def test_same_surname_on_both_sides_drops():
    smt = "tennis_match_exact_score"
    teams = [
        {"id": "1", "abbreviation": "a", "name": "Karolina Pliskova"},
        {"id": "2", "abbreviation": "b", "name": "Kristyna Pliskova"},
    ]
    assert _bets(smt, "Pliskova wins 2-0", teams) == []
    fight = [
        {"id": "1", "abbreviation": "a", "name": "Karolina Pliskova"},
        {"id": "2", "abbreviation": "b", "name": "Kristyna Pliskova"},
    ]
    assert _bets("ufc_method_of_victory", "K. Pliskova by Decision", fight) == []


def test_build_row_carries_the_method_as_grouping_key():
    teams = _FIGHT
    market = _market("ufc_method_of_victory", "B. Hiestand by Decision", teams)
    bind = pus.EventBind(fixture=_FX(), team_sides={"29622": "H", "29619": "A"})
    (bet,) = pus.market_bets(market, bind)
    row = pus.build_row(market, bind, bet, "ufc")
    assert (row.market_type, row.entity, row.side, row.grouping_key) == (
        _MOV, "H", "yes", "decision",
    )


def test_round_of_victory_keys_on_the_optic_fighter_name():
    smt, rb = "ufc_round_of_victory", MarketType.ROUND_BETTING.value
    assert _bets(smt, "Hiestand in Round 1", _FIGHT) == [
        (rb, None, None, "yes", "brady_hiestand_round_1"),
    ]
    assert _bets(smt, "Nakamura in Round 3", _FIGHT) == [
        (rb, None, None, "yes", "rinya_nakamura_round_3"),
    ]
    assert _bets(smt, "Decision / Draw / No Contest", _FIGHT) == []
    assert _bets(smt, "Machado in Round 1", _FIGHT) == []
    assert _bets(smt, "Hiestand in Round 6", _FIGHT) == []


def test_round_of_finish_is_to_start_round_with_sides_swapped():
    smt = "ufc_round_of_finish"
    assert _bets(smt, "Fight ends before Round 2 begins", _FIGHT) == [
        ("to_start_round_2", None, None, "no"),
        ("to_start_round_2", None, None, "yes"),
    ]
    assert _bets(smt, "Fight ends before Round 3 begins", _FIGHT)[0][0] == "to_start_round_3"
    assert _bets(smt, "Fight ends in Round 2", _FIGHT) == []
    assert _bets(smt, "Fight ends before Round 1 begins", _FIGHT) == []
