"""Poly US sub-markets wired 2026-09-27, checked against the Optic rows they land on.

Each case builds the venue bet (``market_bets``) and the Optic row
(``optic.build_rows``) for the same outcome and asserts their merge keys
agree. Shapes are copied from the 2026-09-26 gateway / Optic snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# polymarket first: esports_markets <-> polymarket import cycle.
from mappers.exchanges import polymarket  # noqa: F401
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.optic import Fixture, Odd, OpticConfig, build_rows
from mappers.market_types import MarketType as M
from mappers.shared import TIE_SIDE
from mappers.vocab.esports_markets import ESPORTS_OPTIC_TABLE_TYPES
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES

_YES_NO = [
    {"id": "y", "long": True, "description": "Yes"},
    {"id": "n", "long": False, "description": "No"},
]
_ARI = {"id": "48", "abbreviation": "ari", "name": "Arizona Cardinals"}
_NYG = {"id": "71", "abbreviation": "nyg", "name": "New York Giants"}


@dataclass
class _FX:
    fixture_id: str = "F1"
    home: str = "NYG"
    away: str = "ARI"
    home_name: str = "New York Giants"
    away_name: str = "Arizona Cardinals"
    start_date: str = "2026-10-04T17:00:00Z"


_BIND = pus.EventBind(fixture=_FX(), team_sides={"71": "NYG", "48": "ARI"})


def _market(
    smt: str, title: str = "", *, sides: list[dict[str, Any]] | None = None,
    line: float | None = None, metadata: dict[str, Any] | None = None,
) -> pus.UsMarket:
    obj = {
        "inner": "nfl", "event_id": "1", "event_ticker": "evt",
        "event_start": "2026-10-04T17:00:00Z", "sportradar_game_id": "",
        "teams": [_ARI, _NYG], "market_id": "m1", "slug": "astatc-x",
        "sports_market_type": smt, "line": line, "metadata": metadata or {},
        "sides": sides or _YES_NO, "title": title,
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _optic_keys(table: dict, odds: list[Odd]) -> set[tuple]:
    fx = Fixture(
        fixture_id="F1", game_id="G1", sportradar_id=None,
        start_et="2026-10-04T13:00:00", start_date="2026-10-04T17:00:00Z",
        home="NYG", away="ARI", home_name="New York Giants",
        away_name="Arizona Cardinals", team_map={"T_NYG": "NYG", "T_ARI": "ARI"},
        odds=odds, is_live=False,
    )
    rows, _, _ = build_rows(
        fx.start_date, "NYG", "ARI", fx,
        OpticConfig(league_id="x", table_types=dict(table)), league="nfl",
    )
    return {(r.market_type, r.entity, r.line, r.side, r.grouping_key) for r in rows}


def _odd(market_id: str, selection: str, **kw: Any) -> Odd:
    norm = kw.pop("normalized", selection.casefold().replace(" ", "_"))
    return Odd(
        id=f"F1:{market_id}:{selection}", market_id=market_id, selection=selection,
        normalized_selection=norm, grouping_key="default", **kw,
    )


def _key(bet: tuple) -> tuple:
    return (*bet[:4], bet[4] if len(bet) == 5 else None)


_FB = FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
_ES = ESPORTS_OPTIC_TABLE_TYPES


def test_double_result_lands_on_optic_halftime_fulltime():
    smt = "football_game_double_result"
    optic = _optic_keys(_FB, [
        _odd("halftime_fulltime", "Arizona Cardinals :: New York Giants"),
        _odd("halftime_fulltime", "Draw :: Draw"),
        _odd("halftime_fulltime", "Draw :: Arizona Cardinals"),
    ])
    for title in ("ARI 1H / NYG Game", "1H Tie / Tie", "1H Tie / ARI Game"):
        (bet,) = pus.market_bets(_market(smt, title), _BIND)
        assert _key(bet) in optic, title
    (bet,) = pus.market_bets(_market(smt, "ARI 1H / Tie"), _BIND)
    assert _key(bet) == (M.HALFTIME_FULLTIME.value, None, None, "yes", f"ARI|{TIE_SIDE}")


def test_double_result_drops_unknown_codes_and_other_wordings():
    smt = "football_game_double_result"
    for title in ("DAL 1H / NYG Game", "ARI 1H / NYG", "ARI leads / NYG Game", "Other"):
        assert pus.market_bets(_market(smt, title), _BIND) == [], title


def test_highest_scoring_quarter_is_one_yes_per_quarter():
    smt = "football_game_highest_scoring_quarter"
    optic = _optic_keys(_FB, [_odd("highest_scoring_quarter", "3rd Quarter")])
    (bet,) = pus.market_bets(_market(smt, "3rd Quarter"), _BIND)
    assert _key(bet) in optic
    assert pus.market_bets(_market(smt, "Tie"), _BIND) == []
    assert pus.market_bets(_market(smt, "5th Quarter"), _BIND) == []


def test_safety_and_two_point_conversion_only_at_half_a_point():
    for smt, optic_id in (
        ("football_game_safety", "will_there_be_a_safety"),
        ("football_game_total_two_point_conversions", "successful_2_point_conversion"),
    ):
        optic = _optic_keys(_FB, [_odd(optic_id, "Yes"), _odd(optic_id, "No")])
        bets = pus.market_bets(_market(smt, line=0.5), _BIND)
        assert {_key(b) for b in bets} == optic
        assert pus.market_bets(_market(smt, line=1.5), _BIND) == []


def test_second_half_first_score_is_the_team_yes_only():
    smt = "football_game_second_half_first_score"
    optic = _optic_keys(_FB, [_odd("2nd_half_first_team_to_score", "Arizona Cardinals",
                                   team_id="T_ARI")])
    sides = [{**s, "team_id": "48"} for s in _YES_NO]
    (bet,) = pus.market_bets(_market(smt, sides=sides), _BIND)
    assert _key(bet) in optic
    assert pus.market_bets(_market(smt), _BIND) == []  # the "neither" leg


def test_most_passing_yards_is_the_player_yes():
    smt = "football_player_most_passing_yards"
    optic = _optic_keys(_FB, [_odd("most_passing_yards_player", "Jaxson Dart",
                                   player_id="P1")])
    (bet,) = pus.market_bets(_market(smt, metadata={"playerName": "Jaxson Dart"}), _BIND)
    assert _key(bet) in optic


def test_esports_per_map_markets():
    handicap = [
        {"id": "a", "long": True, "description": "-2.50", "team_id": "48"},
        {"id": "b", "long": False, "description": "+2.50", "team_id": "71"},
    ]
    optic = _optic_keys(_ES, [
        _odd("2nd_map_round_handicap", "Arizona Cardinals", team_id="T_ARI", points=-2.5),
        _odd("2nd_map_round_handicap", "New York Giants", team_id="T_NYG", points=2.5),
    ])
    bets = pus.market_bets(
        _market("esports_map_rounds_handicap_2", sides=handicap, line=-2.5), _BIND)
    assert {_key(b) for b in bets} == optic

    over_under = [
        {"id": "o", "long": True, "description": "Over"},
        {"id": "u", "long": False, "description": "Under"},
    ]
    optic = _optic_keys(_ES, [
        _odd("1st_map_total_rounds", "", selection_line="over", points=21.5),
        _odd("1st_map_total_rounds", "", selection_line="under", points=21.5),
    ])
    bets = pus.market_bets(
        _market("esports_map_total_rounds_1", sides=over_under, line=21.5), _BIND)
    assert {_key(b) for b in bets} == optic

    optic = _optic_keys(_ES, [_odd("3rd_map_team_first_blood", "New York Giants",
                                   team_id="T_NYG")])
    sides = [{**s, "team_id": "71"} for s in _YES_NO]
    (bet,) = pus.market_bets(_market("esports_game_first_blood_3", sides=sides), _BIND)
    assert _key(bet) in optic


def test_kills_odd_even_both_sides_and_map_number_must_agree():
    optic = _optic_keys(_ES, [
        _odd("2nd_map_total_kills_odd_even", "Odd"),
        _odd("2nd_map_total_kills_odd_even", "Even"),
    ])
    for title in ("Odd total kills in game 2", "Game 2 Total Kills Odd"):
        bets = pus.market_bets(_market("esports_game_kills_odd_even_2", title), _BIND)
        assert {_key(b) for b in bets} == optic
    assert pus.market_bets(
        _market("esports_game_kills_odd_even_2", "Odd total kills in game 3"), _BIND) == []
    assert pus.market_bets(
        _market("esports_game_kills_odd_even_2", "Even total kills in game 2"), _BIND) == []
