"""Insurance rows take their base prop's Optic odd with an ``_insurance`` market id."""

from mappers.exchanges.optic import GameRef, Odd
from mappers.insurance_stamp import stamp_insurance_rows
from mappers.pipeline import row_key
from mappers.shared import CanonicalRow


_REF = GameRef(fixture_id="f1", game_id="g1")


def _row(market_type: str, optic_id: str | None = None) -> CanonicalRow:
    return CanonicalRow(
        league="nfl", start_date="2026-10-15", home="Denver Broncos",
        away="Seattle Seahawks", market_type=market_type,
        entity="Rashid Shaheed", line=0.5, side="over", optic_id=optic_id,
    )


def _odd() -> Odd:
    return Odd(id="odd1", market="Player Touchdowns", market_id="mkt1",
               grouping_key="g", points=0.5, source_ids={"Kalshi": "KXNFLTD-X"})


def _index(*rows: CanonicalRow) -> dict:
    return {row_key(r): r for r in rows}


def test_insurance_row_takes_base_odd_with_suffixed_market_id():
    base = _row("player_touchdowns", "odd1")
    ins = _row("player_touchdowns_insurance")
    lookup = {"odd1": _odd()}
    refs = {"odd1": _REF}
    assert stamp_insurance_rows(_index(base, ins), lookup, refs) == 1
    assert ins.optic_id == "odd1_insurance"
    derived = lookup["odd1_insurance"]
    assert derived.market_id == "mkt1_insurance"
    assert derived.points == 0.5 and derived.source_ids == {}
    assert lookup["odd1"].market_id == "mkt1"
    assert refs["odd1_insurance"] is _REF


def test_no_base_row_leaves_insurance_unstamped():
    ins = _row("player_touchdowns_insurance")
    assert stamp_insurance_rows(_index(ins), {"odd1": _odd()}, {"odd1": _REF}) == 0
    assert ins.optic_id is None


def test_non_insurance_rows_untouched():
    plain = _row("player_touchdowns")
    assert stamp_insurance_rows(_index(plain), {}, {}) == 0
    assert plain.optic_id is None
