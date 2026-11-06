"""ProphetX NFL anytime-TD scorer: type=moneyline YES/NO -> player_touchdowns over/under 0.5."""
from mappers.exchanges import px
from mappers.market_types import MarketType
from mappers.vocab.football_markets import NFL_PX

_NAME = "Jaylen Waddle To Score a Touchdown"


def _market(name: str = _NAME) -> px.Market:
    return px.Market(
        id=1700009001, name=name, type="moneyline", status="active", sport_event_id=1,
        selections=[
            {"display_name": "YES", "name": "YES", "outcome_id": 1, "strike": 0, "strike_id": "a"},
            {"display_name": "NO", "name": "NO", "outcome_id": 2, "strike": 0, "strike_id": "b"},
        ],
    )


def test_classifies_as_yes_no_twin_of_player_touchdowns():
    match = px.classify_market(_NAME, "moneyline", NFL_PX)
    assert match.market_type == MarketType.PLAYER_TOUCHDOWNS_YN
    assert match.suffix is not None
    assert px.extract_player(_NAME, match.suffix) == "Jaylen Waddle"


def test_rows_downgrade_to_player_touchdowns_over_under_half():
    cm = px.classify_and_enrich(_market(), NFL_PX, {})
    assert [ln.line for ln in cm.market_lines] == [0.5]
    rows = px.build_rows("2026-10-16T00:00:00Z", "SEA", "LAR", [cm], {}, league="nfl")
    got = {(r.market_type, r.line, r.side) for r in rows}
    assert got == {("player_touchdowns", 0.5, "over"), ("player_touchdowns", 0.5, "under")}


def test_first_and_last_touchdown_stay_unmapped():
    for n in ("X To Score First Touchdown", "X To Score Last Touchdown"):
        try:
            px.classify_market(n, "moneyline", NFL_PX)
        except ValueError:
            continue
        raise AssertionError(n)
