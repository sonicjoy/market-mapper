"""Novig NFL ``*_PROTECTED`` props map like Kalshi's "(Protected)": base type + ``_insurance``.

Source: docs.novig.com/api/concepts/participation-protection (read 2026-11-04).  A
protected market is its own book with the same event, player and strike as its
standard twin; ``marketType`` is the standard type with ``_PROTECTED`` appended.
"""

from __future__ import annotations

import json

import pytest

from mappers.exchanges.novig import NovigMarket, build_rows, parse_market
from mappers.exchanges.optic import GameRef, Odd
from mappers.insurance_stamp import stamp_insurance_rows
from mappers.pipeline import attach_novig_row, row_key
from mappers.vocab.novig_markets import FOOTBALL, FOOTBALL_PROTECTED, classify_novig_type

PLAYER_OPTIC = "D88250CC9CF9"

# Novig's documented list, written out so a vocab edit cannot silently shrink it.
_DOCUMENTED = {
    "PASSING_YARDS", "PASSING_ATTEMPTS", "PASSING_COMPLETIONS", "PASSING_TOUCHDOWNS",
    "LONGEST_COMPLETION", "INTERCEPTIONS_THROWN", "RUSHING_YARDS", "RUSHING_ATTEMPTS",
    "LONGEST_RUSH", "RECEIVING_YARDS", "RECEPTIONS", "LONGEST_RECEPTION",
    "PASSING_AND_RUSHING_YARDS", "RUSHING_AND_RECEIVING_YARDS", "TOUCHDOWNS",
}


def test_every_documented_protected_type_is_mapped():
    assert set(FOOTBALL_PROTECTED) == {f"{t}_PROTECTED" for t in _DOCUMENTED}
    for base in _DOCUMENTED:
        assert classify_novig_type("football", f"{base}_PROTECTED")[0] == "mapped"


@pytest.mark.parametrize("base", sorted(_DOCUMENTED))
def test_protected_type_is_the_base_type_with_insurance(base):
    std, prot = FOOTBALL[base], FOOTBALL[f"{base}_PROTECTED"]
    assert prot.value == f"{std.value}_insurance"
    assert (prot.scope, prot.shape) == (std.scope, std.shape)


def _market(mtype: str, market_id: str) -> NovigMarket:
    m = parse_market(json.dumps({
        "id": market_id, "type": mtype, "description": f"{mtype} desc", "status": "OPEN",
        "strike": 64.5, "league": "NFL", "eventId": "e1", "playerId": "p1",
        "player": {"id": "p1", "name": "Puka Nacua", "fullName": "Puka Nacua", "opticOddsId": PLAYER_OPTIC},
        "outcomeIds": [f"{market_id}-o", f"{market_id}-u"],
        "outcomes": [
            {"id": f"{market_id}-o", "description": "Over 64.5", "type": "Over", "index": 0},
            {"id": f"{market_id}-u", "description": "Under 64.5", "type": "Under", "index": 1},
        ],
    }))
    assert m is not None
    return m


def _rows(mtype: str, market_id: str):
    return build_rows(
        _market(mtype, market_id), FOOTBALL[mtype], home="LAR", away="SF",
        start_date="2026-11-05", league="nfl", team_map={}, player_names={PLAYER_OPTIC: "puka_nacua"})


def test_protected_rows_equal_the_standard_rows_but_for_type_and_ids():
    std, prot = _rows("RECEIVING_YARDS", "m-std"), _rows("RECEIVING_YARDS_PROTECTED", "m-prot")
    assert {r.market_type for r in prot} == {"player_receiving_yards_insurance"}
    shape = lambda rs: sorted((r.line, r.side, r.entity) for r in rs)  # noqa: E731
    assert shape(prot) == shape(std) == [(64.5, "over", "puka_nacua"), (64.5, "under", "puka_nacua")]
    assert {r.novig_market_id for r in prot} == {"m-prot"}


def test_protected_row_is_inserted_then_takes_the_base_props_optic_odd():
    std, prot = _rows("RECEIVING_YARDS", "m-std"), _rows("RECEIVING_YARDS_PROTECTED", "m-prot")
    over = next(r for r in std if r.side == "over")
    over.optic_id = "odd1"  # stands in for the Optic base row
    index, all_rows = {row_key(over): over}, [over]
    odds = {"odd1": Odd(id="odd1", market="Player Receiving Yards", market_id="mkt1",
                        grouping_key="g", points=64.5, source_ids={})}
    refs = {"odd1": GameRef(fixture_id="f1", game_id="g1")}

    assert [attach_novig_row(index, r, all_rows) for r in prot] == ["stamped", "stamped"]
    assert stamp_insurance_rows(index, odds, refs) == 1  # only the over has a base
    ins_over = next(r for r in prot if r.side == "over")
    assert ins_over.optic_id == "odd1_insurance" and ins_over.novig_outcome_id == "m-prot-o"
    assert next(r for r in prot if r.side == "under").optic_id is None


def test_a_standard_prop_with_no_optic_row_is_still_dropped():
    std = _rows("RECEIVING_YARDS", "m-std")
    assert attach_novig_row({}, std[0], []) == "dropped_no_optic"
