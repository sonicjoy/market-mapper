"""Tests for the shared-taxonomy additions: new League/Sport members and
new MLB player-prop / 1st-inning MarketTypes.

These are additive-only checks — they don't touch any existing member,
just confirm the new ones resolve correctly (SPORT_MAP lookups, and the
(scope, shape) tuples new build_rows dispatch will key on).
"""

import re
from pathlib import Path

import pytest

from mappers.market_types import MarketType, Scope, Shape
from mappers.sport import Sport, sport_for_league

_REPO = Path(__file__).resolve().parents[2]

# === New League members resolve in SPORT_MAP ===

@pytest.mark.parametrize("league,sport", [
    ("wnba", Sport.BASKETBALL),
    ("mls", Sport.SOCCER),
    ("liga_mx", Sport.SOCCER),
    ("ucl", Sport.SOCCER),
    ("ufc", Sport.MMA),
])
def test_new_league_sport_map(league, sport):
    assert sport_for_league(league) == sport


def test_sport_has_mma():
    assert Sport.MMA == "mma"


# === New MarketTypes have the intended (scope, shape) ===

@pytest.mark.parametrize("market_type,value", [
    (MarketType.PLAYER_HOME_RUNS, "player_home_runs"),
    (MarketType.PLAYER_STRIKEOUTS, "player_strikeouts"),
    (MarketType.PLAYER_HITS, "player_hits"),
    (MarketType.PLAYER_BASES, "player_bases"),
    (MarketType.PLAYER_HITS_RUNS_RBIS, "player_hits_runs_rbis"),
    (MarketType.PLAYER_RBIS, "player_rbis"),
    (MarketType.PLAYER_STOLEN_BASES, "player_stolen_bases"),
    (MarketType.PLAYER_OUTS, "player_outs"),
    (MarketType.PLAYER_PASSING_YARDS, "player_passing_yards"),
    (MarketType.PLAYER_INTERCEPTIONS, "player_interceptions"),
    (MarketType.PLAYER_PASSING_TOUCHDOWNS, "player_passing_touchdowns"),
    (MarketType.PLAYER_RECEIVING_YARDS, "player_receiving_yards"),
    (MarketType.PLAYER_RECEPTIONS, "player_receptions"),
    (MarketType.PLAYER_RUSHING_YARDS, "player_rushing_yards"),
    (MarketType.PLAYER_RUSHING_ATTEMPTS, "player_rushing_attempts"),
    (MarketType.PLAYER_PASSING_ATTEMPTS, "player_passing_attempts"),
    (MarketType.PLAYER_PASSING_COMPLETIONS, "player_passing_completions"),
    (MarketType.PLAYER_LONGEST_RECEPTION, "player_longest_reception"),
    (MarketType.PLAYER_LONGEST_RUSH, "player_longest_rush"),
    (MarketType.PLAYER_LONGEST_PASSING_COMPLETION, "player_longest_passing_completion"),
    (MarketType.PLAYER_RUSHING_RECEIVING_YARDS, "player_rushing_+_receiving_yards"),
    (MarketType.PLAYER_PASSING_RUSHING_YARDS, "player_passing_+_rushing_yards"),
    (MarketType.PLAYER_TACKLES_ASSISTS, "player_tackles_+_assists"),
    (MarketType.PLAYER_KICKING_POINTS, "player_kicking_points"),
    (MarketType.PLAYER_TOUCHDOWNS, "player_touchdowns"),
])
def test_new_mlb_player_props_are_player_over_under(market_type, value):
    assert market_type.value == value
    assert market_type.scope == Scope.PLAYER
    assert market_type.shape == Shape.OVER_UNDER


def test_first_three_moneyline_3way_is_game_three_way():
    mt = MarketType.FIRST_THREE_MONEYLINE_3WAY
    assert mt.value == "f3_moneyline_3way"
    assert mt.scope == Scope.GAME
    assert mt.shape == Shape.THREE_WAY


def test_first_quarter_and_first_td_shapes():
    assert MarketType.FIRST_QUARTER_WINNER_3WAY.shape == Shape.THREE_WAY
    assert MarketType.FIRST_QUARTER_POINT_SPREAD.shape == Shape.SPREAD
    assert MarketType.FIRST_QUARTER_TOTAL.shape == Shape.TOTAL
    assert MarketType.FIRST_TOUCHDOWN_SCORER.scope == Scope.PLAYER
    assert MarketType.FIRST_TOUCHDOWN_SCORER.shape == Shape.YES_NO


def test_football_team_stat_totals_are_team_total_shape():
    assert MarketType.TEAM_TOTAL_TOUCHDOWNS.scope == Scope.TEAM
    assert MarketType.TEAM_TOTAL_TOUCHDOWNS.shape == Shape.TOTAL
    assert MarketType.TEAM_TOTAL_FIELD_GOALS.scope == Scope.TEAM
    assert MarketType.TEAM_TOTAL_FIELD_GOALS.shape == Shape.TOTAL
    assert MarketType.TEAM_TOTAL_SACKS.shape == Shape.TOTAL
    assert MarketType.TOTAL_TOUCHDOWNS.scope == Scope.GAME
    assert MarketType.WILL_THERE_BE_OVERTIME.shape == Shape.YES_NO
    assert MarketType.RACE_TO_POINTS.shape == Shape.THREE_WAY
    assert MarketType.WINNING_MARGIN_5WAY.scope == Scope.TEAM


def _csv_canonical_types() -> set[str]:
    rows = (_REPO / "docs/mapping-rules/canonical_types.csv").read_text(
        encoding="utf-8",
    ).splitlines()[1:]
    return {line.split(",")[0] for line in rows if line.strip()}


def _ts_canonical_types() -> list[str]:
    text = (_REPO / "console/src/entryEnums.ts").read_text(encoding="utf-8")
    block = text.split("export const CANONICAL_MARKET_TYPES = [", 1)[1]
    block = block.split("] as const", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def test_console_canonical_types_match_enum_and_are_sorted():
    values = sorted(mt.value for mt in MarketType)
    assert _csv_canonical_types() == set(values)
    ts = _ts_canonical_types()
    assert ts == values
