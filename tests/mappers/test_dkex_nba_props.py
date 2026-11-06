"""DKEX NBA player props: every staging token classifies, with the right line and sides.

Rows are real staging markets (one per token, rules text included) in
``tests/fixtures/dkex/staging_nba_props_2026-10-08.json``, run through
``fetch.dkex.normalize``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fetch.dkex import normalize
from mappers.exchanges.dkex import DkexConfig, build_rows, market_from_row
from mappers.market_types import MarketType as MT
from mappers.vocab import dkex_markets as vocab

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_nba_props_2026-10-08.json"
ALL = json.loads(FIXTURE.read_text(encoding="utf-8"))
RAW = {r["parameters"]["statAchievement"]: r for r in ALL if r["parameters"]["statAchievement"] != "MOVY"}
SPREADS = {r["parameters"]["timePeriod"]: r for r in ALL if r["parameters"]["statAchievement"] == "MOVY"}
NBA = DkexConfig(league="NBA", market_types=vocab.BASKETBALL, ignored_markets=vocab.BASKETBALL_IGNORED)

EXPECTED = {
    "PPTS": MT.PLAYER_POINTS, "PPTSOU": MT.PLAYER_POINTS,
    "PREB": MT.PLAYER_REBOUNDS, "PREBOU": MT.PLAYER_REBOUNDS,
    "PAST": MT.PLAYER_ASSISTS, "PASTOU": MT.PLAYER_ASSISTS,
    "P3PM": MT.PLAYER_THREES, "PBLK": MT.PLAYER_BLOCKS,
    "PPRB": MT.PLAYER_PTS_REB, "PPAS": MT.PLAYER_PTS_AST,
    "PRAS": MT.PLAYER_REB_AST,
    "PPRA": MT.PLAYER_PTS_REB_AST, "PPRAOU": MT.PLAYER_PTS_REB_AST,
    "DDBL": MT.PLAYER_DOUBLE_DOUBLE,
}


def _market(token: str):
    m = market_from_row(normalize(RAW[token], "api"))
    assert m is not None
    return m


def test_every_staging_token_is_covered() -> None:
    assert set(RAW) == set(EXPECTED)


@pytest.mark.parametrize("token", sorted(EXPECTED))
def test_token_classifies(token: str) -> None:
    assert NBA.market_type(_market(token)) is EXPECTED[token]


@pytest.mark.parametrize("token", sorted(set(EXPECTED) - {"DDBL"}))
def test_threshold_prop_is_over_under_at_its_strike(token: str) -> None:
    m = _market(token)
    line = NBA.line_for(m)
    assert line == m.strike and line is not None
    rows = build_rows(m, EXPECTED[token], line=line, home="HOU", away="DAL",
                      start_date="2026-10-22T00:40:00Z", league="NBA", player="P")
    assert [(r.side, r.line) for r in rows] == [("over", line), ("under", line)]


def test_double_double_is_yes_no_without_a_line() -> None:
    m = _market("DDBL")
    assert NBA.line_for(m) is None
    rows = build_rows(m, MT.PLAYER_DOUBLE_DOUBLE, line=None, home="HOU", away="DAL",
                      start_date="2026-10-22T00:40:00Z", league="NBA", player="P")
    assert [(r.side, r.line) for r in rows] == [("yes", None), ("no", None)]


@pytest.mark.parametrize("period,mt", [
    ("FG", MT.POINT_SPREAD), ("H1", MT.FIRST_HALF_POINT_SPREAD),
    ("Q1", MT.FIRST_QUARTER_POINT_SPREAD), ("Q2", MT.SECOND_QUARTER_POINT_SPREAD),
    ("Q3", MT.THIRD_QUARTER_POINT_SPREAD),
    ("H2", None),  # OT counts on DKEX, not on Optic (graded on regulation): held
    ("Q4", MT.FOURTH_QUARTER_POINT_SPREAD_INCL_OT),
])
def test_period_spreads(period: str, mt: MT | None) -> None:
    m = market_from_row(normalize(SPREADS[period], "api"))
    assert m is not None and NBA.market_type(m) is mt
