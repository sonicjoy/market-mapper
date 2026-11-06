"""Unit tests for optic.build_rows' player-scoped YES_NO encodings.

Two feed shapes reach the same (PLAYER, YES_NO) branch:
  - over/under 0.5 (NBA double/triple-double) → converted to yes/no
  - affirmative-only, selection_line=None (soccer first_goal_scorer,
    probed live on the WC final 2026-07-19) → side always "yes"

The rest of build_rows is covered by the fixture integration
snapshots; these tests pin the branch itself with synthetic odds.
"""

from mappers.exchanges.optic import Fixture, Odd, OpticConfig, build_rows
from mappers.run import LEAGUES
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES

WC_OPTIC = LEAGUES['world_cup'].OPTIC

NBA_OPTIC = OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES))


def _fixture(odds: list[Odd], home: str, away: str) -> Fixture:
    return Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-07-19T15:00:00", start_date="2026-07-19T19:00:00Z",
        home=home, away=away, home_name=home, away_name=away,
        team_map={}, odds=odds, is_live=False,
    )


def _odd(market_id: str, selection: str, *, selection_line: str | None,
         points: float | None = None, player_id: str | None = "P1") -> Odd:
    return Odd(
        id=f"FIX1:book:{market_id}:{selection}", market_id=market_id,
        selection=selection, selection_line=selection_line, points=points,
        player_id=player_id, grouping_key="default",
    )


def test_first_goal_scorer_affirmative_only():
    """selection_line=None → one yes row per player, no line."""
    odds = [_odd("first_goal_scorer", "Lionel Messi", selection_line=None)]
    rows, _, _ = build_rows(
        "2026-07-19T19:00:00Z", "ESP", "ARG",
        _fixture(odds, "ESP", "ARG"), WC_OPTIC, league="world_cup")
    (row,) = rows
    assert row.market_type == "first_goal_scorer"
    assert row.entity == "lionel_messi"
    assert row.side == "yes"
    assert row.line is None


def test_first_goal_scorer_no_goal_selection():
    """The "No goal" selection ships player_id=null; it normalizes to
    no_goal, the entity Kalshi's -NOGOAL leg also produces."""
    odds = [_odd("first_goal_scorer", "No goal",
                 selection_line=None, player_id=None)]
    rows, _, _ = build_rows(
        "2026-07-19T19:00:00Z", "ESP", "ARG",
        _fixture(odds, "ESP", "ARG"), WC_OPTIC, league="world_cup")
    (row,) = rows
    assert row.entity == "no_goal"
    assert row.side == "yes"


def test_double_double_over_under_encoding_unchanged():
    """Regression: the over/under-0.5 encoding (NBA DD/TD) still
    converts to yes/no with no line."""
    odds = [
        _odd("player_double_double", "James Harden",
             selection_line="over", points=0.5),
        _odd("player_double_double", "James Harden",
             selection_line="under", points=0.5),
    ]
    rows, _, _ = build_rows(
        "2026-02-19T00:00:00Z", "CLE", "BKN",
        _fixture(odds, "CLE", "BKN"), NBA_OPTIC, league="nba")
    assert [(r.entity, r.side, r.line) for r in rows] == [
        ("james_harden", "yes", None),
        ("james_harden", "no", None),
    ]
