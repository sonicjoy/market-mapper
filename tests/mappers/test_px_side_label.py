"""Unit tests for ProphetX side-label resolution."""

import pytest

from mappers.exchanges.px import (
    OUTCOME_IDS_SPREAD,
    OUTCOME_IDS_TEAM,
    OUTCOME_IDS_TOTAL,
    OUTCOME_IDS_YESNO,
    Selection,
    _validate_moneyline_sels,
    build_rows,
    resolve_side_label,
)
from mappers.market_types import MarketType


def test_resolve_side_label_team_moneyline():
    comp = {10: "BRE", 20: "WHU"}
    assert resolve_side_label(
        Selection("l1", 4, 0.0, competitor_id=10), comp) == "BRE"
    assert resolve_side_label(
        Selection("l2", 5, 0.0, competitor_id=20), comp) == "WHU"


def test_resolve_side_label_spread_team():
    comp = {10: "BRE", 20: "WHU"}
    assert resolve_side_label(
        Selection("l1", 1714, -0.5, competitor_id=10), comp) == "BRE"
    assert resolve_side_label(
        Selection("l2", 1715, 0.5, competitor_id=20), comp) == "WHU"


def test_resolve_side_label_over_under():
    assert resolve_side_label(Selection("l1", 12, 0.0), {}) == "over"
    assert resolve_side_label(Selection("l2", 13, 0.0), {}) == "under"


def test_resolve_side_label_yes_no():
    assert resolve_side_label(Selection("l1", 1, 0.0), {}) == "yes"
    assert resolve_side_label(Selection("l2", 2, 0.0), {}) == "no"


def test_resolve_side_label_pre_resolved_team_abbr():
    # sup_moneyline POINT_SPREAD_YN stamps team_abbr at parse time.
    assert resolve_side_label(
        Selection("l1", 1, 0.0, team_abbr="BRE"), {}) == "BRE"


def test_moneyline_type_accepts_team_and_yesno_oids():
    """PX type=moneyline hosts both team ML ({4,5}) and yes/no props ({1,2})."""
    team = [
        Selection("l1", 4, 0.0, competitor_id=10),
        Selection("l2", 5, 0.0, competitor_id=20),
    ]
    yn = [
        Selection("l1", 1, 0.0),
        Selection("l2", 2, 0.0),
    ]
    _validate_moneyline_sels(team, "Moneyline")
    _validate_moneyline_sels(yn, "James Harden To Record a Double Double")
    assert {4, 5} == OUTCOME_IDS_TEAM
    assert {1, 2} == OUTCOME_IDS_YESNO
    assert {1714, 1715} == OUTCOME_IDS_SPREAD
    assert {12, 13} == OUTCOME_IDS_TOTAL


def test_build_rows_rejects_yesno_sides_on_team_moneyline():
    """Shape.MONEYLINE with oids {1,2} would stamp side=yes/no — fail closed."""
    from mappers.exchanges.px import ClassifiedMarket, Line, Market

    raw = Market(
        id=1, name="Moneyline", type="moneyline", status="open",
        sport_event_id=99,
    )
    sels = [
        Selection("l1", 1, 0.0, competitor_id=10),
        Selection("l2", 2, 0.0, competitor_id=20),
    ]
    market = ClassifiedMarket(
        market_type=MarketType.MONEYLINE,
        raw=raw,
        market_lines=[Line(line=None, selections=sels)],
    )
    with pytest.raises(ValueError, match="team moneyline got yes/no"):
        build_rows(
            "2026-07-31T00:00:00Z", "BRE", "WHU", [market],
            {10: "BRE", 20: "WHU"}, league="epl")
