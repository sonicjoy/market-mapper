"""Underdog fight props, overtime, NHL period/team lines and MLB inning/pitcher props.

Rows are verbatim UDX catalogue rows of 2026-10-10. UDX's Optic market id names
the market a contract is priced from, so these also need the sentence to state
the contract.
"""

from __future__ import annotations

from mappers.exchanges.underdog import UnderdogConfig, build_rows, parse_contract
from mappers.exchanges.underdog_pass import is_blocked
from mappers.fight_props import METHOD_DECISION, METHOD_KO_TKO_DQ
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_UFC = "the Ultimate Fighting Championship fight between Ismael Bonfim and Francisco Prado"
_UFC_AT = "originally scheduled for 6:40pm ET on October 10, 2026"
_MLB = (
    "the Major League Baseball game between the Chicago White Sox and the Cleveland Guardians "
    "originally scheduled for 5:00pm ET on October 10, 2026"
)


def _row(ticker: str, description: str, market_id: str, **ids: str) -> dict:
    return {
        "ticker": ticker, "description": description, "status": "open",
        "external_ids": {"optic_odds": {"fixture_id": "FIX", "market_id": market_id, **ids}},
    }


def _built(row: dict, sport: Sport, *, home: str, away: str, team: str | None = None):
    contract = parse_contract(row)
    assert contract is not None
    mt = UnderdogConfig(league="X", market_types=market_types_for_sport(sport)).market_type(contract)
    if mt is None:
        return None
    built = build_rows(
        contract, mt, home=home, away=away, start_date="2026-10-10T22:40:00Z",
        league="x", team=team,
    )
    return [(r.market_type, r.entity, r.line, r.side, r.grouping_key, r.underdog_side) for r in built]


def _ufc(ticker: str, tail: str, market_id: str, *, who: str = "Francisco Prado", team=None, **ids):
    description = f"Resolves Yes if {who} wins {_UFC} {_UFC_AT} {tail}"
    return _built(_row(ticker, description, market_id, **ids), Sport.MMA,
                  home="Francisco Prado", away="Ismael Bonfim", team=team)


def test_fighter_method_of_victory_keys_the_method_like_optic() -> None:
    dec = _ufc("UDXUFCMOV_BONPRA26OCT101840_FPRADODEC", "by decision.", "method_of_victory",
               team="Francisco Prado", player_id="154B5027F517")
    assert dec == [("method_of_victory", "Francisco Prado", None, "yes", METHOD_DECISION, "yes")]
    ko = _ufc("UDXUFCMOV_BONPRA26OCT101840_FPRADOKOTKO", "by KO, TKO or disqualification.",
              "method_of_victory", team="Francisco Prado", player_id="154B5027F517")
    assert ko == [("method_of_victory", "Francisco Prado", None, "yes", METHOD_KO_TKO_DQ, "yes")]


def test_either_fighter_method_is_the_fights_method_of_finish() -> None:
    built = _ufc("UDXUFCMOVFINISH_BONPRA26OCT101840_DEC", "by decision.", "method_of_victory",
                 who="either fighter")
    assert built == [("method_of_finish", None, None, "yes", METHOD_DECISION, "yes")]


def test_round_betting_keys_fighter_and_round_like_optic() -> None:
    built = _ufc("UDXUFCFIGHTWINROUND_BONPRA26OCT101840_FPRADOR1", "during Round 1.",
                 "round_betting", player_id="154B5027F517")
    assert built == [("round_betting", None, None, "yes", "francisco_prado_round_1", "yes")]


def test_go_the_distance_needs_the_all_rounds_sentence() -> None:
    description = f"Resolves Yes if {_UFC} {_UFC_AT} concludes during all scheduled rounds."
    built = _built(_row("UDXUFCDISTANCE_BONPRA26OCT101840_DIST", description, "go_the_distance"),
                   Sport.MMA, home="Francisco Prado", away="Ismael Bonfim")
    assert built == [
        ("fight_goes_distance", None, None, "yes", None, "yes"),
        ("fight_goes_distance", None, None, "no", None, "no"),
    ]
    other = description.replace("all scheduled rounds", "Round 3")
    assert _built(_row("T", other, "go_the_distance"), Sport.MMA,
                  home="Francisco Prado", away="Ismael Bonfim") == []


def test_ufc_round_counts_stay_unmapped() -> None:
    """"concludes during Round 2" carries to_start_round_2: not the same contract."""
    for ticker, tail, market_id in (
        ("UDXUFCEXACTTOTAL_BONPRA26OCT101840_R1", "concludes during Round 1.", "to_start_round_2"),
        ("UDXUFCTOTAL_BONPRA26OCT101840_1.5", "concludes during Rounds 2 through 3.", "to_start_round_2"),
    ):
        description = f"Resolves Yes if {_UFC} {_UFC_AT} {tail}"
        assert _built(_row(ticker, description, market_id), Sport.MMA,
                      home="Francisco Prado", away="Ismael Bonfim") is None


def test_nfl_and_nhl_overtime_map_and_college_overtime_is_blocked() -> None:
    nfl = _row(
        "UDXNFLOVERTIME_BALATL26OCT112020_OT",
        "Resolves Yes if any participating team records at least 1 kickoffs during overtime only "
        "of the National Football League game between the Baltimore Ravens and the Atlanta "
        "Falcons originally scheduled for 8:20pm ET on October 11, 2026.",
        "will_there_be_overtime",
    )
    assert _built(nfl, Sport.FOOTBALL, home="ATL", away="BAL") == [
        ("will_there_be_overtime", None, None, "yes", None, "yes"),
        ("will_there_be_overtime", None, None, "no", None, "no"),
    ]
    nhl = _row(
        "UDXNHLOVERTIME_ANACGY26OCT102200_OT",
        "Resolves Yes if the game between the Anaheim Ducks and Calgary Flames, originally "
        "scheduled for October 10, 2026 at 10:00 PM ET, actually enters an overtime period.",
        "will_there_be_overtime",
    )
    assert not is_blocked(nhl)
    college = {**nfl, "ticker": "UDXNCAAMFBOVERTIME_AFANIU26OCT101930_OT"}
    assert is_blocked(college)


def test_nhl_team_goals_and_period_totals_map() -> None:
    team = _row(
        "UDXNHLTEAMGOALS_ANACGY26OCT102200_ANA0.5",
        "Will NHL Anaheim Ducks record above 0.5 goals during the entire game including "
        "regulation, all overtime periods actually played, and the official shootout result of "
        "Anaheim Ducks (away) at Calgary Flames (home), originally scheduled for October 10, 2026 "
        "at 10:00pm ET?",
        "team_total", team_id="013ABB6C1301",
    )
    assert _built(team, Sport.HOCKEY, home="CGY", away="ANA", team="ANA") == [
        ("team_total", "ANA", 0.5, "over", None, "yes"),
        ("team_total", "ANA", 0.5, "under", None, "no"),
    ]
    period = _row(
        "UDXNHLTOTAL1P_ANACGY26OCT102200_0.5",
        "Will NHL Anaheim Ducks (away) at Calgary Flames (home), originally scheduled for October "
        "10, 2026 at 10:00pm ET have above 0.5 goals during the first regulation period?",
        "1st_period_total_goals",
    )
    assert _built(period, Sport.HOCKEY, home="CGY", away="ANA") == [
        ("p1_total", None, 0.5, "over", None, "yes"),
        ("p1_total", None, 0.5, "under", None, "no"),
    ]


def test_mlb_first_five_and_first_three_need_the_stated_inning_count() -> None:
    f5 = _row(
        "UDXMLBGAMEWIN5_CWSCLE26OCT101700_CLE",
        f"Resolves Yes if the Cleveland Guardians score more runs than their opponent during the "
        f"first 5 innings of {_MLB}.",
        "1st_half_moneyline_3-way", team_id="D4F7181B2181",
    )
    assert _built(f5, Sport.BASEBALL, home="CLE", away="CWS", team="CLE") == [
        ("f5_moneyline_3way", None, None, "CLE", None, "yes"),
    ]
    f3 = {**f5, "description": f5["description"].replace("first 5 innings", "first 3 innings")}
    f3["external_ids"] = {"optic_odds": {"fixture_id": "FIX", "market_id": "1st_3_innings_moneyline_3-way"}}
    assert _built(f3, Sport.BASEBALL, home="CLE", away="CWS", team="CLE") == [
        ("f3_moneyline_3way", None, None, "CLE", None, "yes"),
    ]
    mismatch = {**f5, "description": f3["description"]}
    assert _built(mismatch, Sport.BASEBALL, home="CLE", away="CWS", team="CLE") == []
    total = _row(
        "UDXMLBTOTAL5_CWSCLE26OCT101700_0.5",
        f"Resolves Yes if there are above 0.5 runs during the first 5 innings in {_MLB}.",
        "1st_half_total_runs",
    )
    assert _built(total, Sport.BASEBALL, home="CLE", away="CWS") == [
        ("f5_total", None, 0.5, "over", None, "yes"),
        ("f5_total", None, 0.5, "under", None, "no"),
    ]


def test_mlb_pitcher_and_runner_props_map() -> None:
    sb = _row(
        "UDXMLBSB_CWSCLE26OCT101700ANGELMARTINE_0.5",
        f"Resolves Yes if Angel Martinez records above 0.5 stolen bases during the full duration "
        f"of {_MLB}.",
        "player_stolen_bases", player_id="F256F6F35BD1",
    )
    contract = parse_contract(sb)
    assert contract is not None
    mt = UnderdogConfig(league="X", market_types=market_types_for_sport(Sport.BASEBALL)).market_type(contract)
    assert mt is not None and mt.value == "player_stolen_bases"
    for market_id, value in (
        ("player_outs", "player_outs"),
        ("player_hits_allowed", "player_hits_allowed"),
        ("player_earned_runs", "player_earned_runs"),
        ("player_walks", "player_walks_allowed"),
    ):
        assert market_types_for_sport(Sport.BASEBALL)[market_id].value == value


def test_futures_and_novelty_series_are_blocked() -> None:
    for series in ("UDXMLBCBA", "UDXMLBSTART", "UDXNBAEXPTEAM", "UDXNFLTEAMSALE"):
        assert is_blocked({"ticker": f"{series}_26DEC01", "description": "Will ..."})
