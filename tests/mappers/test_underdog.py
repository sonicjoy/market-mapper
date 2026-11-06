"""Underdog UDX contracts read from typed fields and the venue sentence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mappers.exchanges.underdog import (
    UnderdogConfig,
    build_rows,
    needs_team,
    parse_contract,
    sentence_line,
    sentence_start,
    sentence_teams,
)
from mappers.market_types import MarketType
from mappers.profiles.registry import profile_registered
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_live_2026-10-09.json"
_LIVE = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _row(event: str, ticker: str) -> dict:
    return next(r for r in _LIVE[event]["rows"] if r["ticker"] == ticker)


def test_profile_registered_for_every_sport_with_a_table() -> None:
    for sport in (
        Sport.FOOTBALL, Sport.BASEBALL, Sport.BASKETBALL, Sport.TENNIS,
        Sport.SOCCER, Sport.MMA, Sport.HOCKEY,
    ):
        assert profile_registered("underdog_generic_v1", sport)
        assert market_types_for_sport(sport)


def test_contract_reads_typed_ids_and_the_sentence() -> None:
    row = _row("nfl", "UDXNFLGAMEWIN_BALATL26OCT112020_ATL")
    contract = parse_contract(row)
    assert contract is not None
    assert contract.market_id == "moneyline"
    assert contract.fixture_id == _LIVE["nfl"]["fixture_id"]
    assert contract.sides == ("Baltimore Ravens", "Atlanta Falcons")
    assert contract.yes_team == "Atlanta Falcons"
    assert contract.start is not None
    assert contract.start.isoformat() == "2026-10-12T00:20:00+00:00"  # 8:20pm EDT
    assert contract.line is None
    assert not contract.is_draw


def test_ticker_is_an_opaque_key() -> None:
    row = dict(_row("nfl", "UDXNFLGAMEWIN_BALATL26OCT112020_ATL"), ticker="opaque-1")
    contract = parse_contract(row)
    assert contract is not None
    assert contract.ticker == "opaque-1"
    assert contract.market_id == "moneyline"
    assert contract.yes_team == "Atlanta Falcons"


def test_row_without_optic_ids_is_unparsed() -> None:
    row = dict(_row("nfl", "UDXNFLGAMEWIN_BALATL26OCT112020_ATL"), external_ids={})
    assert parse_contract(row) is None


def test_sentence_without_kickoff_still_parses_for_nba_props() -> None:
    row = next(r for r in _LIVE["nba"]["rows"] if r["external_ids"]["optic_odds"]["market_id"] == "player_points")
    contract = parse_contract(row)
    assert contract is not None
    assert contract.start is None
    assert contract.sides == ("Houston Rockets", "Dallas Mavericks")
    assert contract.player == "Alperen Sengun"
    assert contract.line is not None


def test_sentence_start_reads_both_forms_in_eastern_time() -> None:
    a = sentence_start("... originally scheduled for 5:00pm ET on October 10, 2026.")
    b = sentence_start("... originally scheduled for October 9, 2026 at 8:00pm ET?")
    assert a is not None and a.isoformat() == "2026-10-10T21:00:00+00:00"
    assert b is not None and b.isoformat() == "2026-10-10T00:00:00+00:00"
    assert sentence_start("Will the winner be decided?") is None


@pytest.mark.parametrize(("text", "line"), [
    ("Resolves Yes if X beat Y by at least 2.5 points in the NFL game", 2.5),
    ("Resolves Yes if there are above 43.5 points in the NFL game", 43.5),
    ("Resolves Yes if A wins at least 0.5 more games than their opponent", 0.5),
    ("Alperen Sengun to record over 11.5 points in the Houston Rockets (away)", 11.5),
    ("Resolves Yes if Albania win UEFA Nations League match", None),
])
def test_sentence_line(text: str, line: float | None) -> None:
    assert sentence_line(text) == line


def test_team_sentence_keeps_and_inside_a_name() -> None:
    desc = (
        "Resolves Yes if Brighton and Hove Albion win the Premier League game between "
        "the Brighton and Hove Albion and the Arsenal originally scheduled for 3:00pm ET "
        "on October 10, 2026."
    )
    assert sentence_teams(desc) == ("Brighton and Hove Albion", "Arsenal")


def test_person_sentence_has_no_articles() -> None:
    desc = (
        "Resolves Yes if Jaime Faria wins the ATP Tour match between Hugo Gaston and "
        "Jaime Faria originally scheduled for 8:10pm ET on September 25, 2026."
    )
    assert sentence_teams(desc) == ("Hugo Gaston", "Jaime Faria")


def test_vocab_is_keyed_on_optic_market_ids_per_sport() -> None:
    football = market_types_for_sport(Sport.FOOTBALL)
    assert football["2nd_quarter_point_spread"] is MarketType.SECOND_QUARTER_POINT_SPREAD
    assert football["4th_quarter_moneyline_3-way"] is MarketType.FOURTH_QUARTER_WINNER_3WAY
    assert football["player_longest_reception"] is MarketType.PLAYER_LONGEST_RECEPTION
    # A soccer "moneyline" settles on regulation time, so it is the 3-way.
    assert market_types_for_sport(Sport.SOCCER)["moneyline"] is MarketType.MONEYLINE_3WAY
    assert market_types_for_sport(Sport.TENNIS)["game_spread"] is MarketType.POINT_SPREAD
    assert market_types_for_sport(Sport.BASKETBALL)["player_made_threes"] is MarketType.PLAYER_THREES
    assert football["1st_half_team_total"] is MarketType.FIRST_HALF_TEAM_TOTAL
    basketball = market_types_for_sport(Sport.BASKETBALL)
    assert basketball["player_steals_+_blocks"] is MarketType.PLAYER_STEALS_BLOCKS


_STLBLK_ROW = {
    "ticker": "UDXNBASTLBLK_ATLORL2610211900_D60B4AB763111.5",
    "description": (
        "Resolves Yes if Paolo Banchero records above 1.5 steals AND blocks during the entire "
        "game including overtime of Atlanta Hawks (away) at Orlando Magic (home), originally "
        "scheduled for October 21, 2026 at 7:00pm ET."
    ),
    "status": "open",
    "external_ids": {"optic_odds": {
        "fixture_id": "202610217974F6BE", "market_id": "player_steals_+_blocks",
        "player_id": "D60B4AB76311",
    }},
}


def test_steals_plus_blocks_is_the_players_combined_over() -> None:
    contract = parse_contract(_STLBLK_ROW)
    assert contract is not None
    assert contract.player == "Paolo Banchero"
    assert contract.sides == ("Atlanta Hawks", "Orlando Magic")
    mt = UnderdogConfig(league="nba", market_types=market_types_for_sport(Sport.BASKETBALL)).market_type(contract)
    assert mt is MarketType.PLAYER_STEALS_BLOCKS
    rows = build_rows(
        contract, mt, home="Orlando Magic", away="Atlanta Hawks", start_date="x", league="nba",
        team=None, player_name=contract.player,
    )
    assert {(r.side, r.underdog_side, r.entity, r.line, r.market_type) for r in rows} == {
        ("over", "yes", "Paolo Banchero", 1.5, "player_steals_blocks"),
        ("under", "no", "Paolo Banchero", 1.5, "player_steals_blocks"),
    }


def test_first_half_team_total_is_the_named_teams_over() -> None:
    row = dict(_row("nfl", "UDXNFLTEAMTOTAL_BALATL26OCT112020_ATL10.5"))
    row["ticker"] = "UDXNFLTEAMTOTAL1H_BALATL26OCT112020_ATL10.5"
    row["external_ids"] = {"optic_odds": {**row["external_ids"]["optic_odds"], "market_id": "1st_half_team_total"}}
    contract = parse_contract(row)
    assert contract is not None
    mt = UnderdogConfig(league="nfl", market_types=market_types_for_sport(Sport.FOOTBALL)).market_type(contract)
    assert mt is MarketType.FIRST_HALF_TEAM_TOTAL
    assert needs_team(mt)
    rows = build_rows(
        contract, mt, home="HOM", away="AWY", start_date="x", league="nfl", team="HOM",
    )
    assert {(r.side, r.underdog_side, r.entity, r.line, r.market_type) for r in rows} == {
        ("over", "yes", "HOM", 10.5, "1h_team_total"),
        ("under", "no", "HOM", 10.5, "1h_team_total"),
    }


def test_baseball_inning_markets_without_a_type_and_other_periods_stay_unmapped() -> None:
    baseball = market_types_for_sport(Sport.BASEBALL)
    for market_id in (
        "1st_7_innings_moneyline_3-way", "1st_7_innings_total_runs",
        "1st_3_innings_run_line", "1st_3_innings_total_runs",
    ):
        assert market_id not in baseball
    assert "2nd_half_point_spread" not in market_types_for_sport(Sport.BASKETBALL)
    hockey = market_types_for_sport(Sport.HOCKEY)
    assert "1st_period_moneyline_3-way" not in hockey
    assert "1st_period_puck_line" not in hockey
    combat = market_types_for_sport(Sport.MMA)
    assert not any(market_id.startswith("to_start_round_") for market_id in combat)


def _built(event: str, ticker: str, sport: Sport, *, home="HOM", away="AWY"):
    contract = parse_contract(_row(event, ticker))
    assert contract is not None
    mt = UnderdogConfig(league="X", market_types=market_types_for_sport(sport)).market_type(contract)
    assert mt is not None
    team = {"Atlanta Falcons": home, "Baltimore Ravens": away}.get(contract.yes_team)
    return build_rows(
        contract, mt, home=home, away=away, start_date="2026-10-12T00:20:00Z",
        league=event, team=team,
    )


def _spread_ticker(event: str, market_id: str) -> str:
    return next(
        r["ticker"] for r in _LIVE[event]["rows"]
        if r["external_ids"]["optic_odds"]["market_id"] == market_id
    )


def test_spread_yes_is_the_named_team_with_the_line_negated() -> None:
    ticker = _spread_ticker("nfl", "2nd_quarter_point_spread")
    rows = _built("nfl", ticker, Sport.FOOTBALL)
    yes = next(r for r in rows if r.underdog_side == "yes")
    no = next(r for r in rows if r.underdog_side == "no")
    assert yes.line is not None and yes.line < 0
    assert no.line == -yes.line
    assert {yes.side, no.side} == {"HOM", "AWY"}


def test_integer_line_on_a_line_market_is_dropped() -> None:
    ticker = _spread_ticker("nfl", "2nd_quarter_point_spread")
    row = dict(_row("nfl", ticker))
    row["description"] = row["description"].replace("1.5", "3").replace("2.5", "3")
    contract = parse_contract(row)
    assert contract is not None and contract.line == 3.0
    assert build_rows(
        contract, MarketType.SECOND_QUARTER_POINT_SPREAD,
        home="HOM", away="AWY", start_date="x", league="nfl", team="HOM",
    ) == []


def test_btts_keeps_its_at_least_one_goal_sentence() -> None:
    ticker = _spread_ticker("ucl", "both_teams_to_score")
    row = dict(_row("ucl", ticker))
    row["description"] = row["description"].replace(
        "both teams score in",
        "both participating teams each record at least 1 goals during regulation time of the",
    )
    contract = parse_contract(row)
    assert contract is not None and contract.line == 1.0
    rows = build_rows(
        contract, MarketType.BTTS, home="H", away="A", start_date="x", league="ucl", team=None,
    )
    assert {(r.side, r.underdog_side) for r in rows} == {("yes", "yes"), ("no", "no")}


def test_which_shapes_need_a_named_team() -> None:
    assert needs_team(MarketType.MONEYLINE)
    assert needs_team(MarketType.FIRST_HALF_WINNER_3WAY)
    assert needs_team(MarketType.POINT_SPREAD)
    assert needs_team(MarketType.TEAM_TOTAL)
    assert not needs_team(MarketType.GAME_TOTAL)
    assert not needs_team(MarketType.PLAYER_POINTS)
    assert not needs_team(MarketType.BTTS)
