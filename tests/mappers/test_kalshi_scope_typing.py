"""Kalshi markets typed from Kalshi's own fields, never the ticker or tip rules.

Tickers below are opaque ids; several are deliberately nonsense to prove
nothing reads them.
"""

import json

import pytest

from mappers.exchanges.kalshi import (
    AWAY,
    HOME,
    CorrectScoreMarket,
    KalshiConfig,
    Market,
    OverUnderMarket,
    RoundStartMarket,
    SpreadMarket,
    SubtitleMismatchError,
    ThreeWayMarket,
    TotalMarket,
    build_rows,
    parse_market,
    parse_market_line,
    parse_typed_market,
    scoped_market_type,
)
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import market_type_for_scope, scope_line, sport_for_tags

SOCCER = KalshiConfig(sport=Sport.SOCCER)
TENNIS = KalshiConfig(sport=Sport.TENNIS)
MMA = KalshiConfig(sport=Sport.MMA)
BASEBALL = KalshiConfig(sport=Sport.BASEBALL)
FOOTBALL = KalshiConfig(sport=Sport.FOOTBALL)
HOCKEY = KalshiConfig(sport=Sport.HOCKEY)

MS = {"id": "ms", "home_id": "h-id", "away_id": "a-id", "tie_id": "t-id"}


def _market(scope: str | None, *, series: str | None = None, ticker: str = "T-1",
            **kw) -> Market:
    kw.setdefault("milestone", MS)
    return Market(event_ticker="E", ticker=ticker, title=kw.pop("title", ""),
                  competition_scope=scope,
                  series_scope=series if series is not None else scope, **kw)


# --- scope vocabulary ---

def test_scope_means_the_same_in_every_league_of_a_sport():
    assert market_type_for_scope(Sport.TENNIS, "Total Games") == MarketType.MATCH_TOTAL_GAMES
    assert market_type_for_scope(Sport.TENNIS, "Game") == MarketType.MONEYLINE
    assert market_type_for_scope(Sport.SOCCER, "Game") == MarketType.MONEYLINE_3WAY
    assert market_type_for_scope(Sport.FOOTBALL, "Passing Yards") == MarketType.PLAYER_PASSING_YARDS
    assert market_type_for_scope(Sport.FOOTBALL, "Passing") is None
    assert market_type_for_scope(Sport.SOCCER, "Future") is None


def test_sport_comes_from_one_series_tag():
    assert sport_for_tags(["Football"]) == Sport.FOOTBALL
    assert sport_for_tags(["UFC"]) == Sport.MMA
    assert sport_for_tags(["Golf"]) is None
    assert sport_for_tags(["Soccer", "Basketball"]) is None
    assert sport_for_tags(None) is None


def test_series_scope_wins_where_kalshi_files_advance_events_under_game():
    m = _market("Game", series="To Advance")
    assert scoped_market_type(m, SOCCER) == MarketType.TO_ADVANCE


def test_an_unmapped_event_scope_is_not_rescued_by_its_series():
    assert scoped_market_type(_market("Future", series="Game"), SOCCER) is None


def test_event_scope_types_markets_of_a_broader_series():
    m = _market("Passing Yards", series="Passing")
    assert scoped_market_type(m, FOOTBALL) == MarketType.PLAYER_PASSING_YARDS


def test_passing_yards_range_series_types_as_passing_yards():
    # KXNFLPASSYDSPRECISE: series scope "Stat Range", event scope "Passing Yards Range"
    m = _market("Passing Yards Range", series="Stat Range")
    assert scoped_market_type(m, FOOTBALL) == MarketType.PLAYER_PASSING_YARDS


def test_no_scope_maps_nothing():
    assert scoped_market_type(_market(None, series=""), SOCCER) is None


def test_later_quarter_lines_and_half_team_totals_map_in_any_sport():
    for sport in (Sport.FOOTBALL, Sport.BASKETBALL):
        assert market_type_for_scope(sport, "2nd Quarter Spread") == MarketType.SECOND_QUARTER_POINT_SPREAD
        assert market_type_for_scope(sport, "3rd Quarter Total") == MarketType.THIRD_QUARTER_TOTAL
        assert market_type_for_scope(sport, "1st Half Team Total") == MarketType.FIRST_HALF_TEAM_TOTAL


def test_hockey_period_lines_props_and_team_receiving():
    assert market_type_for_scope(Sport.HOCKEY, "1st Period Spread") == MarketType.FIRST_PERIOD_POINT_SPREAD
    assert market_type_for_scope(Sport.HOCKEY, "3rd Period Total") == MarketType.THIRD_PERIOD_TOTAL
    assert market_type_for_scope(Sport.HOCKEY, "2nd Period Winner") == MarketType.SECOND_PERIOD_WINNER_3WAY
    assert market_type_for_scope(Sport.HOCKEY, "Goalscorer") == MarketType.PLAYER_GOALS
    assert market_type_for_scope(Sport.HOCKEY, "1st Goalscorer") == MarketType.FIRST_GOAL_SCORER
    assert market_type_for_scope(Sport.HOCKEY, "Points") == MarketType.PLAYER_POINTS
    assert market_type_for_scope(Sport.HOCKEY, "Assists") == MarketType.PLAYER_ASSISTS
    assert market_type_for_scope(Sport.FOOTBALL, "Team Receiving Yards") == MarketType.TEAM_TOTAL_RECEIVING_YARDS


def test_baseball_innings_and_the_ninth_left_out():
    assert market_type_for_scope(Sport.BASEBALL, "First 7 Innings Winner") == MarketType.FIRST_SEVEN_MONEYLINE_3WAY
    assert market_type_for_scope(Sport.BASEBALL, "8th Inning Total") == MarketType.INNING_8_TOTAL
    assert market_type_for_scope(Sport.BASEBALL, "9th Inning Total") is None
    assert market_type_for_scope(Sport.BASEBALL, "9th Inning Winner") is None


def test_race_to_points_line_is_the_scope_target():
    assert market_type_for_scope(Sport.FOOTBALL, "Race to 21 Points") == MarketType.RACE_TO_POINTS
    assert scope_line("Race to 21 Points") == 21.0
    assert scope_line("Point Total") is None


# --- parsing ---

def test_total_line_and_yes_side_come_from_the_strike():
    m = _market("Total Games", strike_type="greater", floor_strike=21.5)
    p = parse_typed_market(m, TENNIS)
    assert isinstance(p, TotalMarket)
    assert (p.market_type, p.line) == (MarketType.MATCH_TOTAL_GAMES, 21.5)
    rows = build_rows(start_date="2026-10-01", home="GAU", away="SWI",
                      markets=[m], cfg=TENNIS, league="wta")
    assert [(r.market_type, r.line, r.side, r.kalshi_side, r.kalshi_scope) for r in rows] == [
        ("match_total_games", 21.5, "over", "yes", "Total Games"),
        ("match_total_games", 21.5, "under", "no", "Total Games"),
    ]


def test_n_plus_count_strike_is_over_n_minus_half():
    m = _market("YRFI/NRFI", strike_type="greater_or_equal", floor_strike=1)
    p = parse_typed_market(m, BASEBALL)
    assert isinstance(p, TotalMarket) and p.line == 0.5


def test_a_line_market_without_a_typed_strike_is_skipped(capsys):
    m = _market("Point Total")
    with pytest.raises(ValueError, match="no typed line"):
        parse_typed_market(m, SOCCER)
    assert build_rows(start_date="2026-10-03", home="ARS", away="CHE",
                      markets=[m], cfg=SOCCER, league="epl") == []
    assert "skipping" in capsys.readouterr().err


def test_subtitle_stating_another_line_is_refused():
    m = _market("Point Total", strike_type="greater", floor_strike=2.5,
                yes_sub_title="Over 3.5 goals scored")
    with pytest.raises(ValueError, match="yes_sub_title"):
        parse_typed_market(m, SOCCER)


def test_player_line_comes_from_the_strike_not_the_ticker():
    m = _market("Points", ticker="NONSENSE-99", title="Jack Eichel: 2+ points",
                strike_type="greater", floor_strike=1.5,
                custom_strike={"hockey_player": "p", "hockey_team": "h-id"})
    p = parse_typed_market(m, HOCKEY)
    assert isinstance(p, OverUnderMarket)
    assert (p.market_type, p.player_name, p.line) == (MarketType.PLAYER_POINTS, "Jack Eichel", 1.5)


def test_ufc_round_of_finish_is_to_start_round_n():
    m = _market("Round of Finish", yes_sub_title="Fight ends before round 3")
    p = parse_typed_market(m, MMA)
    assert isinstance(p, RoundStartMarket) and p.market_type == MarketType.TO_START_ROUND_3
    rows = build_rows(start_date="2026-08-08", home="A", away="B",
                      markets=[m], cfg=MMA, league="ufc")
    assert [(r.side, r.kalshi_side) for r in rows] == [("no", "yes"), ("yes", "no")]
    other = _market("Round of Finish", yes_sub_title="Fight ends before 2:30 of round 3")
    with pytest.raises(ValueError, match="not 'Fight ends before round N'"):
        parse_typed_market(other, MMA)


def test_soccer_correct_score_is_the_yes_side_of_the_stated_scoreline():
    def cs(home_score, away_score, ids=("h-id", "a-id"), subtitle=None):
        hi, lo = max(home_score, away_score), min(home_score, away_score)
        return _market("Correct Score", yes_sub_title=subtitle or f"Wins {hi}-{lo}",
                       custom_strike={
            "home_team_id": ids[0], "away_team_id": ids[1],
            "home_score": str(home_score), "away_score": str(away_score)})
    rows = build_rows(start_date="2026-10-01", home="H", away="A",
                      markets=[cs(2, 1), cs(0, 3), cs(1, 1), cs(1, 0, ("a-id", "h-id"))],
                      cfg=SOCCER, league="epl")
    assert [(r.side, r.line, r.kalshi_side) for r in rows] == [
        ("H", 2.01, "yes"), ("A", 3.0, "yes"), ("_TIE", 1.01, "yes"), ("A", 1.0, "yes")]
    with pytest.raises(ValueError, match="not the game's"):
        parse_typed_market(cs(1, 0, ("x", "y")), SOCCER)
    with pytest.raises(ValueError, match="not in yes_sub_title"):
        parse_typed_market(cs(4, 3, subtitle="Stuttgart wins 5-3"), SOCCER)


def test_tennis_exact_match_score_takes_the_named_winner():
    m = _market("Exact Match Score",
                custom_strike={"Set Score": "2-1", "tennis_competitor": "a-id"})
    rows = build_rows(start_date="2026-10-01", home="H", away="A",
                      markets=[m], cfg=TENNIS, league="atp")
    assert [(r.market_type, r.side, r.line) for r in rows] == [("correct_score", "A", 2.01)]


@pytest.mark.parametrize("set_score", ["2-x", "3-3", "2-1-0", "1-2"])
def test_tennis_exact_match_score_rejects_a_malformed_set_score(set_score):
    m = _market("Exact Match Score",
                custom_strike={"Set Score": set_score, "tennis_competitor": "a-id"})
    with pytest.raises(ValueError):
        parse_typed_market(m, TENNIS)


def test_tennis_exact_match_score_flips_with_the_named_competitor():
    def row(who):
        m = _market("Exact Match Score",
                    custom_strike={"Set Score": "2-0", "tennis_competitor": who})
        parsed = parse_typed_market(m, TENNIS)
        assert isinstance(parsed, CorrectScoreMarket)
        return parsed.side
    assert (row("h-id"), row("a-id")) == (HOME, AWAY)


def test_soccer_correct_score_without_a_strike_is_rejected():
    m = _market("Correct Score", yes_sub_title="Wins 2-1")
    with pytest.raises(ValueError):
        parse_typed_market(m, SOCCER)


def test_soccer_correct_score_rejects_non_numeric_scores():
    m = _market("Correct Score", yes_sub_title="Wins 2-1", custom_strike={
        "home_team_id": "h-id", "away_team_id": "a-id",
        "home_score": "two", "away_score": "1"})
    with pytest.raises(ValueError):
        parse_typed_market(m, SOCCER)


@pytest.mark.parametrize("strike_type,floor", [
    ("less", 21.5), ("between", 21.5), (None, 21.5), ("greater", None)])
def test_total_with_an_untyped_line_is_rejected(strike_type, floor):
    m = _market("Total Games", strike_type=strike_type, floor_strike=floor)
    with pytest.raises(ValueError, match="no typed line"):
        parse_typed_market(m, TENNIS)


def test_set_winner_takes_the_set_from_the_event_scope():
    m = _market("Set 2 Winner", series="Set Winner",
                custom_strike={"tennis_competitor": "h-id"})
    p = parse_typed_market(m, TENNIS)
    assert p is not None and p.market_type == MarketType.SECOND_SET_WINNER


def test_three_way_leg_naming_neither_team_is_the_third_outcome():
    legs = [_market("First Team to Score", ticker=t, custom_strike={"soccer_team": i})
            for t, i in (("T-H", "h-id"), ("T-A", "a-id"), ("T-N", "no-goal-id"))]
    rows = build_rows(start_date="2026-10-01", home="H", away="A",
                      markets=legs, cfg=SOCCER, league="epl")
    assert sorted(r.side for r in rows) == ["A", "H", "_TIE"]


def test_incomplete_three_way_is_dropped(capsys):
    legs = [_market("First Team to Score", ticker="T-H", custom_strike={"soccer_team": "h-id"})]
    assert build_rows(start_date="2026-10-01", home="H", away="A",
                      markets=legs, cfg=SOCCER, league="epl") == []
    assert "drop incomplete" in capsys.readouterr().err


def test_race_to_points_rows_carry_the_target_as_line():
    legs = [_market("Race to 21 Points", series="Race to Points", ticker=t,
                    custom_strike={"football_team": i})
            for t, i in (("R-H", "h-id"), ("R-A", "a-id"), ("R-N", "neither-id"))]
    legs += [_market("Race to 14 Points", series="Race to Points", ticker=t,
                     custom_strike={"football_team": i})
             for t, i in (("S-H", "h-id"), ("S-A", "a-id"), ("S-N", "neither-id"))]
    rows = build_rows(start_date="2026-10-12", home="LAR", away="BUF",
                      markets=legs, cfg=FOOTBALL, league="nfl")
    got = sorted((r.line, r.side) for r in rows)
    assert got == [(14.0, "BUF"), (14.0, "LAR"), (14.0, "_TIE"),
                   (21.0, "BUF"), (21.0, "LAR"), (21.0, "_TIE")]
    assert {r.market_type for r in rows} == {"race_to_points"}


def test_inning_winner_takes_the_inning_from_the_event_scope():
    m = _market("3rd Inning Winner", series="Inning Winner",
                custom_strike={"baseball_team": "h-id"})
    p = parse_typed_market(m, BASEBALL)
    assert isinstance(p, ThreeWayMarket)
    assert (p.market_type, p.side) == (MarketType.INNING_3_WINNER_3WAY, HOME)


def test_overtime_count_strike_other_than_one_is_refused():
    one = _market("Overtime", strike_type="greater_or_equal", floor_strike=1)
    two = _market("Overtime", strike_type="greater_or_equal", floor_strike=2)
    p = parse_typed_market(one, FOOTBALL)
    assert p is not None and p.market_type == MarketType.WILL_THERE_BE_OVERTIME
    with pytest.raises(ValueError, match="strike line 1.5"):
        parse_typed_market(two, FOOTBALL)


def test_moneyline_without_a_typed_side_is_skipped():
    no_strike = _market("Game", series="Game")
    with pytest.raises(ValueError, match="no typed side"):
        parse_typed_market(no_strike, TENNIS)
    no_milestone = _market("Game", custom_strike={"tennis_competitor": "h-id"}, milestone=None)
    with pytest.raises(ValueError, match="no typed side"):
        parse_typed_market(no_milestone, TENNIS)
    tie_leg = _market("Game", custom_strike={"cricket_team": "t-id"})
    with pytest.raises(ValueError, match="strike names no team"):
        parse_typed_market(tie_leg, KalshiConfig(sport=Sport.CRICKET))


def test_spread_rows_favour_the_asked_about_side():
    m = _market("Spread", custom_strike={"football_team": "a-id"},
                strike_type="greater", floor_strike=7.5)
    p = parse_typed_market(m, FOOTBALL)
    assert isinstance(p, SpreadMarket) and p.side == AWAY
    rows = build_rows(start_date="2026-10-12", home="LAR", away="BUF",
                      markets=[m], cfg=FOOTBALL, league="nfl")
    assert [(r.side, r.line, r.kalshi_side) for r in rows] == [
        ("BUF", -7.5, "yes"), ("LAR", 7.5, "no")]


def test_football_halftime_fulltime_is_yes_per_outcome_keyed_by_sides():
    def team(t, name, tid):
        return _market("Game", ticker=t, yes_sub_title=name,
                       custom_strike={"football_team": tid})

    def combo(t, half, full):
        return _market("First Half / Fulltime", ticker=t,
                       custom_strike={"1st Half Result": half, "Fulltime Result": full})

    rows = build_rows(
        start_date="2026-10-01", home="HOM", away="AWY",
        markets=[
            team("G-1", "Cleveland", "h-id"), team("G-2", "Pittsburgh", "a-id"),
            combo("C-A", "Cleveland wins 1st Half", "Pittsburgh wins game"),
            combo("C-B", "Tie in 1st Half", "Game ends in a tie"),
            combo("C-C", "Nowhere wins 1st Half", "Game ends in a tie"),
        ],
        cfg=FOOTBALL, league="nfl")
    htft = [(r.side, r.kalshi_side, r.grouping_key) for r in rows
            if r.market_type == "halftime_fulltime"]
    # The unknown team name is skipped, never guessed.
    assert htft == [("yes", "yes", "HOM|AWY"), ("yes", "yes", "_TIE|_TIE")]


# --- yes/no subtitle check ---

def _line(yes: str, no: str, *, sport: str = "football", scope: str = "Game") -> str:
    return json.dumps({
        "event_ticker": "E", "ticker": "T", "title": "x",
        "yes_sub_title": yes, "no_sub_title": no,
        "sport": sport, "competition_scope": scope, "series_scope": scope,
    })


def test_category_label_prefixes_are_cosmetic():
    assert parse_market(_line(
        "Goal Diff Reg Time: Spain wins by more than 2.5 goals",
        "Reg Time: Spain wins by more than 2.5 goals", sport="soccer", scope="Spread"))
    with pytest.raises(SubtitleMismatchError):
        parse_market(_line("Reg Time: Spain wins by more than 2.5 goals",
                           "Reg Time: Austria wins by more than 2.5 goals",
                           sport="soccer", scope="Spread"))


def test_football_display_variants():
    assert parse_market(_line("Tennessee", "TEN Titans"))
    assert parse_market(_line("Los Angeles C wins by over 20.5 points",
                              "Los Angeles wins by over 20.5 points", scope="Spread"))
    with pytest.raises(SubtitleMismatchError):
        parse_market(_line("Tennessee", "Chicago"))
    with pytest.raises(SubtitleMismatchError):
        parse_market(_line("Detroit", "DET Pistons", sport="basketball"))


@pytest.mark.parametrize(("scope", "yes", "no"), [
    # Labels copied from the live Kalshi API, 2026-09-26.
    ("Point Total", "Over 59.5 points", "Over 59.5 points scored"),
    ("1st Half Spread", "PHI Eagles wins by over 7.5 points",
     "PHI Eagles wins 1H by over 7.5 points"),
    ("1st Half Total", "Over 7.5 points", "Over 7.5 1H points scored"),
    ("1st Half Winner", "Philadelphia", "Philadelphia wins 1st Half"),
    ("1st Quarter Winner", "Tie", "Tie 1st Quarter"),
    ("1st Quarter Total", "Over 7.5 points", "Over 7.5 1Q points scored"),
])
def test_football_no_label_may_restate_the_scopes_own_period(scope, yes, no):
    assert parse_market(_line(yes, no, scope=scope))


@pytest.mark.parametrize(("scope", "yes", "no"), [
    ("Spread", "PHI Eagles wins by over 7.5 points",
     "PHI Eagles wins 1H by over 7.5 points"),
    ("Game", "Tie", "Tie 1st Half"),
    ("1st Half Total", "Over 7.5 points", "Over 7.5 1Q points scored"),
    ("1st Quarter Winner", "Tie", "Tie 1st Half"),
    ("1st Half Total", "Over 7.5 points", "Over 8.5 1H points scored"),
])
def test_football_period_word_of_another_period_is_refused(scope, yes, no):
    with pytest.raises(SubtitleMismatchError):
        parse_market(_line(yes, no, scope=scope))


def test_parse_market_line_skips_a_real_disagreement(capsys):
    assert parse_market_line(_line("Philadelphia", "Chicago", scope="1st Half Winner")) is None
    assert "ALERT: kalshi skip T:" in capsys.readouterr().err
