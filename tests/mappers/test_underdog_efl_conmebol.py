"""Underdog EFL Championship / League One and CONMEBOL Libertadores / Sudamericana (live 2026-10-14)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.shared import TIE_SIDE
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport
from tests.mappers.test_tip_leagues import _row

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_efl_conmebol_2026-10-14.json"
_LIVE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_OPTIC_LEAGUE = {
    "england_championship": "england_-_championship",
    "england_league_1": "england_-_league_1",
    "conmebol_copa_libertadores": "conmebol_-_copa_libertadores",
    "conmebol_sudamericana": "conmebol_-_copa_sudamericana",
}


def _entry(optic: dict) -> SimpleNamespace:
    """The Optic fixture as captured: real names, kickoff, and competitor ids for the witness."""
    return SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=optic["fixture_id"], home="HOM", away="AWY",
        home_name=optic["home_name"], away_name=optic["away_name"], start_date=optic["start_date"],
        team_map={optic["home_id"]: "HOM", optic["away_id"]: "AWY"}, odds=[],
    ))


@pytest.mark.parametrize("league", sorted(_OPTIC_LEAGUE))
def test_league_maps_underdog_though_the_tip_pins_none(league: str) -> None:
    run = resolve_run_leagues({}, [_row(league, optic=_OPTIC_LEAGUE[league])])
    cfg = run[league].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["moneyline"] is MarketType.MONEYLINE_3WAY


@pytest.mark.parametrize("league", sorted(_LIVE))
def test_every_live_contract_stamps_on_the_venue_fixture_and_team(league: str) -> None:
    event = _LIVE[league]
    entry = _entry(event["optic"])
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league=league.upper(), market_types=market_types_for_sport(Sport.SOCCER))
    tally = run_pass(
        event["rows"], cfg, [entry], league=league,
        attach=attach, row_index={}, all_rows=[],
    )
    assert tally["stamped"] == len(stamped)
    assert {r.underdog_ticker for r in stamped} == {r["ticker"] for r in event["rows"]}
    venue = {r["ticker"]: r["external_ids"]["optic_odds"] for r in event["rows"]}
    for item in stamped:
        if item.underdog_side != "yes" or item.market_type not in ("moneyline_3way", "point_spread"):
            continue
        team_id = venue[item.underdog_ticker].get("team_id")
        want = entry.fixture.team_map[team_id] if team_id else TIE_SIDE
        assert item.side == want, item.underdog_ticker
    assert any(r.side == TIE_SIDE for r in stamped if r.market_type == "moneyline_3way")
