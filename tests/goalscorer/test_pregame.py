"""Pre-game planning and publishing."""

import json
from datetime import date

from goalscorer.config import FIRST_GOAL_MARKET_ID, MAPPING_SOURCE, MARKET_ID, OVERRIDE_SOURCE, PLAYER_GOALS_MARKET_ID
from goalscorer.models import LineMapping, OverrideState
from goalscorer.pregame import (
    known_players,
    line_untouchable,
    map_fixtures,
    match_players,
    plan_game,
    registered_prefix,
    run_pregame,
    summary_text,
    untouchable,
)
from goalscorer.single import map_single
from tests.goalscorer.fakes import FakeStore, fixture, goal, make_ctx, moneyline

HISTORY = {
    "c-ars": [
        goal("p1", "Bukayo Saka", "ARSBSAKA7-1", day=1),
        goal("p1", "Kai Havertz", "ARSKHAVER29-1", day=1),
        goal("p1", "Bruno Fernandes", "MUNBFERNA8-1", day=1),  # opponent in that game
    ],
    "c-che": [goal("p2", "Cole Palmer", "CHECPALME20-1", day=2, source="HENRY")],
}


def test_known_players_newest_game_wins_and_filters_team():
    rows = [
        goal("old", "Bukayo Saka", "ARSBSAKA7-1", day=1),
        goal("new", "Bukayo Saka", "ARSBSAKA11-1", day=5, source="HENRY"),
        goal("new", "Bruno Fernandes", "MUNBFERNA8-1", day=5),
    ]
    assert {s: m.ticker for s, m in known_players(rows, "ARS").items()} == {
        "Bukayo Saka": "KXEPLGOAL-26AUG01ARSMUN-ARSBSAKA11-1"
    }


def test_match_players_guesses_the_anytime_line_from_a_multi_goal_row():
    history = {"c-che": [goal("b", "Cole Palmer", "CHECPALME20-3", day=9)]}
    assert match_players(fixture(), moneyline(), history) == {"Cole Palmer": "CHECPALME20-1"}


def test_known_players_original_wins_same_game():
    rows = [
        goal("g", "Bukayo Saka", "ARSBSAKA99-1", day=3, source="HENRY"),
        goal("g", "Bukayo Saka", "ARSBSAKA7-1", day=3, source="ORIGINAL"),
    ]
    assert known_players(rows, "ARS")["Bukayo Saka"].mapping_source == "ORIGINAL"


def test_match_players_takes_the_newest_club_for_a_player_in_both_histories():
    history = {
        "c-ars": [goal("a", "Raheem Sterling", "ARSRSTERL30-1", day=3)],
        "c-che": [
            goal("b", "Raheem Sterling", "CHERSTERL7-1", day=9),
            goal("b", "Cole Palmer", "CHECPALME20-1", day=9),
        ],
    }
    assert match_players(fixture(), moneyline(), history) == {
        "Raheem Sterling": "CHERSTERL7-1",
        "Cole Palmer": "CHECPALME20-1",
    }


def test_untouchable_respects_optic_and_other_overrides():
    existing = [goal("g1", "Bukayo Saka", "ARSBSAKA7-1"), goal("g1", "Kai Havertz", "ARSKHAVER29-1", source="HENRY")]
    overrides = [
        OverrideState("g1", "Cole Palmer", "T1", True, OVERRIDE_SOURCE),
        OverrideState("g1", "Enzo Fernandez", "T2", False, "mapping-console"),
    ]
    fixed, ours = untouchable(existing, overrides)
    assert fixed == {"Bukayo Saka", "Enzo Fernandez"}
    assert ours == {"Cole Palmer": "T1"}


def test_plan_game_skips_without_moneyline_or_abbreviation():
    fx = fixture()
    assert plan_game(fx, "KXEPLGOAL", None, HISTORY, (set(), {})).skipped == "no Kalshi moneyline mapping"
    ml = moneyline()
    ml.teams.pop("Chelsea")
    outcome = plan_game(fx, "KXEPLGOAL", ml, HISTORY, (set(), {}))
    assert outcome.skipped and "Chelsea" in outcome.skipped
    assert not outcome.planned


def test_plan_game_builds_tickers_and_skips_covered():
    ours = {"Kai Havertz": "KXEPLGOAL-26SEP26ARSCHE-ARSKHAVER29-1", "Cole Palmer": "KXEPLGOAL-26SEP26ARSCHE-OLD-1"}
    outcome = plan_game(fixture(), "KXEPLGOAL", moneyline(), HISTORY, ({"Bukayo Saka"}, ours))
    assert outcome.covered == 2  # Saka (Optic) + Havertz (identical override)
    assert [(p.selection, p.ticker) for p in outcome.planned if p.is_anytime] == [
        ("Cole Palmer", "KXEPLGOAL-26SEP26ARSCHE-CHECPALME20-1"),  # ticker changed → republish
    ]


def test_plan_game_maps_two_and_three_plus_lines_for_every_known_player():
    outcome = plan_game(fixture(), "KXEPLGOAL", moneyline(), HISTORY, ({"Bukayo Saka"}, {}))
    lines = {(p.selection, p.points): p.ticker for p in outcome.planned if p.points}
    # Saka's anytime is Optic's, but his 2+ / 3+ lines still get mapped from the same code.
    assert lines[("Bukayo Saka", 1.5)] == "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-2"
    assert lines[("Bukayo Saka", 2.5)] == "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-3"
    assert lines[("Cole Palmer", 2.5)] == "KXEPLGOAL-26SEP26ARSCHE-CHECPALME20-3"
    assert len(lines) == 6 and outcome.lines_planned == 6 and outcome.anytime_planned == 2


def test_plan_game_leaves_other_mappers_lines_and_skips_identical_own_lines():
    line_covered = line_untouchable(
        [LineMapping("g1", "Bukayo Saka", 1.5, "GREG", "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-2")],
        [
            OverrideState("g1", "Kai Havertz", "KXEPLGOAL-26SEP26ARSCHE-ARSKHAVER29-3", True, OVERRIDE_SOURCE, 2.5),
            OverrideState("g1", "Cole Palmer", "T", True, "mapping-console", 1.5),
        ],
    )
    outcome = plan_game(fixture(), "KXEPLGOAL", moneyline(), HISTORY, (set(), {}), line_covered)
    planned = {(p.selection, p.points) for p in outcome.planned if p.points}
    assert ("Bukayo Saka", 1.5) not in planned  # Kalshi mapper's row
    assert ("Kai Havertz", 2.5) not in planned  # our identical override
    assert ("Cole Palmer", 1.5) not in planned  # someone else's override
    assert ("Bukayo Saka", 2.5) in planned and ("Cole Palmer", 2.5) in planned
    assert outcome.line_covered == 3


def test_line_untouchable_judges_our_own_rows_by_our_override():
    fixed, ours = line_untouchable(
        [LineMapping("g1", "Bukayo Saka", 1.5, MAPPING_SOURCE, "OLD")],
        [OverrideState("g1", "Bukayo Saka", "OLD", True, OVERRIDE_SOURCE, 1.5)],
    )
    assert fixed == set()
    assert ours == {("Bukayo Saka", 1.5): "OLD"}


def test_map_fixtures_publishes_override_messages():
    ctx = make_ctx(FakeStore(moneyline_rows={"g1": moneyline()}, history=HISTORY))
    [outcome] = map_fixtures(ctx, [fixture()], lambda fx, ml: "KXEPLGOAL")
    assert outcome.anytime_planned == 3 and outcome.lines_planned == 6
    published = ctx.publisher.published  # type: ignore[attr-defined]
    saka = next(m for m in published if m["selection"] == "Bukayo Saka" and m["market_id"] == MARKET_ID)
    assert saka["mapping_source"] == MAPPING_SOURCE
    assert saka["active"] is True
    assert json.loads(saka["source_ids"]) == {"market_id": "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-1", "selection_id": "yes"}


def test_map_fixtures_publishes_player_goals_lines_in_optics_shape():
    ctx = make_ctx(FakeStore(moneyline_rows={"g1": moneyline()}, history=HISTORY))
    map_fixtures(ctx, [fixture()], lambda fx, ml: "KXEPLGOAL")
    published = ctx.publisher.published  # type: ignore[attr-defined]
    saka_3 = next(m for m in published if m["selection"] == "Bukayo Saka" and m["points"] == 2.5)
    assert saka_3 == {
        "game_id": "g1",
        "market_id": PLAYER_GOALS_MARKET_ID,
        "sportsbook": "Kalshi",
        "selection": "Bukayo Saka",
        "selection_line": "over",
        "points": 2.5,
        "selection_points": 2.5,  # Optic sets both to the line
        "grouping_key": "bukayo_saka:2.5",
        "source_ids": json.dumps({"market_id": "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-3", "selection_id": "yes"}),
        "active": True,
        "mapping_source": MAPPING_SOURCE,
    }


def test_summary_text_reports_lines_separately():
    ctx = make_ctx(FakeStore(moneyline_rows={"g1": moneyline()}, history=HISTORY))
    outcomes = map_fixtures(ctx, [fixture()], lambda fx, ml: "KXEPLGOAL")
    text = summary_text("Pre-game", outcomes)
    assert "published 12 mapping(s)" in text
    assert (
        "3 new, 0 already covered · 2+/3+ lines: 6 new, 0 already covered · first goal: 3 new, 0 already covered"
        in text
    )


def test_run_pregame_covers_registered_leagues_in_window():
    store = FakeStore(
        fixture_rows=[fixture("g1"), fixture("g2", league="italy_-_serie_a")],
        moneyline_rows={"g1": moneyline(), "g2": moneyline("26SEP26INTMIL")},
        history=HISTORY,
    )
    ctx = make_ctx(store, days_ahead=0)
    outcomes = run_pregame(ctx, date(2026, 9, 26))
    assert [o.fixture.game_id for o in outcomes] == ["g1"]
    assert run_pregame(ctx, date(2026, 9, 27)) == []


def test_registered_prefix_uses_league_series():
    prefix_for = registered_prefix(make_ctx().leagues.active())
    assert prefix_for(fixture(), moneyline()) == "KXEPLGOAL"
    assert prefix_for(fixture(league="italy_-_serie_a"), moneyline()) is None


def test_map_single_from_ticker_derives_series_for_unregistered_league():
    store = FakeStore(
        fixture_rows=[fixture("g9", league="international_-_friendlies")],
        moneyline_rows={"g9": moneyline(series="KXINTLFRIENDLYGAME")},
        part_games={"26SEP26ARSCHE": ["g9"]},
        history=HISTORY,
    )
    outcome, error = map_single(make_ctx(store), "KXINTLFRIENDLYGAME-26SEP26ARSCHE-ARS", is_ticker=True)
    assert not error and outcome
    assert all(
        p.ticker.startswith(("KXINTLFRIENDLYGOAL-26SEP26ARSCHE-", "KXINTLFRIENDLYFIRSTGOAL-26SEP26ARSCHE-"))
        for p in outcome.planned
    )


def test_map_single_reports_ambiguous_or_missing_fixture():
    store = FakeStore(part_games={"26SEP26ARSCHE": ["a", "b"]})
    assert map_single(make_ctx(store), "KXEPLGAME-26SEP26ARSCHE", is_ticker=True)[0] is None
    outcome, error = map_single(make_ctx(store), "NOPE-NOPE", is_ticker=True)
    assert outcome is None and "No Optic game" in error


def test_plan_game_maps_first_goal_from_the_same_code():
    outcome = plan_game(fixture(), "KXEPLGOAL", moneyline(), HISTORY, (set(), {}))
    first = {p.selection: p.ticker for p in outcome.planned if p.is_first_goal}
    assert first == {
        "Bukayo Saka": "KXEPLFIRSTGOAL-26SEP26ARSCHE-ARSBSAKA7",
        "Kai Havertz": "KXEPLFIRSTGOAL-26SEP26ARSCHE-ARSKHAVER29",
        "Cole Palmer": "KXEPLFIRSTGOAL-26SEP26ARSCHE-CHECPALME20",
    }
    assert outcome.first_goal_planned == 3


def test_plan_game_first_goal_follows_the_anytime_rules():
    first_covered = untouchable(
        [goal("g1", "Bukayo Saka", "ARSBSAKA7", part="26SEP26ARSCHE")],  # Optic maps Kalshi first goal itself
        [OverrideState("g1", "Kai Havertz", "KXEPLFIRSTGOAL-26SEP26ARSCHE-ARSKHAVER29", True, OVERRIDE_SOURCE)],
    )
    outcome = plan_game(fixture(), "KXEPLGOAL", moneyline(), HISTORY, (set(), {}), None, first_covered)
    assert [p.selection for p in outcome.planned if p.is_first_goal] == ["Cole Palmer"]
    assert outcome.first_goal_covered == 2


def test_map_fixtures_publishes_first_goal_in_optics_shape():
    store = FakeStore(
        moneyline_rows={"g1": moneyline()},
        history=HISTORY,
        first_goal_rows=[goal("g1", "Bukayo Saka", "ARSBSAKA7", part="26SEP26ARSCHE")],
    )
    ctx = make_ctx(store)
    [outcome] = map_fixtures(ctx, [fixture()], lambda fx, ml: "KXEPLGOAL")
    assert outcome.first_goal_planned == 2 and outcome.first_goal_covered == 1
    published = ctx.publisher.published  # type: ignore[attr-defined]
    palmer = next(m for m in published if m["selection"] == "Cole Palmer" and m["market_id"] == FIRST_GOAL_MARKET_ID)
    assert palmer == {
        "game_id": "g1",
        "market_id": FIRST_GOAL_MARKET_ID,
        "sportsbook": "Kalshi",
        "selection": "Cole Palmer",
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
        "source_ids": json.dumps({"market_id": "KXEPLFIRSTGOAL-26SEP26ARSCHE-CHECPALME20", "selection_id": "yes"}),
        "active": True,
        "mapping_source": MAPPING_SOURCE,
    }


def test_map_single_from_a_first_goal_ticker_uses_the_anytime_series():
    store = FakeStore(
        fixture_rows=[fixture("g9", league="international_-_friendlies")],
        moneyline_rows={"g9": moneyline()},
        part_games={"26SEP26ARSCHE": ["g9"]},
        history=HISTORY,
    )
    outcome, _ = map_single(make_ctx(store), "KXEPLFIRSTGOAL-26SEP26ARSCHE-ARSBSAKA7", is_ticker=True)
    assert outcome is not None
    assert "KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-1" in {p.ticker for p in outcome.planned if p.is_anytime}
