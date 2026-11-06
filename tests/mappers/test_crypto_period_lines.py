"""crypto.com NBA/NCAAB team totals, NBA period lines, soccer half lines."""

from __future__ import annotations

import json

import mappers.pipeline  # noqa: F401  (the vocab modules import each other circularly otherwise)

from mappers.exchanges.crypto_com import build_rows, parse_selection
from mappers.exchanges.crypto_soccer import soccer_crypto_config
from mappers.market_types import MarketType as M
from mappers.vocab.basketball_markets import NBA_CRYPTO, NCAAB_CRYPTO, WNBA_CRYPTO

_ALIASES = {"H": "DET", "A": "BOS", "T-DET": "DET"}


def _sel(group, contract, period, outcome, value=None, *, team_id=None, participant=None):
    return parse_selection(json.dumps({
        "SecurityID": f"S-{contract}-{period}", "Symbol": "NX.F.OPT.NBA-00001-261020-M.O.1.1.20270731",
        "eventMetaLEAGUE": "NBA", "eventMetaSPORTS_GROUPING": "NBA",
        "eventMetaEVENT_DATE": "2026-10-20T19:00:00+00:00", "eventMetaPREDICT_MARKET_TYPE": group,
        "eventMetaPREDICT_CONTRACT_TYPE": contract, "eventMetaPREDICT_PERIOD_TYPE": period,
        "eventMetaPREDICT_OUTCOME_TYPE": outcome, "eventMetaPREDICT_VALUE": value,
        "eventName": "x", "eventMetaPREDICT_MARKET_ID": "MKT", "eventMetaPREDICT_OUTCOME_ID": "OUT",
        "eventMetaPARTICIPANT": participant, "eventMetaTEAM_ID": team_id,
        "eventMetaEXTERNAL_HOME_ID": "H", "eventMetaEXTERNAL_AWAY_ID": "A", "eventMetaEXTERNAL_GAME_ID": "G",
        "eventMetaHOME_PARTICIPANT": "Detroit Pistons", "eventMetaAWAY_PARTICIPANT": "Boston Celtics",
    }))


def _rows(sel, cfg, league="nba"):
    return build_rows("2026-10-20T19:00:00+00:00", "DET", "BOS", [sel], cfg,
                      aliases=_ALIASES, league=league)


def test_nba_team_total_binds_team_from_typed_team_id() -> None:
    (row,) = _rows(_sel("Team Prop", "Team Total", "Full-Game", "Over", 102.5,
                        team_id="T-DET", participant="Pistons"), NBA_CRYPTO)
    assert (row.market_type, row.entity, row.line, row.side) == (
        M.TEAM_TOTAL.value, "DET", 102.5, "over")


def test_ncaab_team_total_maps_wnba_does_not() -> None:
    sel = _sel("Team Prop", "Team Total", "Full-Game", "Under", 70.5, team_id="T-DET")
    assert len(_rows(sel, NCAAB_CRYPTO, "ncaab")) == 1
    assert _rows(sel, WNBA_CRYPTO, "wnba") == []


def test_nba_period_lines() -> None:
    cases = [
        ("Total Points", "3rd Quarter", "Over", 55.5, M.THIRD_QUARTER_TOTAL),
        ("Spread", "1st Half", "Home", -1.5, M.FIRST_HALF_POINT_SPREAD),
        ("Moneyline (3-Way)", "1st Quarter", "Draw", None, M.FIRST_QUARTER_WINNER_3WAY),
    ]
    for contract, period, outcome, value, mt in cases:
        (row,) = _rows(_sel("Game Line", contract, period, outcome, value), NBA_CRYPTO)
        assert row.market_type == mt.value


def test_soccer_half_lines_and_half_btts() -> None:
    cfg = soccer_crypto_config("EPL")
    cases = [
        ("Game Line", "Total Goals", "1st Half", "Over", 0.5, M.FIRST_HALF_TOTAL),
        ("Game Line", "Spread", "2nd Half", "Home", -0.5, M.SECOND_HALF_POINT_SPREAD),
        ("Game Line", "Moneyline (3-Way)", "1st Half", "Draw", None, M.FIRST_HALF_WINNER_3WAY),
        ("Game Prop", "Both Teams To Score", "2nd Half", "Yes", None, M.SECOND_HALF_BTTS),
        ("Game Prop", "Both Teams To Score", "90 Minutes and Stoppage Time", "Yes", None, M.BTTS),
    ]
    for group, contract, period, outcome, value, mt in cases:
        (row,) = _rows(_sel(group, contract, period, outcome, value), cfg, "epl")
        assert row.market_type == mt.value


def test_nba_second_half_and_fourth_quarter_stay_unmapped() -> None:
    """Overtime basis unclear, so no row."""
    for contract, period in (("Total Points", "2nd Half"), ("Total Points", "4th Quarter")):
        assert _rows(_sel("Game Line", contract, period, "Over", 55.5), NBA_CRYPTO) == []


def test_nfl_race_to_points_sides_and_line() -> None:
    from mappers.vocab.football_markets import NFL_CRYPTO
    got = {}
    for outcome in ("Home", "Away", "Neither"):
        (row,) = _rows(_sel("Game Prop", "Race to 10 Points", "Full-Game", outcome), NFL_CRYPTO, "nfl")
        got[outcome] = (row.market_type, row.entity, row.line, row.side)
    rt = M.RACE_TO_POINTS.value
    assert got == {"Home": (rt, None, 10.0, "DET"), "Away": (rt, None, 10.0, "BOS"),
                   "Neither": (rt, None, 10.0, "_TIE")}
    # Optic has no race to 30.
    assert _rows(_sel("Game Prop", "Race to 30 Points", "Full-Game", "Home"), NFL_CRYPTO, "nfl") == []


def test_soccer_first_team_to_score_no_goal_is_tie() -> None:
    cfg = soccer_crypto_config("EPL")
    sides = []
    for outcome in ("Home", "Away", "No Goal"):
        (row,) = _rows(_sel("Game Prop", "First Team To Score", "90 Minutes and Stoppage Time", outcome),
                       cfg, "epl")
        assert row.market_type == M.FIRST_TEAM_TO_SCORE.value
        sides.append(row.side)
    assert sides == ["DET", "BOS", "_TIE"]


def test_race_yes_with_participant_binds_team_yes_without_stays_unmapped() -> None:
    from mappers.vocab.football_markets import NFL_CRYPTO
    (row,) = _rows(_sel("Game Prop", "Race to 14 Points", "Full-Game", "Yes",
                        team_id="T-DET", participant="Pistons"), NFL_CRYPTO, "nfl")
    assert (row.line, row.side) == (14.0, "DET")
    assert _rows(_sel("Game Prop", "Race to 14 Points", "Full-Game", "Yes"), NFL_CRYPTO, "nfl") == []
