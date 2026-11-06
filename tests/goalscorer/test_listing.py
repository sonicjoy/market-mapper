"""Listing check: move pre-game guesses onto the tickers Kalshi lists."""

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from goalscorer import kalshi
from goalscorer.config import FIRST_GOAL_MARKET_ID, LISTING_SOURCE, OVERRIDE_SOURCE, REVIEW_SOURCE
from goalscorer.listing import Move, event_date, event_ticker, plan_moves, run_listing_check
from goalscorer.models import GoalMapping, OverrideState
from tests.goalscorer.fakes import KICKOFF, FakeStore, goal, make_ctx

PART = "26SEP25ARSCHE"  # today on the frozen clock
EVENT = f"KXEPLGOAL-{PART}"


def tk(code: str) -> str:
    return f"{EVENT}-{code}"


def guess(selection: str, code: str, *, source: str = OVERRIDE_SOURCE, active: bool = True) -> OverrideState:
    return OverrideState("g1", selection, tk(code), active, source)


def line_guess(selection: str, code: str, points: float, *, source: str = OVERRIDE_SOURCE) -> OverrideState:
    return OverrideState("g1", selection, tk(code), True, source, points)


LISTED = {
    tk("ARSBSAKA7-1"): "Bukayo Saka",
    tk("ARSLDELAP19-1"): "Liam Delap",  # kit number changed (guessed 9)
    tk("CHEDMUNOZ27-1"): "Daniel Munoz",  # changed club (guessed ARS…2)
    tk("CHECPALME20-1"): "Cole Palmer",
}


def test_event_helpers():
    assert event_ticker(tk("ARSBSAKA7-1")) == EVENT
    assert event_date(EVENT) == date(2026, 9, 25)
    assert event_date("KXEPLGOAL-NOTADATE") is None


def test_plan_moves_follows_kit_and_club_changes():
    overrides = [
        guess("Bukayo Saka", "ARSBSAKA7-1"),  # listed as guessed
        guess("Liam Delap", "ARSLDELAP9-1"),
        guess("Daniel Muñoz", "ARSDMUNOZ2-1"),
        guess("Not In Squad", "ARSNSQUAD4-1"),  # no listed match: left alone
    ]
    assert plan_moves(overrides, LISTED) == [
        Move("g1", "Daniel Muñoz", tk("ARSDMUNOZ2-1"), tk("CHEDMUNOZ27-1")),
        Move("g1", "Liam Delap", tk("ARSLDELAP9-1"), tk("ARSLDELAP19-1")),
    ]


def test_plan_moves_never_takes_a_held_ticker_or_picks_between_claimants():
    overrides = [
        guess("Cole Palmer", "CHECPALME10-1"),
        guess("Liam Delap", "ARSLDELAP9-1"),
        guess("L. Delap", "ARSLDELAP8-1"),  # same code letters: two claims on one ticker
    ]
    held = [goal("g1", "Cole J. Palmer", "CHECPALME20-1", part=PART)]
    assert plan_moves(overrides, LISTED, held) == []


def test_plan_moves_ignores_multi_goal_markets_listed_before_the_anytime_one():
    overrides = [guess("Eberechi Eze", "ARSEEZE10-1")]
    early = {tk("ARSEEZE10-3"): "Eberechi Eze"}  # Kalshi listed 3+ eleven minutes before 1+
    assert plan_moves(overrides, early) == []
    assert plan_moves(overrides, {**early, tk("ARSEEZE10-1"): "Eberechi Eze"}) == []
    moved = [guess("Liam Delap", "ARSLDELAP9-1")]
    lines = {tk("ARSLDELAP19-2"): "Liam Delap", tk("ARSLDELAP19-1"): "Liam Delap"}
    assert plan_moves(moved, lines) == [Move("g1", "Liam Delap", tk("ARSLDELAP9-1"), tk("ARSLDELAP19-1"))]


def test_plan_moves_only_moves_active_pregame_guesses():
    overrides = [
        guess("Liam Delap", "ARSLDELAP9-1", source=REVIEW_SOURCE),
        guess("Daniel Muñoz", "ARSDMUNOZ2-1", active=False),
    ]
    assert plan_moves(overrides, LISTED) == []


def test_run_listing_check_publishes_moves_under_the_listing_source():
    store = FakeStore(
        overrides=[guess("Liam Delap", "ARSLDELAP9-1"), guess("Bukayo Saka", "ARSBSAKA7-1")],
        mappings=[goal("g1", "Liam Delap", "ARSLDELAP9-1", source="HENRY", part=PART)],
    )
    ctx = make_ctx(store)
    asked: list[str] = []

    def listing(event):
        asked.append(event)
        return LISTED

    moves = run_listing_check(ctx, listing)
    assert asked == [EVENT]
    assert [(m.selection, m.new) for m in moves] == [("Liam Delap", tk("ARSLDELAP19-1"))]
    [msg] = ctx.publisher.published  # type: ignore[attr-defined]
    assert json.loads(msg["source_ids"])["market_id"] == tk("ARSLDELAP19-1") and msg["active"] is True
    assert ctx.publisher.sources == [LISTING_SOURCE]  # type: ignore[attr-defined]
    assert ctx.slack.posts == []  # type: ignore[attr-defined]  # moves go to the job log only


def test_run_listing_check_reads_mapping_rows_once_for_every_game_and_market():
    part = "26SEP24RMABAR"  # yesterday's event, still open
    other, first = f"KXEPLGOAL-{part}", f"KXEPLFIRSTGOAL-{part}"
    optic = "Vinícius José Paixão de Oliveira Júnior"
    store = FakeStore(
        overrides=[
            guess("Liam Delap", "ARSLDELAP9-1"),
            OverrideState("g2", "Vinicius Junior", f"{other}-RMAVINI9-1", True, OVERRIDE_SOURCE),
        ],
        line_overrides=[line_guess("Liam Delap", "ARSLDELAP9-2", 1.5)],
        first_goal_overrides=[OverrideState("g2", "Vinicius Junior", f"{first}-RMAVINI9", True, OVERRIDE_SOURCE)],
        mappings=[goal("g2", optic, "RMAVINI7-1", part=part)],
        first_goal_rows=[GoalMapping("g2", KICKOFF, optic, "ORIGINAL", f"{first}-RMAVINI7")],
    )
    reads: list[tuple] = []
    rows = store.held_rows
    store.held_rows = lambda *a: reads.append(a) or rows(*a)  # type: ignore[method-assign]
    listings = {
        EVENT: {**LISTED, tk("ARSLDELAP19-2"): "Liam Delap"},
        other: {f"{other}-RMAVINI7-1": "Vinicius Junior"},
        first: {f"{first}-RMAVINI7": "Vinicius Junior"},
    }

    moves = run_listing_check(make_ctx(store), listings.get)
    assert [m.new for m in moves] == [tk("ARSLDELAP19-1"), tk("ARSLDELAP19-2")]  # Optic holds both of Vinicius's
    assert reads == [(["g1", "g2"], datetime(2026, 9, 23, tzinfo=UTC), datetime(2026, 9, 27, tzinfo=UTC))]


def test_run_listing_check_waits_for_kalshi_and_skips_far_events():
    far = OverrideState("g2", "Someone", "KXEPLGOAL-26SEP28ARSCHE-ARSSOMEO1-1", True, OVERRIDE_SOURCE)
    store = FakeStore(overrides=[guess("Liam Delap", "ARSLDELAP9-1"), far])
    store.held_rows = lambda *a: pytest.fail("read mapping rows with nothing to move")  # type: ignore[method-assign]
    ctx = make_ctx(store)
    asked: list[str] = []

    def listing(event):
        asked.append(event)
        return {}  # not listed yet

    assert run_listing_check(ctx, listing) == []
    assert asked == [EVENT]  # 28 Sep is too far out to ask about
    assert ctx.publisher.published == [] and ctx.slack.posts == []  # type: ignore[attr-defined]


def test_plan_moves_on_a_multi_goal_line_only_uses_that_lines_markets():
    listed = {
        tk("ARSLDELAP19-1"): "Liam Delap",
        tk("ARSLDELAP19-2"): "Liam Delap",
        tk("ARSLDELAP19-3"): "Liam Delap",
    }
    two = [line_guess("Liam Delap", "ARSLDELAP9-2", 1.5)]
    assert plan_moves(two, listed, line="2", points=1.5) == [
        Move("g1", "Liam Delap", tk("ARSLDELAP9-2"), tk("ARSLDELAP19-2"), 1.5)
    ]
    three = [line_guess("Liam Delap", "ARSLDELAP9-3", 2.5)]
    assert plan_moves(three, {tk("ARSLDELAP19-1"): "Liam Delap"}, line="3", points=2.5) == []


def test_run_listing_check_moves_line_guesses_as_player_goals():
    store = FakeStore(
        overrides=[guess("Liam Delap", "ARSLDELAP9-1")],
        line_overrides=[
            line_guess("Liam Delap", "ARSLDELAP9-2", 1.5),
            line_guess("Liam Delap", "ARSLDELAP9-3", 2.5),
            line_guess("Bukayo Saka", "ARSBSAKA7-2", 1.5, source=REVIEW_SOURCE),  # not ours: never moved
        ],
    )
    listed = {
        tk("ARSLDELAP19-1"): "Liam Delap",
        tk("ARSLDELAP19-2"): "Liam Delap",
        tk("ARSLDELAP19-3"): "Liam Delap",
        tk("ARSBSAKA77-2"): "Bukayo Saka",
    }
    ctx = make_ctx(store)
    asked: list[str] = []

    def listing(event):
        asked.append(event)
        return listed

    moves = run_listing_check(ctx, listing)
    assert asked == [EVENT]  # one Kalshi call shared by the anytime and line checks
    assert [(m.new, m.points) for m in moves] == [
        (tk("ARSLDELAP19-1"), 0.0),
        (tk("ARSLDELAP19-2"), 1.5),
        (tk("ARSLDELAP19-3"), 2.5),
    ]
    published = ctx.publisher.published  # type: ignore[attr-defined]
    assert [m["market_id"] for m in published] == ["anytime_goal_scorer", "player_goals", "player_goals"]
    assert published[2]["grouping_key"] == "liam_delap:2.5" and published[2]["selection_line"] == "over"
    assert ctx.publisher.sources == [LISTING_SOURCE] * 3  # type: ignore[attr-defined]


def test_event_players_reads_names_and_survives_kalshi_errors(monkeypatch):
    resp = MagicMock()
    resp.json.return_value = {
        "markets": [
            {"ticker": "T1", "yes_sub_title": "Jorgen Strand Larsen: 1+"},
            {"ticker": "T2", "title": "Liam Delap: 1+ goals"},
        ]
    }
    monkeypatch.setattr(kalshi.requests, "get", lambda *a, **k: resp)
    assert kalshi.event_players("E") == {"T1": "Jorgen Strand Larsen", "T2": "Liam Delap"}

    markets = resp.json.return_value["markets"]
    markets[0]["status"] = "finalized"  # a player market settles early; the event is still open
    assert kalshi.event_players("E") == {"T1": "Jorgen Strand Larsen", "T2": "Liam Delap"}
    markets[1]["status"] = "closed"
    assert kalshi.event_players("E") == {}  # the event has closed: nothing left to move onto

    def down(*a, **k):
        raise kalshi.requests.ConnectionError("down")

    monkeypatch.setattr(kalshi.requests, "get", down)
    assert kalshi.event_players("E") is None


def test_run_listing_check_moves_first_goal_guesses_against_their_own_event():
    first_event = f"KXEPLFIRSTGOAL-{PART}"
    store = FakeStore(
        first_goal_overrides=[OverrideState("g1", "Liam Delap", f"{first_event}-ARSLDELAP9", True, OVERRIDE_SOURCE)],
        first_goal_rows=[goal("g1", "Cole Palmer", "CHECPALME20", part=PART)],
    )
    listed = {f"{first_event}-ARSLDELAP19": "Liam Delap", f"{first_event}-CHECPALME20": "Cole Palmer"}
    ctx = make_ctx(store)
    asked: list[str] = []

    def listing(event):
        asked.append(event)
        return listed

    [move] = run_listing_check(ctx, listing)
    assert asked == [first_event]
    assert (move.old, move.new, move.market_id) == (
        f"{first_event}-ARSLDELAP9",
        f"{first_event}-ARSLDELAP19",
        FIRST_GOAL_MARKET_ID,
    )
    [msg] = ctx.publisher.published  # type: ignore[attr-defined]
    assert msg["market_id"] == FIRST_GOAL_MARKET_ID and msg["grouping_key"] == "default"
    assert json.loads(msg["source_ids"])["market_id"] == f"{first_event}-ARSLDELAP19"
