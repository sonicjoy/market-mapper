"""SX Bet typed records, outcome parsing, row construction, league table.

Catalogue rows are real ``GET /markets/active`` rows captured 2026-10-13
(``tests/fixtures/sxbet/markets_active_2026-10-13.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mappers.exchanges import sxbet, sxbet_leagues
from mappers.exchanges.sxbet import (
    build_rows,
    market_from_row,
    parse_handicap,
    parse_total,
    selection_id,
    strip_segment,
)
from mappers.market_types import MarketType as M
from mappers.shared import TIE_SIDE

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sxbet" / "markets_active_2026-10-13.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _row(o1: str, o2: str | None = None) -> dict:
    return next(r for r in RAW if r["outcomeOneName"] == o1 and (o2 is None or r["outcomeTwoName"] == o2))


def _market(o1: str, o2: str | None = None) -> sxbet.SxMarket:
    m = market_from_row(_row(o1, o2))
    assert m is not None
    return m


SIDES = {"Galatasaray SK": "GS", "Barcelona FC": "BAR",
         "SV Werder Bremen": "SVW", "SC Paderborn 07": "PAD",
         "Tennessee Volunteers": "TENN", "Alabama Crimson Tide": "ALA",
         "Elmer Moller": "EML6", "Lukas Neumayer": "NEU"}


def _rows(m: sxbet.SxMarket, mt: M, home: str = "GS", away: str = "BAR"):
    return build_rows(m, mt, side_of=SIDES.get, home=home, away=away,
                      start_date="2026-10-13T19:00:00Z", league="ucl")


# === The id stamp ===

def test_selection_id_suffix_is_the_makers_outcome() -> None:
    """Prod 2026-10-13: 0xe995d877... outcome one is "Over 5.5" and its |one row is under."""
    assert selection_id("0xABC", 1) == "0xabc|two"
    assert selection_id("0xabc", 2) == "0xabc|one"
    with pytest.raises(ValueError):
        selection_id("0xabc", 0)


def test_market_from_row_reads_the_typed_fields() -> None:
    m = _market("Galatasaray SK +1.5")
    assert m.market_hash == m.market_hash.lower()
    assert (m.event_id, m.league_id, m.sport, m.type, m.line) == ("L20129630", 30, "Soccer", 3, 1.5)
    assert m.start == "2026-10-13T19:00:00Z"
    assert (m.team_one, m.team_two) == ("Galatasaray SK", "Barcelona FC")


@pytest.mark.parametrize("drop", ["marketHash", "sportXeventId", "type", "outcomeOneName", "teamTwoName"])
def test_market_from_row_refuses_a_row_missing_a_key_field(drop: str) -> None:
    raw = dict(_row("Galatasaray SK +1.5"))
    raw.pop(drop)
    assert market_from_row(raw) is None


# === Outcome parsing ===

@pytest.mark.parametrize(("name", "want"), [
    ("Tennessee Volunteers +3.5 (1st half)", "Tennessee Volunteers +3.5"),
    ("Over 2.5 (sets)", "Over 2.5"),
    ("Elmer Moller (1st Period)", "Elmer Moller"),
    ("Over 1.5 (1st 5 Innings)", "Over 1.5"),
    ("Stade Brestois (Brest)", "Stade Brestois (Brest)"),  # a club qualifier is not a period
])
def test_strip_segment(name: str, want: str) -> None:
    assert strip_segment(name) == want


@pytest.mark.parametrize(("name", "want"), [
    ("Galatasaray SK +2.25", ("Galatasaray SK", 2.25)),
    ("Barcelona FC -2", ("Barcelona FC", -2.0)),
    ("Eintracht Frankfurt 0", ("Eintracht Frankfurt", 0.0)),     # a level line is unsigned
    ("FC Schalke 04 0", ("FC Schalke 04", 0.0)),
    ("SC Paderborn 07 +0.75", ("SC Paderborn 07", 0.75)),
    ("Lukas Neumayer -1.5 (sets)", ("Lukas Neumayer", -1.5)),
    ("FC Schalke 04", None),                                     # a club number is never a line
    ("Galatasaray SK", None),
])
def test_parse_handicap(name: str, want) -> None:
    assert parse_handicap(name) == want


def test_parse_total() -> None:
    assert parse_total("Under 27.5 (1st half)") == ("under", 27.5)
    assert parse_total("Over 5.0") == ("over", 5.0)
    assert parse_total("Galatasaray SK +1.5") is None


# === Row construction ===

def test_spread_rows_follow_each_outcomes_own_handicap() -> None:
    rows = _rows(_market("Galatasaray SK +2.25"), M.POINT_SPREAD)
    assert [(r.side, r.line, r.sx_outcome) for r in rows] == [("GS", 2.25, 1), ("BAR", -2.25, 2)]
    assert {r.market_type for r in rows} == {"point_spread"}
    assert {r.sx_event_id for r in rows} == {"L20129630"}
    assert {r.sx_type for r in rows} == {3}


def test_total_rows_and_a_period_total() -> None:
    rows = _rows(_market("Over 27.5 (1st half)"), M.FIRST_HALF_TOTAL, "TENN", "ALA")
    assert [(r.side, r.line, r.sx_outcome, r.market_type) for r in rows] == [
        ("over", 27.5, 1, "1h_total"), ("under", 27.5, 2, "1h_total")]


def test_moneyline_rows_strip_the_period_suffix() -> None:
    rows = _rows(_market("Elmer Moller (1st Period)"), M.FIRST_SET_WINNER, "EML6", "NEU")
    assert [(r.side, r.sx_outcome) for r in rows] == [("EML6", 1), ("NEU", 2)]


def test_three_way_builds_the_affirmative_outcome_only() -> None:
    """ "Not X" is the double chance on the other two -- refused by the SX maker, so never built."""
    team = _rows(_market("Barcelona FC", "Not Barcelona FC"), M.MONEYLINE_3WAY)
    tie = _rows(_market("Tie", "Not tie"), M.MONEYLINE_3WAY)
    assert [(r.side, r.sx_outcome) for r in team] == [("BAR", 1)]
    assert [(r.side, r.sx_outcome) for r in tie] == [(TIE_SIDE, 1)]


def test_a_market_drops_whole_when_a_side_does_not_resolve() -> None:
    m = _market("Galatasaray SK +2.25")
    assert build_rows(m, M.POINT_SPREAD, side_of=lambda n: "GS" if n == "Galatasaray SK" else None,
                      home="GS", away="BAR", start_date="x", league="ucl") == []


def test_a_market_drops_when_both_outcomes_land_on_one_side() -> None:
    m = _market("Galatasaray SK +2.25")
    assert build_rows(m, M.POINT_SPREAD, side_of=lambda _: "GS",
                      home="GS", away="BAR", start_date="x", league="ucl") == []


def test_a_spread_whose_line_disagrees_with_its_outcome_names_drops() -> None:
    raw = dict(_row("Galatasaray SK +2.25"), line=1.0)
    m = market_from_row(raw)
    assert m is not None
    assert _rows(m, M.POINT_SPREAD) == []


def test_a_total_whose_two_lines_differ_drops() -> None:
    raw = dict(_row("Over 3.5", "Under 3.5"), outcomeTwoName="Under 4.5")
    m = market_from_row(raw)
    assert m is not None
    assert _rows(m, M.GAME_TOTAL) == []


def test_a_three_way_with_no_not_outcome_drops() -> None:
    raw = dict(_row("Tie", "Not tie"), outcomeTwoName="Galatasaray SK")
    m = market_from_row(raw)
    assert m is not None
    assert _rows(m, M.MONEYLINE_3WAY) == []


# === League table ===

@pytest.mark.parametrize(("lid", "label", "sport", "want"), [
    (30, "Champions League_UEFA", "Soccer", "ucl"),
    (244, "German Bundesliga", "Soccer", "germany_bundesliga"),
    (1117, "NBA Preseason", "Basketball", "nba"),
    (1063, "DWCS", "Mixed Martial Arts", "ufc"),
    (1516, "Women's World Cup", "Soccer", None),   # not on the tip
    (None, "ATP Challenger - Maia", "Tennis", "atp_challenger"),
    (1535, "ATP - Shanghai", "Tennis", "atp"),
    (1074, "WTA Wuhan", "Tennis", "wta"),
    (9999, "ITF Monastir", "Tennis", None),
])
def test_slug_for(lid, label, sport, want) -> None:
    assert sxbet_leagues.slug_for(lid, label, sport) == want


def test_config_for_takes_the_sports_crosswalk_and_name_rules() -> None:
    soccer = sxbet_leagues.config_for("germany_bundesliga", "soccer")
    tennis = sxbet_leagues.config_for("ATP", "tennis")
    assert soccer is not None and tennis is not None
    assert soccer.club_short_names and not soccer.person_names
    assert tennis.person_names and tennis.slug == "atp"
    assert soccer.market_types[3] is M.POINT_SPREAD
    assert sxbet_leagues.config_for("nonexistent", "soccer") is None
    assert sxbet_leagues.config_for("germany_bundesliga", "cricket") is None


def test_a_crosswalk_entry_wins_over_the_ignore_list() -> None:
    tennis = sxbet_leagues.config_for("atp", "tennis")
    soccer = sxbet_leagues.config_for("ucl", "soccer")
    assert tennis is not None and soccer is not None
    ml = _market("Elmer Moller", "Lukas Neumayer")   # type 52
    soccer_12 = _market("Galatasaray SK", "Barcelona FC")  # type 52, soccer
    assert tennis.market_type(ml) is M.MONEYLINE and not tennis.deliberately_unmapped(ml)
    assert soccer.market_type(soccer_12) is None and soccer.deliberately_unmapped(soccer_12)


def test_with_code_sxbet_sets_and_clears_the_config() -> None:
    from mappers.pipeline import LeagueConfig
    from mappers.seed.tip_factories import with_code_sxbet

    def cfg(league: str, sx=None) -> LeagueConfig:
        return LeagueConfig(league=league, PX=None, OPTIC=None, OUTPUT_ORDER=(),  # type: ignore[arg-type]
                            MarketType=M, sport="soccer", SXBET=sx)  # type: ignore[arg-type]

    base = cfg("germany_bundesliga")
    wired = with_code_sxbet(base, "germany_bundesliga")
    assert wired.SXBET is not None and wired.SXBET.slug == "germany_bundesliga"
    assert with_code_sxbet(wired, "germany_bundesliga") is wired      # unchanged config: same object
    other = cfg("japan_j2_league", wired.SXBET)
    assert with_code_sxbet(other, "japan_j2_league").SXBET is None     # a league SX does not list
