"""PX soccer 90-minute result shipped as three YES/NO markets.

Argentina v Benin (PX event 90123170, 2026-10-06) lists the result as
"Argentina to Win (90 Min)", "Benin to Win (90 Min)" and "Draw (90 Min)",
each with YES/NO selections, instead of one three-selection market.
"""

import pytest

from mappers.exchanges.px import (
    Market,
    PxConfig,
    build_rows,
    classify_and_enrich,
    group_markets,
    validate_markets,
)
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE

CFG = PxConfig(
    tournament_id=54,
    exact={"Draw (90 Min)": MarketType.MONEYLINE_3WAY},
    suffix=[(" to Win (90 Min)", MarketType.MONEYLINE_3WAY)],
)
ETM = {"ARG": "ARG", "BEN": "BEN", "Argentina": "ARG", "Benin": "BEN"}


def _yes_no(mid: int, name: str) -> Market:
    return Market(
        id=mid, name=name, type="moneyline", status="active",
        sport_event_id=90123170,
        selections=[
            {"display_name": "YES", "line": 0, "line_id": f"{mid}y",
             "name": "YES", "outcome_id": 1},
            {"display_name": "NO", "line": 0, "line_id": f"{mid}n",
             "name": "NO", "outcome_id": 2},
        ],
    )


def _classified(names: list[str]) -> list:
    return [
        classify_and_enrich(_yes_no(1325 + i, n), CFG, {}, ETM)
        for i, n in enumerate(names)
    ]


LEGS = ["Argentina to Win (90 Min)", "Benin to Win (90 Min)", "Draw (90 Min)"]


def test_yes_leg_binds_team_or_tie_and_no_is_dropped():
    markets = _classified(LEGS)
    sides = [
        [(s.team_abbr, s.line_id) for s in m.market_lines[0].selections]
        for m in markets
    ]
    assert sides == [
        [("ARG", "1325y")], [("BEN", "1326y")], [(TIE_SIDE, "1327y")],
    ]


def test_build_rows_emits_home_away_and_tie():
    markets = _classified(LEGS)
    validate_markets(group_markets(markets), "ARG", "BEN", label="t")
    rows = build_rows(
        start_date="2026-10-06T23:00:00Z", home="ARG", away="BEN",
        markets=markets, comp_map={}, league="international_friendlies",
    )
    assert [(r.market_type, r.side, r.px_line_id) for r in rows] == [
        ("moneyline_3way", "ARG", "1325y"),
        ("moneyline_3way", "BEN", "1326y"),
        ("moneyline_3way", TIE_SIDE, "1327y"),
    ]


def test_unknown_team_maps_nothing_instead_of_raising():
    (market,) = _classified(["Brazil to Win (90 Min)"])
    assert market.market_lines == []


def test_duplicate_legs_rejected():
    markets = _classified([LEGS[0], LEGS[0]])
    with pytest.raises(ValueError, match="not distinct YES/NO legs"):
        validate_markets(group_markets(markets), "ARG", "BEN", label="t")


def test_unknown_team_leg_does_not_fail_validation():
    markets = _classified([LEGS[0], "Brazil to Win (90 Min)", LEGS[2]])
    validate_markets(group_markets(markets), "ARG", "BEN", label="t")
