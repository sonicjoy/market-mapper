"""Every Polymarket US bet names its venue side from typed fields only.

The side list is deliberately given short-first, and the long side is
deliberately the AWAY team, so neither list order nor home/away can
stand in for ``marketSides[].long``.
"""

from __future__ import annotations

from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_sides import venue_side
from mappers.market_types import MarketType
from mappers.pipeline import _usa_market_rows, _usa_side_passthrough, row_key
from mappers.shared import TIE_SIDE
from tests.mappers.test_polymarket_usa_structured import _DET_PIT, _bind, _rec, _side


def _sides_of(market: pus.UsMarket) -> dict[tuple, str | None]:
    bind = _bind()
    return {bet: venue_side(market, bind, bet) for bet in pus.market_bets(market, bind)}


def test_two_team_winner_long_team_is_yes_whatever_the_order():
    market = _rec("baseball_team_full_game_winner", [
        _side("Detroit Tigers", False, "3010"),   # short listed first
        _side("Pittsburgh Pirates", True, "3021"),  # long = the away team
    ], slug="aec-mlb-pit-det-2026-09-26")
    sides = _sides_of(market)
    assert sides[(MarketType.MONEYLINE.value, None, None, "PIT")] == "yes"
    assert sides[(MarketType.MONEYLINE.value, None, None, "DET")] == "no"


def test_spread_long_team_is_yes():
    market = _rec("baseball_team_full_game_spread", [
        _side("+1.50", False, "3010"),
        _side("-1.50", True, "3021"),
    ], slug="asc-mlb-pit-det-2026-09-26-pos-1pt5", line=1.5)
    sides = _sides_of(market)
    assert sides[(MarketType.POINT_SPREAD.value, None, -1.5, "PIT")] == "yes"
    assert sides[(MarketType.POINT_SPREAD.value, None, 1.5, "DET")] == "no"


def test_total_side_follows_the_long_flag_not_the_word():
    """Under as the long side: the under row is the YES."""
    market = _rec("baseball_team_full_game_total", [
        _side("Over", False), _side("Under", True),
    ], slug="tsc-mlb-pit-det-2026-09-26-8pt5", line=8.5)
    sides = _sides_of(market)
    assert sides[(MarketType.GAME_TOTAL.value, None, 8.5, "under")] == "yes"
    assert sides[(MarketType.GAME_TOTAL.value, None, 8.5, "over")] == "no"


def test_yes_no_market_reads_both_sides():
    market = _rec("baseball_game_extra_innings", [
        _side("No", False), _side("Yes", True),
    ], slug="x-extra")
    sides = _sides_of(market)
    assert sides[(MarketType.EXTRA_INNINGS.value, None, None, "yes")] == "yes"
    assert sides[(MarketType.EXTRA_INNINGS.value, None, None, "no")] == "no"


def test_hockey_overtime_is_game_wide_yes_no_despite_its_team_id():
    """The venue tags the NHL overtime market with the home team's id only."""
    market = _rec("hockey_game_overtime", [
        _side("Yes", True, "3010"), _side("No", False, "3010"),
    ], slug="astatc-nhl-x-ot", line=1)
    sides = _sides_of(market)
    assert sides == {
        (MarketType.WILL_THERE_BE_OVERTIME.value, None, None, "yes"): "yes",
        (MarketType.WILL_THERE_BE_OVERTIME.value, None, None, "no"): "no",
    }


def test_per_outcome_market_is_its_own_yes():
    team = _rec("soccer_team_full_time_winner", [
        _side("No", False, "3021"), _side("Yes", True, "3021"),
    ], slug="atc-x-pit")
    draws = frozenset({"atc-x-draw"})
    draw = _rec("soccer_team_full_time_winner", [
        _side("No", False), _side("Yes", True),
    ], slug="atc-x-draw", market_id="atc-x-draw")
    bind = _bind()
    (team_bet,) = pus.market_bets(team, bind)
    (draw_bet,) = pus.market_bets(draw, bind, draws)
    assert draw_bet[3] == TIE_SIDE
    assert venue_side(team, bind, team_bet) == "yes"
    assert venue_side(draw, bind, draw_bet) == "yes"


def test_no_team_scores_first_is_the_first_to_score_tie():
    """astatc-…-fh-ftts-none: the team-less member of the 3-market group."""
    team = _rec("soccer_game_first_half_first_team_to_score", [
        _side("Yes", True, "3021"), _side("No", False, "3021"),
    ], slug="astatc-x-fh-ftts-pit", market_id="astatc-x-fh-ftts-pit")
    other = _rec("soccer_game_first_half_first_team_to_score", [
        _side("Yes", True, "3010"), _side("No", False, "3010"),
    ], slug="astatc-x-fh-ftts-det", market_id="astatc-x-fh-ftts-det")
    none = _rec("soccer_game_first_half_first_team_to_score", [
        _side("No", False), _side("Yes", True),
    ], slug="astatc-x-fh-ftts-none", market_id="astatc-x-fh-ftts-none")
    draws = pus.draw_market_ids([team, other, none])
    assert draws == frozenset({"astatc-x-fh-ftts-none"})
    bind = _bind()
    (bet,) = pus.market_bets(none, bind, draws)
    assert bet == (MarketType.FIRST_HALF_FIRST_TEAM_TO_SCORE.value, None, None, TIE_SIDE)
    assert venue_side(none, bind, bet) == "yes"
    assert pus.market_bets(none, bind) == []  # not a known draw: nothing


def test_a_bet_no_typed_side_accounts_for_gets_no_side():
    market = _rec("baseball_team_full_game_winner", [
        _side("Detroit Tigers", False, "3010"), _side("Pittsburgh Pirates", True, "3021"),
    ], slug="aec-mlb-pit-det-2026-09-26")
    stranger = (MarketType.MONEYLINE.value, None, None, "NYY")
    assert venue_side(market, _bind(), stranger) is None
    one_sided = _rec("baseball_team_full_game_winner", [
        _side("Pittsburgh Pirates", True, "3021"),
    ], slug="aec-mlb-pit-det-2026-09-26")
    bet = (MarketType.MONEYLINE.value, None, None, "PIT")
    assert venue_side(one_sided, _bind(), bet) is None


def test_derived_rows_carry_their_side():
    market = _rec("baseball_team_full_game_winner", [
        _side("Detroit Tigers", False, "3010"), _side("Pittsburgh Pirates", True, "3021"),
    ], slug="aec-mlb-pit-det-2026-09-26")
    stats = {"no_bets": 0}
    rows = _usa_market_rows([market], {market.event_id: _bind()}, {}, "mlb", stats)
    by_side = {r.side: r.polymarket_usa_side for r in rows[market.slug]}
    assert by_side == {"PIT": "yes", "DET": "no"}


def test_passthrough_gets_the_side_only_where_the_bind_reproduces_it():
    market = _rec("baseball_team_full_game_winner", [
        _side("Detroit Tigers", False, "3010"), _side("Pittsburgh Pirates", True, "3021"),
    ], slug="aec-mlb-pit-det-2026-09-26")
    derived = _usa_market_rows(
        [market], {market.event_id: _bind()}, {}, "mlb", {"no_bets": 0},
    )[market.slug]
    pit = pus.build_row(market, _bind(), (MarketType.MONEYLINE.value, None, None, "PIT"), "mlb")
    det = pus.build_row(market, _bind(), (MarketType.MONEYLINE.value, None, None, "DET"), "mlb")
    for r in (pit, det):
        r.polymarket_usa_market_id = None  # Optic's stamp, not ours
    index = {row_key(pit): pit, row_key(det): det}
    _usa_side_passthrough(derived, {row_key(pit)}, index)  # Optic hung it on PIT only
    assert pit.polymarket_usa_side == "yes"
    assert det.polymarket_usa_side is None
    assert _DET_PIT.away == "PIT"  # the YES is the away team: order is not the side
