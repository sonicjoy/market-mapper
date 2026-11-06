"""Underdog catalogue pass: typed ids and sentences, never the ticker."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from mappers.exchanges.underdog import UnderdogConfig, parse_contract
from mappers.exchanges.underdog_pass import _match_fixture, is_blocked, run_pass
from mappers.shared import TIE_SIDE
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_UDX_START = datetime(2026, 9, 25, 19, 10, tzinfo=ZoneInfo("America/New_York"))
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_live_2026-10-09.json"
_LIVE = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _entry(away: str, home: str, start_date: str) -> SimpleNamespace:
    return SimpleNamespace(fixture=SimpleNamespace(
        away=away, home=home, away_name=away, home_name=home, start_date=start_date,
    ))


def test_doubleheader_joins_the_nearer_game() -> None:
    game1 = _entry("Baltimore Orioles", "New York Yankees", "2026-09-25T20:10:00Z")
    game2 = _entry("Baltimore Orioles", "New York Yankees", "2026-09-25T23:30:00Z")
    sides = ("Baltimore Orioles", "New York Yankees")
    assert _match_fixture(sides, _UDX_START, [game1, game2], player=False) is game2


def test_equidistant_fixtures_are_ambiguous() -> None:
    early = _entry("Baltimore Orioles", "New York Yankees", "2026-09-25T22:10:00Z")
    late = _entry("Baltimore Orioles", "New York Yankees", "2026-09-26T00:10:00Z")
    sides = ("Baltimore Orioles", "New York Yankees")
    assert _match_fixture(sides, _UDX_START, [early, late], player=False) is None


def test_three_hour_drift_joins_people_not_teams() -> None:
    tennis = _entry("Hugo Gaston", "Jaime Faria", "2026-09-26T02:10:00Z")
    assert _match_fixture(("Hugo Gaston", "Jaime Faria"), _UDX_START, [tennis], player=True) is tennis
    team = _entry("Chicago Cubs", "Boston Red Sox", "2026-09-26T02:10:00Z")
    assert _match_fixture(("Chicago Cubs", "Boston Red Sox"), _UDX_START, [team], player=False) is None


def test_placeholder_tennis_start_takes_the_only_pair_within_three_days() -> None:
    """A tennis start listed a day before Optic's (adding-underdog.md item 11)."""
    sides = ("Hugo Gaston", "Jaime Faria")
    next_day = _entry("Hugo Gaston", "Jaime Faria", "2026-09-26T23:30:00Z")
    assert _match_fixture(sides, _UDX_START, [next_day], player=True) is next_day
    rematch = _entry("Hugo Gaston", "Jaime Faria", "2026-09-27T23:30:00Z")
    assert _match_fixture(sides, _UDX_START, [next_day, rematch], player=True) is None
    team = _entry("Chicago Cubs", "Boston Red Sox", "2026-09-26T23:30:00Z")
    assert _match_fixture(("Chicago Cubs", "Boston Red Sox"), _UDX_START, [team], player=False) is None


def _live_entry(event: str) -> SimpleNamespace:
    """Optic fixture for a captured event, built from its first sentence that names a kickoff."""
    for row in _LIVE[event]["rows"]:
        contract = parse_contract(row)
        if contract is not None and contract.start is not None:
            away, home = contract.sides
            return SimpleNamespace(fixture=SimpleNamespace(
                fixture_id=_LIVE[event]["fixture_id"],
                away="AWY", home="HOM", away_name=away, home_name=home,
                start_date=contract.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                team_map={}, odds=[],
            ))
    raise AssertionError(event)


def _run(event: str, sport: Sport, *, league: str, catalogue=None, entry=None):
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league=league.upper(), market_types=market_types_for_sport(sport))
    tally = run_pass(
        catalogue if catalogue is not None else _LIVE[event]["rows"],
        cfg, [entry or _live_entry(event)], league=league,
        attach=attach, row_index={}, all_rows=[],
    )
    return tally, stamped


def _market_ids(event: str) -> list[str]:
    return [r["external_ids"]["optic_odds"]["market_id"] for r in _LIVE[event]["rows"]]


def test_nfl_event_stamps_every_mapped_market_and_nothing_else() -> None:
    tally, stamped = _run("nfl", Sport.FOOTBALL, league="nfl")
    table = market_types_for_sport(Sport.FOOTBALL)
    ids = _market_ids("nfl")
    assert tally["unparsed"] == 0
    assert tally["other_league"] == 0
    assert tally["unmapped"] == sum(i not in table for i in ids)
    assert tally["stamped"] == len(stamped) > 0
    kinds = {row.market_type for row in stamped}
    assert {"2q_point_spread", "4q_winner_3way", "player_longest_reception"} <= kinds


def test_period_comes_from_the_optic_market_id_not_the_ticker() -> None:
    """Swap every ticker for an opaque one: the stamps do not change."""
    rows = [dict(r, ticker=f"opaque-{i}") for i, r in enumerate(_LIVE["nfl"]["rows"])]
    _, named = _run("nfl", Sport.FOOTBALL, league="nfl")
    _, opaque = _run("nfl", Sport.FOOTBALL, league="nfl", catalogue=rows)
    shape = lambda rs: sorted(  # noqa: E731
        (r.market_type, r.side, r.entity or "", r.line if r.line is not None else 0.0, r.underdog_side)
        for r in rs
    )
    assert shape(named) == shape(opaque)
    assert all(r.underdog_ticker.startswith("opaque-") for r in opaque)


def test_ncaaf_team_total_side_comes_from_the_sentence() -> None:
    tally, stamped = _run("ncaaf", Sport.FOOTBALL, league="ncaaf")
    totals = [r for r in stamped if r.market_type == "team_total"]
    assert totals
    # Air Force is the venue's away side; the entity is the team the sentence names.
    assert {r.entity for r in totals} <= {"AWY", "HOM"}
    assert {(r.side, r.underdog_side) for r in totals} == {("over", "yes"), ("under", "no")}
    assert tally["no_side"] == 0


def test_nba_props_without_a_kickoff_resolve_by_optic_fixture_id() -> None:
    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=_LIVE["nba"]["fixture_id"], away="HOU", home="DAL",
        away_name="Houston Rockets", home_name="Dallas Mavericks",
        start_date="2026-10-09T12:00:00Z", team_map={}, odds=[],
    ))
    tally, stamped = _run("nba", Sport.BASKETBALL, league="nba", entry=entry)
    assert tally["unparsed"] == 0
    assert tally["no_fixture"] == 0
    props = [r for r in stamped if r.market_type == "player_points"]
    assert props
    assert {r.entity for r in props} == {"alperen_sengun"}
    assert {(r.side, r.underdog_side) for r in props} == {("over", "yes"), ("under", "no")}


def test_a_kickoff_less_sentence_that_names_other_teams_is_not_joined() -> None:
    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=_LIVE["nba"]["fixture_id"], away="BOS", home="NYK",
        away_name="Boston Celtics", home_name="New York Knicks",
        start_date="2026-10-09T12:00:00Z", team_map={}, odds=[],
    ))
    tally, stamped = _run("nba", Sport.BASKETBALL, league="nba", entry=entry)
    assert stamped == []
    assert tally["no_fixture"] > 0


def _stale_kickoff_catalogue(event: str, expires_at: str) -> list[dict]:
    """The captured rows with the sentence kickoff moved to UDX's 12:00am ET placeholder."""
    rows = []
    for row in _LIVE[event]["rows"]:
        description = re.sub(
            r"scheduled for \d{1,2}:\d{2}[ap]m ET on", "scheduled for 12:00am ET on",
            row["description"],
        )
        rows.append({**row, "description": description, "expires_at": expires_at})
    return rows


def _expiry_three_days_after(entry: SimpleNamespace, *, shift: timedelta = timedelta()) -> str:
    kickoff = datetime.fromisoformat(entry.fixture.start_date.replace("Z", "+00:00"))
    return (kickoff + timedelta(days=3) + shift).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def test_stale_sentence_kickoff_joins_the_id_named_fixture_at_expiry_kickoff() -> None:
    """NCAAF TAM @ MIZ 2026-10-10: sentence 12:00am ET, expires_at kickoff + 3 days."""
    entry = _live_entry("ncaaf")
    catalogue = _stale_kickoff_catalogue("ncaaf", _expiry_three_days_after(entry))
    tally, stamped = _run("ncaaf", Sport.FOOTBALL, league="ncaaf", catalogue=catalogue, entry=entry)
    assert tally["no_fixture"] == 0
    assert stamped


def test_stale_sentence_kickoff_with_expiry_off_the_fixture_still_joins_by_id() -> None:
    """With no same-pair sibling, the typed id is the join; time does not veto it."""
    entry = _live_entry("ncaaf")
    catalogue = _stale_kickoff_catalogue(
        "ncaaf", _expiry_three_days_after(entry, shift=timedelta(hours=9)),
    )
    tally, stamped = _run("ncaaf", Sport.FOOTBALL, league="ncaaf", catalogue=catalogue, entry=entry)
    assert tally["no_fixture"] == 0
    assert stamped


def _run_with_sibling(entry: SimpleNamespace, sibling: SimpleNamespace, catalogue: list[dict]):
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league="NCAAF", market_types=market_types_for_sport(Sport.FOOTBALL))
    tally = run_pass(
        catalogue, cfg, [entry, sibling], league="ncaaf",
        attach=attach, row_index={}, all_rows=[],
    )
    return tally, stamped


def _sibling_of(entry: SimpleNamespace, hours: int) -> SimpleNamespace:
    kickoff = datetime.fromisoformat(entry.fixture.start_date.replace("Z", "+00:00"))
    return SimpleNamespace(fixture=SimpleNamespace(
        **{**vars(entry.fixture), "fixture_id": "SIBLING",
           "start_date": (kickoff + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    ))


def test_doubleheader_sibling_needs_kickoff_to_agree_with_the_id() -> None:
    """Item 13: UDX swapped ids on a doubleheader, so a same-pair sibling makes kickoff decide."""
    entry = _live_entry("ncaaf")
    sibling = _sibling_of(entry, 6)
    agrees = _stale_kickoff_catalogue("ncaaf", _expiry_three_days_after(entry))
    _, stamped = _run_with_sibling(entry, sibling, agrees)
    assert stamped
    swapped = _stale_kickoff_catalogue("ncaaf", _expiry_three_days_after(entry, shift=timedelta(hours=6)))
    tally, stamped = _run_with_sibling(entry, sibling, swapped)
    assert stamped == []
    assert tally["optic_fixture"] > 0


def test_stale_sentence_kickoff_never_joins_a_fixture_the_names_do_not_fit() -> None:
    entry = _live_entry("ncaaf")
    entry.fixture.away_name, entry.fixture.home_name = "Some College", "Other College"
    catalogue = _stale_kickoff_catalogue("ncaaf", _expiry_three_days_after(entry))
    tally, stamped = _run("ncaaf", Sport.FOOTBALL, league="ncaaf", catalogue=catalogue, entry=entry)
    assert stamped == []


_SWPP = {
    "ticker": "UDXNFLSWPP_ARILAR26OCT181605_ARI10",
    "description": (
        "Resolves Yes if the Arizona Cardinals wins the National Football League game between the "
        "Arizona Cardinals and the Los Angeles Rams originally scheduled for 4:05pm ET on October 18, "
        "2026 without its win probability falling below 10% over any 1 minute window."
    ),
    "status": "open",
    "expires_at": "2026-10-21T14:00:00.000000Z",
    "external_ids": {"optic_odds": {
        "fixture_id": "2026101843BFE7F5", "market_id": "moneyline", "team_id": "AF456B375E7E",
    }},
}


def test_swpp_is_blocked_though_udx_tags_it_moneyline() -> None:
    """2026-10-10: 420 UDXNFLSWPP symbols were stamped as plain moneyline."""
    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id="2026101843BFE7F5", away="ARI", home="LAR",
        away_name="Arizona Cardinals", home_name="Los Angeles Rams",
        start_date="2026-10-18T20:05:00Z", team_map={"AF456B375E7E": "ARI"}, odds=[],
    ))
    tally, stamped = _run("nfl", Sport.FOOTBALL, league="nfl", catalogue=[_SWPP], entry=entry)
    assert stamped == []
    assert tally["blocked"] == 1


def test_win_probability_clause_is_blocked_in_any_series() -> None:
    assert is_blocked({**_SWPP, "ticker": "UDXNBASWPP_PORSAC26OCT132200_POR10"})
    assert is_blocked({**_SWPP, "ticker": "UDXNFLSWPP-ANY"})
    plain = {**_SWPP, "ticker": "UDXNFLGAMEWIN_ARILAR26OCT181605_ARI",
             "description": _SWPP["description"].split(" without")[0] + "."}
    assert not is_blocked(plain)


def test_futures_and_novelty_series_are_blocked() -> None:
    for series in ("UDXMLBCBA", "UDXMLBSTART", "UDXNBAEXPTEAM", "UDXNFLTEAMSALE"):
        assert is_blocked({"ticker": f"{series}_26DEC01", "description": "Will ..."})


def test_contract_for_another_leagues_fixture_is_not_this_leagues() -> None:
    entry = _live_entry("nfl")
    entry.fixture.fixture_id = "SOME-OTHER-FIXTURE"
    tally, stamped = _run("nfl", Sport.FOOTBALL, league="nfl", entry=entry)
    assert stamped == []
    assert tally["other_league"] == len(_LIVE["nfl"]["rows"])


def test_soccer_event_maps_the_draw_and_both_sides_of_btts() -> None:
    tally, stamped = _run("ucl", Sport.SOCCER, league="ucl")
    assert tally["unparsed"] == 0
    results = {(r.side, r.underdog_side) for r in stamped if r.market_type == "moneyline_3way"}
    assert (TIE_SIDE, "yes") in results
    assert ("AWY", "yes") in results and ("HOM", "yes") in results
    btts = {(r.side, r.underdog_side) for r in stamped if r.market_type == "btts"}
    assert btts == {("yes", "yes"), ("no", "no")}
    spreads = [r for r in stamped if r.market_type == "point_spread"]
    assert spreads and {r.underdog_side for r in spreads} == {"yes", "no"}


def test_nhl_game_lines_map_and_period_markets_do_not() -> None:
    tally, stamped = _run("nhl", Sport.HOCKEY, league="nhl")
    ids = _market_ids("nhl")
    table = market_types_for_sport(Sport.HOCKEY)
    assert tally["unmapped"] == sum(i not in table for i in ids)
    assert {r.market_type for r in stamped} <= {
        "moneyline", "point_spread", "game_total", "team_total",
        "p1_total", "p2_total", "p3_total", "will_there_be_overtime",
    }
    assert not {r.market_type for r in stamped} & {"p1_winner_3way", "p1_point_spread"}


def test_person_moneyline_stamps_the_named_player() -> None:
    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=_LIVE["wta"]["fixture_id"], away="Nikola Bartunkova", home="Mirra Andreeva",
        away_name="Nikola Bartunkova", home_name="Mirra Andreeva",
        start_date="2026-10-10T06:00:00Z", team_map={}, odds=[],
    ))
    tally, stamped = _run("wta", Sport.TENNIS, league="wta", entry=entry)
    assert tally["unparsed"] == 0
    won = {(r.side, r.underdog_side) for r in stamped if r.market_type == "moneyline"}
    assert ("Mirra Andreeva", "yes") in won and ("Nikola Bartunkova", "no") in won


def test_closed_rows_and_unmapped_market_ids_are_tallied_not_stamped() -> None:
    rows = [dict(r) for r in _LIVE["nfl"]["rows"][:2]]
    rows[0]["status"] = "closed"
    rows[1]["external_ids"] = {
        "optic_odds": {**rows[1]["external_ids"]["optic_odds"], "market_id": "1st_3_innings_run_line"},
    }
    tally, stamped = _run("nfl", Sport.FOOTBALL, league="nfl", catalogue=rows)
    assert stamped == []
    assert tally["closed"] == 1
    assert tally["unmapped"] == 1


_DIMAYOR = json.loads(
    (_FIXTURE.parent / "underdog_dimayor_2026-10-14.json").read_text(encoding="utf-8"),
)["colombia_primera_a"]
_JUN_WIN = "UDXDIMAYORGAMEWIN_PERJUN26OCT141730_JUN"


def test_colombia_primera_a_event_stamps_every_live_contract() -> None:
    """UDXDIMAYOR*, live 2026-10-14: Optic lists Junior home, Pereira away."""
    entry = SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=_DIMAYOR["fixture_id"], away="PER", home="JUN",
        away_name="Deportivo Pereira FC", home_name="CD Popular Junior FC SA",
        start_date="2026-10-14T21:30:00Z", team_map={}, odds=[],
    ))
    tally, stamped = _run(
        "colombia_primera_a", Sport.SOCCER, league="colombia_primera_a",
        catalogue=_DIMAYOR["rows"], entry=entry,
    )
    assert tally["stamped"] == len(stamped) == 33
    assert {r.underdog_ticker for r in stamped} == {r["ticker"] for r in _DIMAYOR["rows"]}
    won = {(r.underdog_ticker, r.side, r.underdog_side) for r in stamped if r.market_type == "moneyline_3way"}
    assert (_JUN_WIN, "JUN", "yes") in won
    assert {(side, udx) for _, side, udx in won} == {("JUN", "yes"), ("PER", "yes"), (TIE_SIDE, "yes")}
    by_side = {
        r.underdog_side: (r.side, r.line) for r in stamped
        if r.underdog_ticker == "UDXDIMAYORSPREAD_PERJUN26OCT141730_JUN1.5"
    }
    assert by_side == {"yes": ("JUN", -1.5), "no": ("PER", 1.5)}


def test_the_sibling_scan_runs_once_per_event_not_per_contract(monkeypatch) -> None:
    """Every contract of an event asks the same sibling question (NCAAF: 6,500 rows, 79 s -> 33 s)."""
    from mappers.exchanges import underdog_pass

    calls: list = []
    real = underdog_pass._siblings

    def counted(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(underdog_pass, "_siblings", counted)
    _, stamped = _run("ncaaf", Sport.FOOTBALL, league="ncaaf")
    assert len(stamped) > len(calls) == len(set(calls))
