"""A US passthrough is only allowed on the fixture the venue binds (pin)."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.exchanges import optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.optic_passthrough_crosscheck import TWO_WAY_NO, CrosscheckLedger
from mappers.pipeline import _strip_unverified_usa_passthrough, row_key
from mappers.shared import CanonicalRow

_GAME1 = "2026-09-25T20:05:00Z"
_GAME2 = "2026-09-25T23:25:00Z"
_TICKER = "astatc-mlb-bal-nyy-2026-09-26-hr-petalo-gte1"


def _prop(start: str) -> CanonicalRow:
    return CanonicalRow(
        league="mlb", start_date=start, home="NYY", away="BAL",
        market_type="player_home_runs", entity="PA", line=0.5, side="over",
        optic_id="o",
    )


def _strip(
    row: CanonicalRow, bound_start: str | None, computed: list[CanonicalRow],
    smt: str = "baseball_player_home_runs",
    ledger: CrosscheckLedger | None = None,
) -> int:
    market = pus.UsMarket(
        league_id=5, event_id="e1", event_ticker="", event_start=_GAME1,
        sportradar_game_id="", teams=(), market_id="m", slug=_TICKER,
        sports_market_type=smt, line=1.0,
        player_name="", line_label="", sides=(),
    )
    binds = {}
    if bound_start is not None:
        fx = SimpleNamespace(start_date=bound_start, home=row.home, away=row.away)
        binds["e1"] = pus.EventBind(fixture=fx)
    odd = optic.Odd(
        id="o", market_id="player_home_runs", grouping_key="default",
        source_ids={"Polymarket (USA)": {"market_id": _TICKER}},
    )
    return _strip_unverified_usa_passthrough(
        {row_key(row): row}, {"o": odd}, [market], binds,
        {_TICKER: computed} if computed else {}, ledger,
    )


def test_pin_keeps_the_bound_fixture_only():
    """Doubleheader: Optic hung a prop ticker on game 2; the venue bound game 1."""
    assert _strip(_prop(_GAME1), _GAME1, []) == 0
    assert _strip(_prop(_GAME2), _GAME1, []) == 1


def test_strip_unbound_and_verify_derived_rows():
    assert _strip(_prop(_GAME1), None, []) == 1
    row = _prop(_GAME1)
    assert _strip(row, _GAME1, [row]) == 0
    other = row.model_copy(update={"line": 1.5})
    assert _strip(row, _GAME1, [other]) == 1


def test_not_equivalent_enum_on_bound_fixture_is_stripped(monkeypatch):
    """A NOT_EQUIVALENT enum never keeps an Optic passthrough; corners do."""
    import mappers.pipeline as pipeline

    monkeypatch.setattr(pipeline, "NOT_EQUIVALENT", frozenset({"ufc_x_not_equal"}))
    row = _prop(_GAME1)
    assert _strip(row, _GAME1, [], smt="ufc_x_not_equal") == 1
    assert _strip(row, _GAME1, [], smt="soccer_game_total_corners") == 0


def _set_winner(side: str, usa_side: str | None = None) -> CanonicalRow:
    return CanonicalRow(
        league="atp", start_date=_GAME1, home="TAB2", away="NBK5",
        market_type="1st_set_winner", side=side, optic_id="o",
        polymarket_usa_side=usa_side,
    )


def test_two_way_no_listing_is_stripped_but_not_a_disagreement():
    """Optic hangs the TAB2 set-1 symbol on NBK5 too: that is its NO side."""
    ledger = CrosscheckLedger()
    yes = _set_winner("TAB2", usa_side="yes")
    assert _strip(_set_winner("NBK5"), _GAME1, [yes], "tennis_set_1_winner", ledger) == 1
    (rec,) = ledger.disagreements
    assert rec["detail"] == TWO_WAY_NO
    assert rec["our_row_key"] == str(row_key(yes))


def test_strip_records_why_and_our_key():
    ledger = CrosscheckLedger()
    _strip(_prop(_GAME1), None, [], ledger=ledger)
    assert [(r["detail"], r["our_row_key"]) for r in ledger.disagreements] == [("unbound", "")]
    row = _prop(_GAME1)
    other = row.model_copy(update={"line": 1.5})
    ledger = CrosscheckLedger()
    _strip(row, _GAME1, [other], ledger=ledger)
    assert [(r["detail"], r["our_row_key"]) for r in ledger.disagreements] == [
        ("contradicts", str(row_key(other))),
    ]


def test_two_way_needs_our_yes_to_count_as_the_no():
    """Without a derived YES the complement pass stamps nothing back."""
    ledger = CrosscheckLedger()
    unsided = _set_winner("TAB2")
    _strip(_set_winner("NBK5"), _GAME1, [unsided], "tennis_set_1_winner", ledger)
    assert [r["detail"] for r in ledger.disagreements] == ["contradicts"]
