"""Underdog LoL / CS2 series winner and total maps (live catalogue 2026-10-14)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport
from tests.mappers.test_tip_leagues import _row

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_esports_2026-10-14.json"
_LIVE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_OPTIC_LEAGUE = {"lol": "league_of_legends", "cs2": "cs2"}


def _entries(optic: list[dict]) -> list[SimpleNamespace]:
    """Optic fixtures as captured: names, Optic start, competitor ids for the witness."""
    return [
        SimpleNamespace(fixture=SimpleNamespace(
            fixture_id=fx["fixture_id"], home="HOM", away="AWY",
            home_name=fx["home_name"], away_name=fx["away_name"], start_date=fx["start_date"],
            team_map={fx["home_id"]: "HOM", fx["away_id"]: "AWY"}, odds=[],
        ))
        for fx in optic
    ]


def _run(league: str, rows: list[dict], entries: list[SimpleNamespace]) -> tuple[dict, list]:
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league=league.upper(), market_types=market_types_for_sport(Sport.ESPORTS))
    tally = run_pass(rows, cfg, entries, league=league, attach=attach, row_index={}, all_rows=[])
    return tally, stamped


@pytest.mark.parametrize("league", sorted(_OPTIC_LEAGUE))
def test_esports_league_maps_underdog_series_markets(league: str) -> None:
    run = resolve_run_leagues({}, [_row(league, sport="esports", optic=_OPTIC_LEAGUE[league])])
    cfg = run[league].UNDERDOG
    assert cfg is not None
    assert cfg.market_types == {"moneyline": MarketType.MONEYLINE, "total_maps": MarketType.TOTAL_MAPS}


@pytest.mark.parametrize("league", sorted(_LIVE))
def test_every_live_contract_stamps_on_the_venue_fixture_and_team(league: str) -> None:
    """The sentences name no kickoff (``scheduled for October 14, 2026``): the join is by Optic id."""
    event = _LIVE[league]
    entries = _entries(event["optic"])
    tally, stamped = _run(league, event["rows"], entries)
    assert tally["stamped"] == len(stamped) == 2 * len(event["rows"])
    assert {r.underdog_ticker for r in stamped} == {r["ticker"] for r in event["rows"]}
    team_maps = {e.fixture.fixture_id: e.fixture.team_map for e in entries}
    for row in event["rows"]:
        ids = row["external_ids"]["optic_odds"]
        sides = {r.underdog_side: r for r in stamped if r.underdog_ticker == row["ticker"]}
        if ids["market_id"] == "moneyline":
            yes = team_maps[ids["fixture_id"]][ids["team_id"]]
            assert (sides["yes"].side, sides["no"].side) == (yes, "AWY" if yes == "HOM" else "HOM")
        else:
            line = float(row["ticker"].rsplit("_", 1)[1])
            assert (sides["yes"].side, sides["no"].side) == ("over", "under")
            assert sides["yes"].line == sides["no"].line == line


def test_contract_on_a_fixture_outside_the_league_is_not_stamped() -> None:
    """No kickoff in the sentence: a contract whose Optic id is not this league's never joins by name."""
    event = _LIVE["cs2"]
    entries = _entries(event["optic"])
    for e in entries:
        e.fixture.fixture_id = f"OTHER-{e.fixture.fixture_id}"
    tally, stamped = _run("cs2", event["rows"], entries)
    assert stamped == []
    assert tally["other_league"] == len(event["rows"])
