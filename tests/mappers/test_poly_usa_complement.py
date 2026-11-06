"""One-sided Polymarket US tickers get their exhaustive NO-side row."""

from __future__ import annotations

import pytest

from mappers.exchanges import optic
from mappers.market_types import MarketType
from mappers.pipeline import row_key
from mappers.poly_usa_complement import stamp_usa_complements, usa_no_goal_satellites
from mappers.shared import CanonicalRow

_USA = "Polymarket (USA)"


def _row(market_type: str, side: str, *, optic_id: str | None, line: float | None = None,
         entity: str | None = None, league: str = "unl") -> CanonicalRow:
    return CanonicalRow(
        league=league, start_date="2026-09-25T18:45:00Z", home="ITA", away="BEL",
        market_type=market_type, entity=entity, line=line, side=side, optic_id=optic_id,
    )


def _odd(odd_id: str, ticker: str | None = None) -> optic.Odd:
    src = {_USA: {"market_id": ticker}} if ticker else {}
    return optic.Odd(id=odd_id, market_id="m", grouping_key="default", source_ids=src)


def _index(*rows: CanonicalRow) -> dict[tuple, CanonicalRow]:
    return {row_key(r): r for r in rows}


def test_yes_only_passthrough_gets_the_no_row():
    """astatc-unl-ita-bel-2026-09-25-btts: Optic hung the ticker on Yes only."""
    ticker = "astatc-unl-ita-bel-2026-09-25-btts"
    yes = _row(MarketType.BTTS.value, "yes", optic_id="o-yes")
    no = _row(MarketType.BTTS.value, "no", optic_id="o-no")
    odds = {"o-yes": _odd("o-yes", ticker), "o-no": _odd("o-no")}
    stats = stamp_usa_complements(_index(yes, no), odds)
    assert stats["stamped"] == 1
    assert no.polymarket_usa_market_id == ticker
    assert yes.polymarket_usa_market_id is None  # passthrough row stays passthrough


def test_over_only_prop_at_half_line_gets_the_under():
    ticker = "astatc-nfl-kc-mia-2026-09-27-patt-patmah-gte28"
    over = _row(MarketType.GAME_TOTAL.value, "over", optic_id="o", line=27.5, entity="PM")
    under = _row(MarketType.GAME_TOTAL.value, "under", optic_id="u", line=27.5, entity="PM")
    over.polymarket_usa_market_id = ticker  # Path 2 stamp
    stamp_usa_complements(_index(over, under), {"o": _odd("o"), "u": _odd("u")})
    assert under.polymarket_usa_market_id == ticker


def test_one_team_half_line_spread_gets_the_other_team():
    ticker = "asc-intf-aus-bra-2026-09-25-pos-1pt5"
    aus = _row(MarketType.POINT_SPREAD.value, "ITA", optic_id="a", line=1.5)
    bel = _row(MarketType.POINT_SPREAD.value, "BEL", optic_id="b", line=-1.5)
    aus.polymarket_usa_market_id = ticker
    stamp_usa_complements(_index(aus, bel), {"a": _odd("a"), "b": _odd("b")})
    assert bel.polymarket_usa_market_id == ticker


def test_push_capable_lines_are_not_completed():
    """An integer or quarter line can push/half-push: its NO is not one row."""
    for line in (3.0, 0.25):
        over = _row(MarketType.GAME_TOTAL.value, "over", optic_id="o", line=line)
        under = _row(MarketType.GAME_TOTAL.value, "under", optic_id="u", line=line)
        over.polymarket_usa_market_id = "tsc-x"
        stats = stamp_usa_complements(_index(over, under), {"o": _odd("o"), "u": _odd("u")})
        assert under.polymarket_usa_market_id is None
        assert stats["not_exhaustive"] == 1


def test_moneyline_is_never_completed():
    """A 3-way NO is two selections; aec already stamps both teams itself."""
    home = _row(MarketType.MONEYLINE.value, "ITA", optic_id="h")
    draw = _row(MarketType.MONEYLINE.value, "_TIE", optic_id="d")
    home.polymarket_usa_market_id = "atc-unl-ita-bel-2026-09-25-ita"
    stats = stamp_usa_complements(_index(home, draw), {"h": _odd("h"), "d": _odd("d")})
    assert draw.polymarket_usa_market_id is None
    assert stats["stamped"] == 0


def test_two_sided_ticker_is_untouched():
    yes = _row(MarketType.BTTS.value, "yes", optic_id="y")
    no = _row(MarketType.BTTS.value, "no", optic_id="n")
    odds = {"y": _odd("y", "t"), "n": _odd("n", "t")}
    assert stamp_usa_complements(_index(yes, no), odds)["stamped"] == 0
    assert no.polymarket_usa_market_id is None


def test_claimed_or_missing_complement_is_left_alone():
    """Missing > wrong: never overwrite another ticker, never invent a row."""
    yes = _row(MarketType.BTTS.value, "yes", optic_id="y")
    no = _row(MarketType.BTTS.value, "no", optic_id="n")
    yes.polymarket_usa_market_id = "t-yes"
    no.polymarket_usa_market_id = "t-other"
    stats = stamp_usa_complements(_index(yes, no), {"y": _odd("y"), "n": _odd("n")})
    assert no.polymarket_usa_market_id == "t-other"
    assert stats["claimed"] >= 1

    lone = _row(MarketType.BTTS.value, "yes", optic_id="y2", league="epl")
    lone.polymarket_usa_market_id = "t-lone"
    stats = stamp_usa_complements(_index(lone), {"y2": _odd("y2")})
    assert stats == {"stamped": 0, "no_optic": 1, "claimed": 0, "not_exhaustive": 0}


def test_per_outcome_yes_only_types_never_get_a_no():
    """MOV / MOF / exact score: the NO is every other outcome, never one row."""
    ticker = "astatc-ufc-brahie-rinnak-2026-09-26-mov-f1-dec"
    yes = _row(MarketType.METHOD_OF_VICTORY.value, "yes", optic_id="o-yes",
               entity="HIE", league="ufc")
    yes.grouping_key = "decision"
    no = _row(MarketType.METHOD_OF_VICTORY.value, "no", optic_id="o-no",
              entity="HIE", league="ufc")
    no.grouping_key = "decision"
    odds = {"o-yes": _odd("o-yes", ticker), "o-no": _odd("o-no")}
    stats = stamp_usa_complements(_index(yes, no), odds)
    assert stats["stamped"] == 0
    assert no.polymarket_usa_market_id is None


# === Soccer per-outcome moneyline No → Optic double chance ===

from mappers.poly_usa_complement import stamp_usa_double_chance  # noqa: E402


def _dc_fixture(ml_type: str, dc_type: str) -> tuple[dict, dict]:
    """Three Yes-stamped outcome rows plus the three Optic DC rows."""
    rows = {
        "ITA": _row(ml_type, "ITA", optic_id="ml-h"),
        "BEL": _row(ml_type, "BEL", optic_id="ml-a"),
        "_TIE": _row(ml_type, "_TIE", optic_id="ml-d"),
        "ITA/_TIE": _row(dc_type, "ITA/_TIE", optic_id="dc-1x"),
        "BEL/_TIE": _row(dc_type, "BEL/_TIE", optic_id="dc-x2"),
        "ITA/BEL": _row(dc_type, "ITA/BEL", optic_id="dc-12"),
    }
    base = "atc-unl-ita-bel-2026-09-25"
    rows["ITA"].polymarket_usa_market_id = f"{base}-ita"
    rows["BEL"].polymarket_usa_market_id = f"{base}-bel"
    rows["_TIE"].polymarket_usa_market_id = f"{base}-draw"
    odds = {r.optic_id: _odd(r.optic_id) for r in rows.values() if r.optic_id}
    return rows, odds


def test_soccer_outcome_no_lands_on_the_other_two_outcomes():
    """ITA No = BEL or draw; BEL No = ITA or draw; draw No = either team."""
    rows, odds = _dc_fixture(MarketType.MONEYLINE_3WAY.value, MarketType.DOUBLE_CHANCE.value)
    stats = stamp_usa_double_chance(_index(*rows.values()), odds, soccer=True)
    assert stats["stamped"] == 3
    base = "atc-unl-ita-bel-2026-09-25"
    assert rows["BEL/_TIE"].polymarket_usa_market_id == f"{base}-ita"
    assert rows["ITA/_TIE"].polymarket_usa_market_id == f"{base}-bel"
    assert rows["ITA/BEL"].polymarket_usa_market_id == f"{base}-draw"
    for dc in ("ITA/_TIE", "BEL/_TIE", "ITA/BEL"):
        assert rows[dc].polymarket_usa_side == "no"
    for yes in ("ITA", "BEL", "_TIE"):  # the Yes rows are not touched
        assert rows[yes].polymarket_usa_side is None


def test_soccer_first_half_lands_on_first_half_double_chance():
    rows, odds = _dc_fixture(
        MarketType.FIRST_HALF_WINNER_3WAY.value, MarketType.FIRST_HALF_DOUBLE_CHANCE.value)
    assert stamp_usa_double_chance(_index(*rows.values()), odds, soccer=True)["stamped"] == 3
    assert rows["BEL/_TIE"].polymarket_usa_market_id == "atc-unl-ita-bel-2026-09-25-ita"


def test_non_soccer_three_way_never_gets_double_chance():
    """NFL 1H is 3-way on the venue too, but Optic prices no half DC there."""
    rows, odds = _dc_fixture(
        MarketType.FIRST_HALF_WINNER_3WAY.value, MarketType.FIRST_HALF_DOUBLE_CHANCE.value)
    assert stamp_usa_double_chance(_index(*rows.values()), odds, soccer=False)["stamped"] == 0
    assert rows["BEL/_TIE"].polymarket_usa_market_id is None


def test_double_chance_is_left_alone_when_missing_or_ambiguous():
    """Missing > wrong: an unpriced DC, or a symbol on two rows, maps nothing."""
    rows, odds = _dc_fixture(MarketType.MONEYLINE_3WAY.value, MarketType.DOUBLE_CHANCE.value)
    rows["ITA/BEL"].optic_id = None  # Optic doesn't price "either team"
    # the BEL symbol on the ITA row too: it is no longer one outcome
    rows["ITA"].polymarket_usa_market_id = "atc-unl-ita-bel-2026-09-25-bel"
    stats = stamp_usa_double_chance(_index(*rows.values()), odds, soccer=True)
    assert stats == {"stamped": 0, "no_optic": 1, "claimed": 0, "not_one_outcome": 1}
    assert all(r.polymarket_usa_side is None for r in rows.values())


def test_claimed_double_chance_keeps_its_symbol():
    rows, odds = _dc_fixture(MarketType.MONEYLINE_3WAY.value, MarketType.DOUBLE_CHANCE.value)
    rows["BEL/_TIE"].polymarket_usa_market_id = "someone-else"
    stats = stamp_usa_double_chance(_index(*rows.values()), odds, soccer=True)
    assert stats["claimed"] == 1
    assert stats["stamped"] == 2
    assert rows["BEL/_TIE"].polymarket_usa_market_id == "someone-else"
    assert rows["BEL/_TIE"].polymarket_usa_side is None


@pytest.fixture(autouse=True)
def _no_goal_under_on(monkeypatch):
    monkeypatch.setenv("MAPPING_POLYUS_NO_GOAL_UNDER", "1")


def _no_goal(market_type: str = MarketType.FIRST_HALF_FIRST_TEAM_TO_SCORE.value) -> CanonicalRow:
    row = _row(market_type, "_TIE", optic_id=None)
    row.polymarket_usa_market_id = "astatc-unl-ita-bel-2026-09-25-fh-ftts-none"
    row.polymarket_usa_side = "yes"
    return row


def test_no_team_scores_is_priced_off_the_periods_under_half_goal():
    """The under row keeps the venue's own total 0.5 symbol; the no-goal
    symbol becomes a satellite on its own first-team-to-score key."""
    under = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=0.5)
    under.polymarket_usa_market_id = "tsc-unl-ita-bel-2026-09-25-fh-0pt5"
    ft_under = _row(MarketType.GAME_TOTAL.value, "under", optic_id="ft", line=0.5)
    ur = _no_goal()
    sats, stats = usa_no_goal_satellites(_index(under, ft_under), [ur], soccer=True)
    assert sats == [ur] and stats["stamped"] == 1 and stats["no_optic"] == 0
    assert ur.optic_id == "u"  # the 1H under, not the full-game one
    assert ur.polymarket_usa_satellite
    assert under.polymarket_usa_market_id == "tsc-unl-ita-bel-2026-09-25-fh-0pt5"


def test_no_team_scores_needs_the_under_half_goal_and_soccer():
    under = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=0.5)
    assert usa_no_goal_satellites(_index(under), [_no_goal()], soccer=False)[0] == []
    over_only = _row(MarketType.FIRST_HALF_TOTAL.value, "over", optic_id="o", line=0.5)
    sats, stats = usa_no_goal_satellites(_index(over_only), [_no_goal()], soccer=True)
    assert sats == [] and stats["no_optic"] == 1
    one_five = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=1.5)
    assert usa_no_goal_satellites(_index(one_five), [_no_goal()], soccer=True)[0] == []


def test_only_the_first_to_score_tie_gets_a_no_goal_satellite():
    under = _row(MarketType.GAME_TOTAL.value, "under", optic_id="u", line=0.5)
    team = _row(MarketType.FIRST_TEAM_TO_SCORE.value, "ITA", optic_id=None)
    draw = _row(MarketType.MONEYLINE_3WAY.value, "_TIE", optic_id=None)
    sats, _ = usa_no_goal_satellites(_index(under), [team, draw], soccer=True)
    assert sats == []


def test_two_outcome_team_market_no_is_the_other_team():
    """astatc-atp-…-sw1: one symbol per player; its NO is the other player."""
    ticker = "astatc-atp-danmed-romsaf-2026-09-28-sw1"
    ita = _row(MarketType.FIRST_SET_WINNER.value, "ITA", optic_id="i")
    bel = _row(MarketType.FIRST_SET_WINNER.value, "BEL", optic_id="b")
    ita.polymarket_usa_market_id = ticker
    ita.polymarket_usa_side = "yes"
    stats = stamp_usa_complements(_index(ita, bel), {"i": _odd("i"), "b": _odd("b")})
    assert stats["stamped"] == 1
    assert (bel.polymarket_usa_market_id, bel.polymarket_usa_side) == (ticker, "no")


def test_an_unsided_two_outcome_symbol_is_not_completed():
    """Optic's passthrough the bind never reproduced: which team is YES is unknown."""
    ita = _row(MarketType.MAP_1_WINNER.value, "ITA", optic_id="i")
    bel = _row(MarketType.MAP_1_WINNER.value, "BEL", optic_id="b")
    ita.polymarket_usa_market_id = "astatc-cs2-x-m1"
    stamp_usa_complements(_index(ita, bel), {"i": _odd("i"), "b": _odd("b")})
    assert bel.polymarket_usa_market_id is None


def test_no_goal_fallback_is_off_by_default(monkeypatch):
    """Held until the maker reads selection_id (mmpolymarketusrfq#75)."""
    monkeypatch.delenv("MAPPING_POLYUS_NO_GOAL_UNDER")
    under = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=0.5)
    assert usa_no_goal_satellites(_index(under), [_no_goal()], soccer=True)[0] == []


def test_no_team_scores_no_is_the_periods_over_half_goal():
    """The fallback YES (under 0.5) gets its NO: a team scores first = over 0.5."""
    under = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=0.5)
    over = _row(MarketType.FIRST_HALF_TOTAL.value, "over", optic_id="o", line=0.5)
    ur = _no_goal()
    sats, stats = usa_no_goal_satellites(_index(under, over), [ur], soccer=True)
    assert stats["stamped"] == 1 and stats["no_stamped"] == 1
    yes, no = sats
    assert (yes.optic_id, yes.polymarket_usa_side) == ("u", "yes")
    assert (no.optic_id, no.polymarket_usa_side) == ("o", "no")
    assert no.polymarket_usa_market_id == ur.polymarket_usa_market_id
    assert no.polymarket_usa_satellite and no.side == "ITA/BEL"
    assert row_key(no) != row_key(yes)  # its own MERGE key


def test_optic_draw_keeps_the_yes_and_gets_the_over_as_its_no():
    """Optic prices the first-to-score draw: no YES satellite, only the NO."""
    draw = _row(MarketType.FIRST_HALF_FIRST_TEAM_TO_SCORE.value, "_TIE", optic_id="d")
    draw.polymarket_usa_market_id = "astatc-mls-nyr-stl-2026-09-26-fh-ftts-none"
    draw.polymarket_usa_side = "yes"
    over = _row(MarketType.FIRST_HALF_TOTAL.value, "over", optic_id="o", line=0.5)
    sats, stats = usa_no_goal_satellites(_index(draw, over), [], soccer=True,
                                         odd_lookup={"d": _odd("d"), "o": _odd("o")})
    assert stats["stamped"] == 0 and stats["no_stamped"] == 1
    (no,) = sats
    assert (no.optic_id, no.polymarket_usa_side) == ("o", "no")
    assert draw.optic_id == "d" and not draw.polymarket_usa_satellite


def test_no_goal_no_needs_the_over_half_goal():
    under = _row(MarketType.FIRST_HALF_TOTAL.value, "under", optic_id="u", line=0.5)
    sats, stats = usa_no_goal_satellites(_index(under), [_no_goal()], soccer=True)
    assert len(sats) == 1 and stats["no_no_optic"] == 1
