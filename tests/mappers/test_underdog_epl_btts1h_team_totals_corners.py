"""Underdog EPL 1H BTTS, team total goals, total and team corners (2026-10-23).

Live wording from UDXEPLBTTS1H / UDXEPLTEAMTOTAL / UDXEPLCORNERS /
UDXEPLTCORNERS (Brighton v Liverpool, 2026-10-25). Optic's grader settles
1st_half_both_teams_to_score on the first half (25/25 EPL matches), team_total
on the 90 minutes (43/43) and total / team corners on corners TAKEN, as UDX.
"""

from __future__ import annotations

from typing import Any

import pytest

from mappers.exchanges.underdog import build_rows, parse_contract
from mappers.exchanges.underdog_pass import soccer_basis_stated
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_WHEN = "originally scheduled for 10:00am ET on October 25, 2026."
_FX = "20261024413B0340"


def _row(ticker: str, description: str, market_id: str, team_id: str | None = None) -> dict[str, Any]:
    optic = {"fixture_id": _FX, "market_id": market_id}
    if team_id:
        optic["team_id"] = team_id
    return {
        "ticker": ticker, "description": description,
        "external_ids": {"optic_odds": optic},
        "expires_at": "2026-10-28T14:00:00.000000Z",
    }


_BTTS1H = _row(
    "UDXEPLBTTS1H_BHALIV26OCT25_BTTS",
    "Resolves Yes if both participating teams record at least 1 goals during the first half of "
    f"match between Brighton & Hove Albion FC and Liverpool FC {_WHEN}",
    "1st_half_both_teams_to_score",
)
_TEAMTOTAL = _row(
    "UDXEPLTEAMTOTAL_BHALIV26OCT25_BHA0.5",
    "Resolves Yes if Brighton & Hove Albion FC record above 0.5 goals during the entire game "
    "excluding extra time of match between Brighton & Hove Albion FC and Liverpool FC "
    f"{_WHEN}",
    "team_total", "263AF016D0C5",
)
_CORNERS = _row(
    "UDXEPLCORNERS_BHALIV26OCT25_10.5",
    "Resolves Yes if both participating teams combined record above 10.5 corner kicks taken "
    "during regulation time of English Premier League match between Liverpool FC and "
    f"Brighton & Hove Albion FC {_WHEN}",
    "total_corners",
)
_TCORNERS = _row(
    "UDXEPLTCORNERS_BHALIV26OCT25_LIV5.5",
    "Resolves Yes if Liverpool FC record above 5.5 corner kicks taken during regulation time "
    "of English Premier League match between Liverpool FC and Brighton & Hove Albion FC "
    f"{_WHEN}",
    "team_total_corners", "F799E43513D4",
)


def test_crosswalk_maps_the_four_soccer_ids():
    table = market_types_for_sport(Sport.SOCCER)
    assert table["1st_half_both_teams_to_score"] is MarketType.FIRST_HALF_BTTS
    assert table["team_total"] is MarketType.TEAM_TOTAL
    assert table["total_corners"] is MarketType.TOTAL_CORNERS
    assert table["team_total_corners"] is MarketType.TEAM_TOTAL_CORNERS


def _rows(row: dict[str, Any], mt: MarketType, team: str | None) -> list[tuple]:
    contract = parse_contract(row)
    assert contract is not None
    built = build_rows(contract, mt, home="BHA", away="LIV", start_date="2026-10-25T14:00:00Z",
                       league="epl", team=team)
    return [(r.side, r.entity, r.line, r.underdog_side) for r in built]


def test_first_half_btts_is_yes_no():
    assert _rows(_BTTS1H, MarketType.FIRST_HALF_BTTS, None) == [
        ("yes", None, None, "yes"), ("no", None, None, "no"),
    ]


def test_team_total_goals_is_over_under_with_the_team():
    assert _rows(_TEAMTOTAL, MarketType.TEAM_TOTAL, "BHA") == [
        ("over", "BHA", 0.5, "yes"), ("under", "BHA", 0.5, "no"),
    ]


def test_total_corners_is_over_under():
    assert _rows(_CORNERS, MarketType.TOTAL_CORNERS, None) == [
        ("over", None, 10.5, "yes"), ("under", None, 10.5, "no"),
    ]


def test_team_corners_is_over_under_with_the_team():
    assert _rows(_TCORNERS, MarketType.TEAM_TOTAL_CORNERS, "LIV") == [
        ("over", "LIV", 5.5, "yes"), ("under", "LIV", 5.5, "no"),
    ]


@pytest.mark.parametrize("row,mt", [
    (_BTTS1H, MarketType.FIRST_HALF_BTTS),
    (_TEAMTOTAL, MarketType.TEAM_TOTAL),
    (_CORNERS, MarketType.TOTAL_CORNERS),
    (_TCORNERS, MarketType.TEAM_TOTAL_CORNERS),
])
def test_live_sentences_state_their_basis(row: dict[str, Any], mt: MarketType):
    assert soccer_basis_stated(mt, row["description"], "epl")


def test_a_soccer_sentence_without_the_basis_maps_nothing():
    extra_time = _TEAMTOTAL["description"].replace(
        "during the entire game excluding extra time", "during the entire game including extra time",
    )
    assert not soccer_basis_stated(MarketType.TEAM_TOTAL, extra_time, "ucl")
    assert not soccer_basis_stated(
        MarketType.TOTAL_CORNERS, _CORNERS["description"].replace("during regulation time ", ""), "epl",
    )


def test_other_sports_team_totals_are_not_held():
    nba = ("Resolves Yes if the Atlanta Hawks records above 112.5 points scored during the entire "
           "game including overtime of the National Basketball Association game")
    assert soccer_basis_stated(MarketType.TEAM_TOTAL, nba, "nba")


def _run(catalogue: list[dict[str, Any]]):
    from types import SimpleNamespace

    from mappers.exchanges.underdog import UnderdogConfig
    from mappers.exchanges.underdog_pass import run_pass

    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=_FX, away="LIV", home="BHA",
        away_name="Liverpool FC", home_name="Brighton & Hove Albion FC",
        start_date="2026-10-25T14:00:00Z", team_map={}, odds=[],
    ))
    cfg = UnderdogConfig(league="EPL", market_types=market_types_for_sport(Sport.SOCCER))
    tally = run_pass(catalogue, cfg, [entry], league="epl", attach=attach, row_index={}, all_rows=[])
    return tally, stamped


def test_pass_stamps_the_live_rows_and_holds_an_unstated_basis():
    extra_time = dict(_TEAMTOTAL, ticker="UDXEPLTEAMTOTAL_BHALIV26OCT25_BHA1.5", description=(
        _TEAMTOTAL["description"].replace("0.5 goals", "1.5 goals").replace(
            "excluding extra time", "including extra time")))
    tally, stamped = _run([_BTTS1H, _TEAMTOTAL, _CORNERS, _TCORNERS, extra_time])
    assert tally["basis_unstated"] == 1
    assert {r.market_type for r in stamped} == {"1h_btts", "team_total", "total_corners", "team_total_corners"}
    assert all(r.line != 1.5 for r in stamped if r.market_type == "team_total")
