"""Underdog UDXNBATOTAL1Q / UDXNBASPREAD1Q onto Optic's 1st_quarter ids.

Live wording from the prod catalogue, 2026-11-05 (MIA @ GSW, Optic fixture 20261106DE5BCAFF);
both rows carry ``external_ids.optic_odds.market_id`` ``1st_quarter_total_points`` /
``1st_quarter_point_spread`` and were UNMAPPED_OPTIC before the vocab line.
"""

from __future__ import annotations

from mappers.exchanges.underdog import parse_contract
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_GAME = (
    "the National Basketball Association game between the Miami Heat and the Golden State "
    "Warriors originally scheduled for 10:00pm ET on November 5, 2026"
)


def _row(ticker: str, description: str, market_id: str) -> dict:
    return {
        "ticker": ticker,
        "description": description,
        "rules": "",
        "external_ids": {"optic_odds": {"fixture_id": "20261106DE5BCAFF", "market_id": market_id}},
        "expires_at": "2026-11-09T03:00:00.000000Z",
    }


def test_vocab_maps_the_quarter_ids() -> None:
    table = market_types_for_sport(Sport.BASKETBALL)
    assert table["1st_quarter_total_points"] is MarketType.FIRST_QUARTER_TOTAL
    assert table["1st_quarter_point_spread"] is MarketType.FIRST_QUARTER_POINT_SPREAD


def test_quarter_total_parses() -> None:
    c = parse_contract(_row(
        "UDXNBATOTAL1Q_MIAGSW26NOV052200_53.5",
        f"Resolves Yes if there are above 53.5 points during the first quarter of {_GAME}.",
        "1st_quarter_total_points",
    ))
    assert c is not None and c.line == 53.5


def test_quarter_spread_parses_with_the_named_team() -> None:
    c = parse_contract(_row(
        "UDXNBASPREAD1Q_MIAGSW26NOV052200_GSW1.5",
        f"Resolves Yes if the Golden State Warriors beat the Miami Heat by above 1.5 points "
        f"during the first quarter of {_GAME}.",
        "1st_quarter_point_spread",
    ))
    assert c is not None and c.line == 1.5 and c.yes_team == "Golden State Warriors"
