"""Optic build_rows must skip malformed NFL/NCAAF period odds, not abort."""

from mappers.exchanges.optic import Fixture, Odd, OpticConfig, build_rows
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES

_CFG = OpticConfig(
    league_id="ncaaf",
    table_types=dict(FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES),
)


def _fixture(odds: list[Odd]) -> Fixture:
    return Fixture(
        fixture_id="FIX1",
        game_id="GAME1",
        sportradar_id=None,
        start_et="2026-09-10T12:00:00",
        start_date="2026-09-10T16:00:00Z",
        home="ALA",
        away="UGA",
        home_name="Alabama",
        away_name="Georgia",
        team_map={"t1": "ALA", "t2": "UGA"},
        odds=odds,
        is_live=False,
    )


def _odd(
    market_id: str,
    selection: str,
    *,
    selection_line: str | None = "",
    points: float | None = None,
    team_id: str | None = None,
    player_id: str | None = None,
) -> Odd:
    return Odd(
        id=f"FIX1:book:{market_id}:{selection}",
        market_id=market_id,
        selection=selection,
        selection_line=selection_line,
        points=points,
        team_id=team_id,
        player_id=player_id,
        grouping_key="default",
    )


def _rows(odds: list[Odd]) -> tuple[list, dict]:
    rows, odd_lookup, _ = build_rows(
        "2026-09-10T16:00:00Z",
        "ALA",
        "UGA",
        _fixture(odds),
        _CFG,
        league="ncaaf",
    )
    return rows, odd_lookup


def test_ncaaf_spread_without_points_is_skipped_not_fatal():
    rows, odd_lookup = _rows([
        _odd("1st_half_point_spread", "Alabama", points=None, team_id="t1"),
        _odd("moneyline", "Alabama", points=None, team_id="t1"),
    ])
    assert len(rows) == 1
    assert rows[0].market_type == "moneyline"
    assert len(odd_lookup) == 1


def test_ncaaf_first_td_blank_selection_line_is_yes():
    """Optic first-TD rows often ship selection_line=''; do not assert."""
    rows, _ = _rows([
        _odd("first_touchdown_scorer", "Jahmyr Gibbs", player_id="P1"),
        _odd("moneyline", "Alabama", team_id="t1"),
    ])
    kinds = {row.market_type for row in rows}
    assert kinds == {"first_touchdown_scorer", "moneyline"}
    td = next(row for row in rows if row.market_type == "first_touchdown_scorer")
    assert td.entity == "jahmyr_gibbs"
    assert td.side == "yes"
    assert td.line is None


def test_will_there_be_overtime_yes_no_does_not_raise():
    """Live Optic OT (MLB/Valorant 90d census) is literal Yes/No."""
    rows, _ = _rows([
        Odd(
            id="FIX1:book:ot:Yes",
            market_id="will_there_be_overtime",
            selection="Yes",
            name="Yes",
            normalized_selection="yes",
            selection_line="",
            points=0.0,
            grouping_key="default",
        ),
        Odd(
            id="FIX1:book:ot:No",
            market_id="will_there_be_overtime",
            selection="No",
            name="No",
            normalized_selection="no",
            selection_line="",
            points=0.0,
            grouping_key="default",
        ),
    ])
    ot = [row for row in rows if row.market_type == "will_there_be_overtime"]
    assert {row.side for row in ot} == {"yes", "no"}
    assert all(row.line is None and row.grouping_key is None for row in ot)


def test_race_to_points_line_from_market_id_when_points_null():
    rows, _ = _rows([
        _odd("race_to_14_points", "Alabama", team_id="t1", points=None),
        _odd("1st_half_moneyline_3-way", "Alabama", team_id="t1"),
    ])
    race = next(row for row in rows if row.market_type == "race_to_points")
    assert race.line == 14.0
    assert race.side == "ALA"
    half = next(row for row in rows if row.market_type == "1h_winner_3way")
    assert half.line is None


def test_ncaaf_first_td_unknown_selection_line_is_skipped_not_fatal():
    rows, odd_lookup = _rows([
        _odd(
            "first_touchdown_scorer",
            "Jahmyr Gibbs",
            selection_line="anytime",
            player_id="P1",
        ),
        _odd("moneyline", "Alabama", team_id="t1"),
    ])
    assert [row.market_type for row in rows] == ["moneyline"]
    assert len(odd_lookup) == 1
