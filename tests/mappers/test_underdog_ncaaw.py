"""Underdog NCAA women's basketball (UDXNCAAWBB*, listed 2026-11-05).

The NCAAWBB filings settle the full game on regulation plus any overtime
("Where not specified otherwise, <time period> shall be understood to refer to
the sum of regulation time and any officially designated overtime periods"),
as Optic's ``moneyline``, ``point_spread`` and ``total_points`` and as NCAAMBB.
Replay on the live catalogue, 2026-11-05: 2,454 stamps on 1,290 of 1,312
contracts, each on the venue's own Optic fixture, market and team.
"""

from __future__ import annotations

from typing import Any

from mappers.exchanges.underdog import parse_contract
from mappers.exchanges.underdog_pass import basketball_basis_stated
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport, sport_for_league
from mappers.vocab.underdog_markets import UNDERDOG_LEAGUE_SLUGS
from tests.mappers.test_tip_leagues import _row as _tip_row

_GAME = (
    "the NCAA Women's Basketball game between the Alabama A&M and the Alabama "
    "originally scheduled for 7:00pm ET on November 5, 2026"
)


def _row(ticker: str, description: str, market_id: str, team_id: str | None = None) -> dict[str, Any]:
    optic = {"fixture_id": "2026110565C66BCB", "market_id": market_id}
    if team_id:
        optic["team_id"] = team_id
    return {
        "ticker": ticker,
        "description": description,
        "rules": "",
        "external_ids": {"optic_odds": optic},
        "expires_at": "2026-11-08T15:00:00.000000Z",
    }


def test_ncaaw_is_a_code_league_with_the_basketball_table() -> None:
    assert "ncaaw" in UNDERDOG_LEAGUE_SLUGS
    assert sport_for_league("ncaaw") is Sport.BASKETBALL
    run = resolve_run_leagues({}, [_tip_row("ncaaw", sport="basketball", optic="ncaaw")])
    cfg = run["ncaaw"].UNDERDOG
    assert cfg is not None
    assert cfg.market_types["moneyline"] is MarketType.MONEYLINE
    assert cfg.market_types["point_spread"] is MarketType.POINT_SPREAD
    assert cfg.market_types["total_points"] is MarketType.GAME_TOTAL


def test_live_game_lines_parse() -> None:
    win = parse_contract(
        _row("UDXNCAAWBBGAMEWIN_AAMUALA26NOV05_AAMU", f"Resolves Yes if Alabama A&M win {_GAME}.", "moneyline")
    )
    spread = parse_contract(
        _row(
            "UDXNCAAWBBSPREAD_AAMUALA26NOV05_ALA11.5",
            f"Resolves Yes if Alabama beat the Alabama A&M by at least 11.5 points in {_GAME}.",
            "point_spread",
        )
    )
    total = parse_contract(
        _row(
            "UDXNCAAWBBTOTAL_AAMUALA26NOV05_110.5",
            f"Resolves Yes if there are above 110.5 points in {_GAME}.",
            "total_points",
        )
    )
    assert win is not None and win.yes_team == "Alabama A&M"
    assert spread is not None and spread.yes_team == "Alabama" and spread.line == 11.5
    assert total is not None and total.yes_team == "" and total.line == 110.5


def test_a_half_line_needs_its_half_in_the_sentence() -> None:
    game_wording = f"Resolves Yes if Alabama beat the Alabama A&M by at least 5.5 points in {_GAME}."
    assert not basketball_basis_stated(MarketType.FIRST_HALF_POINT_SPREAD, game_wording, "ncaaw")
    assert basketball_basis_stated(MarketType.POINT_SPREAD, game_wording, "ncaaw")
