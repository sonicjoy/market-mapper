from typing import Any

from mappers.pipeline import attach_polymarket_row, row_key
from mappers.shared import CanonicalRow


def _optic(**kw):
    base: dict[str, Any] = dict(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ", away="STL",
                market_type="game_total", line=8.5, side="over", optic_id="OPT1")
    base.update(kw)
    return CanonicalRow(**base)


def _poly(**kw):
    base: dict[str, Any] = dict(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ", away="STL",
                market_type="game_total", line=8.5, side="over",
                polymarket_clob_token_id="cO")
    base.update(kw)
    return CanonicalRow(**base)


def test_attach_stamps_onto_matching_optic_row():
    optic = _optic()
    index = {row_key(optic): optic}
    result = attach_polymarket_row(index, _poly())
    assert result == "stamped"
    assert index[row_key(optic)].polymarket_clob_token_id == "cO"


def test_attach_drops_when_no_optic_row():
    # guard #3: optic didn't price this market for this fixture -> drop, don't append
    index = {}
    result = attach_polymarket_row(index, _poly())
    assert result == "dropped_no_optic"
    assert index == {}
