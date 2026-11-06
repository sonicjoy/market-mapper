"""Soccer player_goals over 0.5 is canonicalised as anytime_goal_scorer."""
import pytest

from mappers.anytime_scorer import fold_anytime_goalscorer
from mappers.shared import CanonicalRow


def _row(league="epl", market_type="player_goals", line=0.5, side="over"):
    return CanonicalRow(
        league=league, start_date="2026-10-17T14:00:00Z", home="A", away="B",
        market_type=market_type, entity="some_player", line=line, side=side)


@pytest.mark.parametrize("side", ["over", "yes"])
def test_over_half_becomes_anytime_yes_without_line(side):
    r = _row(side=side)
    assert (r.market_type, r.line, r.side) == ("anytime_goal_scorer", None, "yes")


@pytest.mark.parametrize("side", ["under", "no"])
def test_under_half_stays_on_player_goals(side):
    r = _row(side=side)
    assert (r.market_type, r.line, r.side) == ("player_goals", 0.5, side)


@pytest.mark.parametrize("line", [1.5, 2.5, None])
def test_higher_rungs_stay_on_the_ladder(line):
    r = _row(line=line)
    assert (r.market_type, r.line, r.side) == ("player_goals", line, "over")


def test_hockey_goals_ladder_is_untouched():
    r = _row(league="nhl")
    assert (r.market_type, r.line, r.side) == ("player_goals", 0.5, "over")


def test_other_markets_untouched():
    r = _row(market_type="player_assists")
    assert (r.market_type, r.line, r.side) == ("player_assists", 0.5, "over")


def test_unknown_side_is_not_folded():
    assert fold_anytime_goalscorer("epl", "player_goals", 0.5, "draw") is None
