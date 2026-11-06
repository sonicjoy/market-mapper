"""MLB F3: Optic 1st_3_innings_moneyline_3-way emits Home/Away/Draw.

Crypto.com lists F3 Moneyline (3-Way) plus Spread/Total Runs. Optic only
prices the 3-way ML (no 1st_3_innings run-line or total as of 2026-09-02),
so crypto F3 spread/total stay unwired. Draw legs in BQ often carry
team_id="" rather than SQL null — build_rows must still emit _TIE.
"""

from mappers.exchanges import optic
from mappers.exchanges.optic import OpticConfig
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE
from mappers.vocab.baseball_markets import BASEBALL_OPTIC_TABLE_TYPES

_HOME, _AWAY = "SEA", "BOS"
_HOME_NAME, _AWAY_NAME = "Seattle Mariners", "Boston Red Sox"
_START = "2026-09-02T02:10:00Z"
_TEAM_MAP = {"T_SEA": _HOME, "T_BOS": _AWAY}
_CFG = OpticConfig(league_id="mlb", table_types=dict(BASEBALL_OPTIC_TABLE_TYPES))


def _odd(market_id: str, selection: str, *, team_id=None) -> optic.Odd:
    return optic.Odd(
        id=f"FIX1:book:{market_id}:{selection}",
        market_id=market_id,
        market=market_id,
        selection=selection,
        team_id=team_id,
        grouping_key="default",
    )


def _rows(*odds: optic.Odd) -> list[optic.CanonicalRow]:
    fixture = optic.Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-09-01T22:10:00", start_date=_START,
        home=_HOME, away=_AWAY, home_name=_HOME_NAME, away_name=_AWAY_NAME,
        team_map=_TEAM_MAP, odds=list(odds), is_live=False,
    )
    rows, _, _ = optic.build_rows(_START, _HOME, _AWAY, fixture, _CFG, league="mlb")
    return rows


def test_optic_f3_table_type_is_three_way_ml_only():
    assert _CFG.table_types["1st_3_innings_moneyline_3-way"] == (
        MarketType.FIRST_THREE_MONEYLINE_3WAY
    )
    assert "1st_3_innings_run_line" not in _CFG.table_types
    assert "1st_3_innings_total_runs" not in _CFG.table_types


def test_optic_emits_f3_moneyline_3way_home_away_draw():
    rows = _rows(
        _odd("1st_3_innings_moneyline_3-way", _HOME_NAME, team_id="T_SEA"),
        _odd("1st_3_innings_moneyline_3-way", _AWAY_NAME, team_id="T_BOS"),
        _odd("1st_3_innings_moneyline_3-way", "Draw"),
    )
    by_side = {r.side: r for r in rows}
    assert set(by_side) == {_HOME, _AWAY, TIE_SIDE}
    assert all(r.market_type == "f3_moneyline_3way" and r.line is None for r in rows)


def test_optic_f3_draw_blank_team_id_is_tie():
    rows = _rows(
        _odd("1st_3_innings_moneyline_3-way", _HOME_NAME, team_id="T_SEA"),
        _odd("1st_3_innings_moneyline_3-way", "Draw", team_id=""),
    )
    assert {r.side for r in rows} == {_HOME, TIE_SIDE}
