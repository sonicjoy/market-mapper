"""Polymarket US NBA 2H team total counts overtime, so it maps to Optic's _incl_ot market.

Venue text (gateway event 135241, 2026-10-20): "... scores over 53.5 points in the second
half ... Overtime is included if played." Optic lists the OT-inclusive line as
``2nd_half_team_total_incl_ot`` (DraftKings) beside the plain ``2nd_half_team_total``.
"""

from __future__ import annotations

import json

import mappers.pipeline as pipeline
from mappers.exchanges import optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_sides import venue_side
from mappers.market_types import MarketType as M
from mappers.shared import CanonicalRow
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.poly_usa_smt import smt_spec

# fetch.polymarket_usa.market_record of tsc-nba-bos-det-2026-10-20-tt-bos-sh-53pt5 (ids kept, extras trimmed).
_RECORD = {
    "league_id": 2, "event_id": "135241", "event_ticker": "nba-bos-det-2026-10-20",
    "event_start": "2026-10-20T19:00:00Z", "sportradar_game_id": "023405e4-4019-4c27-ae8b-b7064db1d8d0",
    "teams": [{"id": "17", "abbreviation": "bos", "name": "Celtics", "league": "nba"},
              {"id": "23", "abbreviation": "det", "name": "Pistons", "league": "nba"}],
    "market_id": "1578656", "slug": "tsc-nba-bos-det-2026-10-20-tt-bos-sh-53pt5",
    "sports_market_type": "basketball_team_total_points_second_half", "market_type": "totals",
    "line": 53.5, "metadata": {"teamId": 17},
    "sides": [{"id": "3156788", "long": True, "description": "Over", "team_id": "17"},
              {"id": "3156789", "long": False, "description": "Under", "team_id": "17"}],
}
_FX = optic.Fixture(
    fixture_id="20261020D42F1161", game_id="G", sportradar_id=None, start_et="2026-10-20T15:00:00",
    start_date="2026-10-20T19:00:00Z", home="DET", away="BOS", home_name="Detroit Pistons",
    away_name="Boston Celtics", team_map={"OPT-DET": "DET", "OPT-BOS": "BOS"}, odds=[], is_live=False,
)
_BIND = pus.EventBind(fixture=_FX, team_sides={"17": "BOS", "23": "DET"})


def _market() -> pus.UsMarket:
    market = pus.parse_market(json.loads(json.dumps(_RECORD)))
    assert market is not None
    return market


def _optic_keys(market_id: str) -> set[tuple]:
    odds = [optic.Odd(id=f"F:dk:{market_id}:{s}", market_id=market_id, name=f"Boston Celtics {s.title()} 53.5",
                      selection="Boston Celtics", selection_line=s, points=53.5, team_id="OPT-BOS",
                      grouping_key="default") for s in ("over", "under")]
    rows, _, _ = optic.build_rows(_FX.start_date, "DET", "BOS", _FX._replace(odds=odds),
                                  optic.OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES)),
                                  league="nba")
    return {(r.market_type, r.entity, r.line, r.side) for r in rows}


def test_second_half_team_total_is_the_incl_ot_type() -> None:
    assert smt_spec("basketball_team_total_points_second_half") == (M.SECOND_HALF_TEAM_TOTAL_INCL_OT, "team_total")
    assert BASKETBALL_OPTIC_TABLE_TYPES["2nd_half_team_total_incl_ot"] is M.SECOND_HALF_TEAM_TOTAL_INCL_OT
    assert BASKETBALL_OPTIC_TABLE_TYPES["2nd_half_team_total"] is M.SECOND_HALF_TEAM_TOTAL


def test_bets_land_on_the_incl_ot_selection_only() -> None:
    market = _market()
    bets = pus.market_bets(market, _BIND)
    assert bets == [("2h_team_total_incl_ot", "BOS", 53.5, "over"), ("2h_team_total_incl_ot", "BOS", 53.5, "under")]
    assert [venue_side(market, _BIND, b) for b in bets] == ["yes", "no"]
    assert set(bets) <= _optic_keys("2nd_half_team_total_incl_ot")
    assert not set(bets) & _optic_keys("2nd_half_team_total")


def test_optic_passthrough_onto_the_plain_2h_market_is_stripped() -> None:
    """Optic hangs the symbol on its plain 2nd_half_team_total; our bind contradicts it, so it goes."""
    market = _market()
    computed = [pus.build_row(market, _BIND, b, "nba", venue_side(market, _BIND, b))
                for b in pus.market_bets(market, _BIND)]
    passthrough = CanonicalRow(league="nba", start_date=_FX.start_date, home="DET", away="BOS",
                               market_type=M.SECOND_HALF_TEAM_TOTAL.value, entity="BOS", line=53.5, side="over")
    verdict = pipeline._usa_strip_reason(passthrough, market, _BIND, computed)
    assert verdict is not None and verdict[0] == "contradicts"
