"""Underdog NCAA men's basketball (UDXNCAAMBB*, listed 2026-10-30).

Live wording from the prod catalogue, 2026-10-30. GAMEWIN, SPREAD and TOTAL
settle on the entire game including overtime, as Optic's ``moneyline``,
``point_spread`` and ``total_points``. GAMEWIN1H says "in the ... game", not
"during the first half", and OVERTIME counts jump balls; neither maps.
"""

from __future__ import annotations

from typing import Any

import pytest

from mappers.exchanges.underdog import parse_contract
from mappers.exchanges.underdog_pass import basketball_basis_stated
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport
from mappers.vocab.underdog_markets import UNDERDOG_LEAGUE_SLUGS, market_types_for_sport
from tests.mappers.test_tip_leagues import _row as _tip_row

_GAME = (
    "the NCAA Men's Basketball game between the High Point and the Liberty "
    "originally scheduled for 12:00am ET on November 2, 2026"
)
_HALF_GAME = (
    "the NCAA Men's Basketball game between the Villanova and the Notre Dame "
    "originally scheduled for 9:30am ET on November 1, 2026"
)
_NBA_HALF = (
    "Resolves Yes if the Charlotte Hornets beat the Washington Wizards by above 16.5 points during the "
    "first half of the National Basketball Association game between the Charlotte Hornets and the "
    "Washington Wizards originally scheduled for 7:00pm ET on November 1, 2026."
)


def _row(ticker: str, description: str, market_id: str, team_id: str | None = None) -> dict[str, Any]:
    optic = {"fixture_id": "202611020798CA77", "market_id": market_id}
    if team_id:
        optic["team_id"] = team_id
    return {
        "ticker": ticker,
        "description": description,
        "rules": "",
        "external_ids": {"optic_odds": optic},
        "expires_at": "2026-11-03T00:00:00.000000Z",
    }


def test_ncaab_is_a_code_league_with_the_basketball_table() -> None:
    assert "ncaab" in UNDERDOG_LEAGUE_SLUGS
    run = resolve_run_leagues({}, [_tip_row("ncaab", sport="basketball", optic="ncaab")])
    cfg = run["ncaab"].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["moneyline"] is MarketType.MONEYLINE
    assert cfg.market_types["point_spread"] is MarketType.POINT_SPREAD
    assert cfg.market_types["total_points"] is MarketType.GAME_TOTAL


def test_overtime_and_the_second_half_three_way_are_not_in_the_table() -> None:
    # The first half three-way maps (period alone, as Optic); the 2H counts overtime.
    table = market_types_for_sport(Sport.BASKETBALL)
    assert "will_there_be_overtime" not in table
    assert "2nd_half_moneyline_3-way" not in table
    assert table["1st_half_moneyline_3-way"] is MarketType.FIRST_HALF_WINNER_3WAY


@pytest.mark.parametrize(
    "row,yes_team,line",
    [
        (
            _row(
                "UDXNCAAMBBSPREAD_HPULIB26NOV02_HPU4.5",
                f"Resolves Yes if High Point beat the Liberty by at least 4.5 points in {_GAME}.",
                "point_spread",
            ),
            "High Point",
            4.5,
        ),
        (
            _row(
                "UDXNCAAMBBTOTAL_HPULIB26NOV02_154.5",
                f"Resolves Yes if there are above 154.5 points in {_GAME}.",
                "total_points",
            ),
            "",
            154.5,
        ),
    ],
)
def test_game_lines_parse(row: dict[str, Any], yes_team: str, line: float) -> None:
    contract = parse_contract(row)
    assert contract is not None
    assert contract.yes_team == yes_team
    assert contract.line == line


def test_game_winner_parses_the_named_team() -> None:
    row = _row(
        "UDXNCAAMBBGAMEWIN_HPULIB26NOV02_HPU",
        f"Resolves Yes if High Point win {_GAME}.",
        "moneyline",
    )
    contract = parse_contract(row)
    assert contract is not None
    assert contract.yes_team == "High Point"


def test_a_half_line_maps_only_when_its_sentence_names_the_half() -> None:
    ncaa_half = f"Resolves Yes if Villanova beat the Notre Dame by above 3.5 points in {_HALF_GAME}."
    assert not basketball_basis_stated(MarketType.FIRST_HALF_POINT_SPREAD, ncaa_half, "ncaab")
    assert not basketball_basis_stated(MarketType.FIRST_HALF_TOTAL, ncaa_half, "ncaab")
    assert basketball_basis_stated(MarketType.FIRST_HALF_POINT_SPREAD, _NBA_HALF, "nba")
    assert basketball_basis_stated(MarketType.POINT_SPREAD, ncaa_half, "ncaab")


def test_the_half_check_leaves_other_sports_alone() -> None:
    soccer = "Resolves Yes if there are above 0.5 goals in the match."
    assert basketball_basis_stated(MarketType.FIRST_HALF_TOTAL, soccer, "epl")
