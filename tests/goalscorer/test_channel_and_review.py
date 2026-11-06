"""Channel commands (add league / map one match) and review resolution."""

import json
from dataclasses import replace

import pytest

from goalscorer import channel
from goalscorer.commands import Command
from goalscorer.config import FIRST_GOAL_MARKET_ID, PLAYER_GOALS_MARKET_ID, REVIEW_SOURCE
from goalscorer.models import LineMapping, ReviewItem
from goalscorer.review import UNKNOWN_NAME, record, resolve_typed
from tests.goalscorer.fakes import FakeLeagues, FakeStore, fixture, goal, make_ctx, moneyline

SLUG = "international_-_friendlies"


@pytest.fixture
def kalshi_says(monkeypatch):
    def set_answer(answer):
        monkeypatch.setattr(channel, "kalshi_series_exists", lambda prefix: answer)

    return set_answer


def test_add_league_derives_series_and_registers(kalshi_says):
    kalshi_says(True)
    leagues = FakeLeagues(optic={SLUG: ("International - Friendlies", "soccer")}, derived={SLUG: "KXINTLFRIENDLYGOAL"})
    league, reply = channel.add_league(make_ctx(leagues=leagues), SLUG, None, "U1")
    assert league and league.goal_prefix == "KXINTLFRIENDLYGOAL"
    assert leagues.added == [(league, "U1")]
    assert "Added" in reply


def test_add_league_refusals(kalshi_says):
    kalshi_says(False)
    ctx = make_ctx(leagues=FakeLeagues(optic={SLUG: ("Friendlies", "soccer")}, derived={SLUG: "KXNOPEGOAL"}))
    assert channel.add_league(ctx, SLUG, None, "U1")[0] is None  # Kalshi has no such series
    assert "already mapped" in channel.add_league(ctx, "england_-_premier_league", None, "U1")[1]
    assert "no fixtures" in channel.add_league(ctx, "mars_-_league", None, "U1")[1]
    no_ml = make_ctx(leagues=FakeLeagues(optic={SLUG: ("Friendlies", "soccer")}))
    assert "KX…GOAL" in channel.add_league(no_ml, SLUG, None, "U1")[1]


def test_add_league_unconfirmed_series_still_added(kalshi_says):
    kalshi_says(None)
    leagues = FakeLeagues(optic={SLUG: ("Friendlies", "soccer")})
    league, reply = channel.add_league(make_ctx(leagues=leagues), SLUG, "KXFRIENDLYGOAL", "U1")
    assert league and "unconfirmed" in reply


def test_add_league_command_maps_the_league_immediately(kalshi_says):
    kalshi_says(True)
    store = FakeStore(
        fixture_rows=[fixture("g1", league=SLUG)],
        moneyline_rows={"g1": moneyline(series="KXINTLFRIENDLYGAME")},
        history={"c-ars": [goal("p", "Bukayo Saka", "ARSBSAKA7-1", day=20)]},
    )
    leagues = FakeLeagues(optic={SLUG: ("Friendlies", "soccer")}, derived={SLUG: "KXINTLFRIENDLYGOAL"})
    ctx = make_ctx(store, leagues)
    replies = channel.handle_command(ctx, Command("add_league", SLUG), "U1")
    assert len(replies) == 2 and "1 new" in replies[1]
    assert ctx.publisher.published[0]["selection"] == "Bukayo Saka"  # type: ignore[attr-defined]


def test_map_command_reports_errors():
    replies = channel.handle_command(make_ctx(), Command("map_fixture", "202608110FBC008C"), "U1")
    assert replies[0].startswith(":warning: No Optic fixture")


def test_resolve_typed_snaps_to_book_spelling():
    names = ["Martin Ødegaard", "Bukayo Saka"]
    assert resolve_typed("martin odegaard", names, force=False) == ("Martin Ødegaard", None)
    assert resolve_typed("Martin Odegard", names, force=False) == (None, UNKNOWN_NAME)
    assert resolve_typed("Martin Odegard", names, force=True) == ("Martin Odegard", None)
    assert resolve_typed("", names, force=True)[0] is None


def test_record_inserts_knowledge_row():
    item = ReviewItem("g1", fixture().start_date, "soccer", "EPL", "A vs B", "ARSX1-1", "KXEPLGOAL-P-ARSX1-1")
    ctx = make_ctx()
    assert "Mapped to *X*" in record(ctx, item, "X", "U1")
    assert ctx.store.inserted[0].ticker == item.ticker  # type: ignore[attr-defined]
    assert "Dry run" in record(make_ctx(dry_run=True), item, "X", "U1")


DELAP = ReviewItem("g1", fixture().start_date, "soccer", "EPL", "A vs B", "ARSLDELAP19-1", "KXEPLGOAL-P-ARSLDELAP19-1")


def test_record_repoints_this_jobs_stale_ticker_with_an_override():
    store = FakeStore(mappings=[goal("g1", "Liam Delap", "ARSLDELAP9-1", source="HENRY", part="P")])
    ctx = make_ctx(store)
    assert "replacing `ARSLDELAP9-1`" in record(ctx, DELAP, "Liam Delap", "U1")
    assert store.inserted == []
    [msg] = ctx.publisher.published  # type: ignore[attr-defined]
    assert msg["selection"] == "Liam Delap" and json.loads(msg["source_ids"])["market_id"] == DELAP.ticker
    assert ctx.publisher.sources == [REVIEW_SOURCE]  # type: ignore[attr-defined]


def test_record_refuses_multi_goal_tickers():
    store = FakeStore(mappings=[goal("g1", "Liam Delap", "ARSLDELAP19-1", source="HENRY", part="P")])
    ctx = make_ctx(store)
    two_plus = ReviewItem(
        "g1", fixture().start_date, "soccer", "EPL", "A vs B", "ARSLDELAP19-2", "KXEPLGOAL-P-ARSLDELAP19-2"
    )
    assert "not anytime — no change" in record(ctx, two_plus, "Liam Delap", "U1")
    assert "not anytime" in record(make_ctx(dry_run=True), two_plus, "Liam Delap", "U1")
    assert ctx.publisher.published == [] and store.inserted == []  # type: ignore[attr-defined]


def test_record_leaves_optic_mappings_and_held_tickers_alone():
    optic = make_ctx(FakeStore(mappings=[goal("g1", "Liam Delap", "ARSLDELAP9-1", part="P")]))
    assert ":warning:" in record(optic, DELAP, "Liam Delap", "U1")
    held = make_ctx(FakeStore(mappings=[goal("g1", "Someone Else", "ARSLDELAP19-1", part="P")]))
    assert "Mapped to *Someone Else* — no change" in record(held, DELAP, "Liam Delap", "U1")
    for ctx in (optic, held):
        assert ctx.publisher.published == [] and ctx.store.inserted == []  # type: ignore[attr-defined]


def test_record_maps_the_players_two_and_three_plus_lines_too():
    ctx = make_ctx()
    note = record(ctx, DELAP, "Liam Delap", "U1")
    assert "Mapped to *Liam Delap*" in note and "2+/3+ lines: 2 mapped" in note
    assert [(r.ticker, r.points) for r in ctx.store.inserted_lines] == [  # type: ignore[attr-defined]
        ("KXEPLGOAL-P-ARSLDELAP19-2", 1.5),
        ("KXEPLGOAL-P-ARSLDELAP19-3", 2.5),
    ]


def test_record_lines_repoint_own_rows_and_leave_others():
    store = FakeStore(
        line_rows=[
            LineMapping("g1", "Liam Delap", 1.5, "HENRY", "KXEPLGOAL-P-ARSLDELAP9-2"),  # our stale guess
            LineMapping("g1", "Liam Delap", 2.5, "GREG", "KXEPLGOAL-P-ARSLDELAP9-3"),  # Kalshi mapper's
        ]
    )
    ctx = make_ctx(store)
    assert "2+/3+ lines: 1 mapped, 1 already mapped" in record(ctx, DELAP, "Liam Delap", "U1")
    assert store.inserted_lines == []
    [msg] = ctx.publisher.published  # type: ignore[attr-defined]
    assert msg["market_id"] == PLAYER_GOALS_MARKET_ID and msg["points"] == 1.5
    assert json.loads(msg["source_ids"])["market_id"] == "KXEPLGOAL-P-ARSLDELAP19-2"
    assert ctx.publisher.sources == [REVIEW_SOURCE]  # type: ignore[attr-defined]


def test_record_already_mapped_player_still_gets_his_lines():
    store = FakeStore(mappings=[goal("g1", "Liam Delap", "ARSLDELAP19-1", part="P")])
    note = record(make_ctx(store), DELAP, "Liam Delap", "U1")
    assert "Already mapped for this game · 2+/3+ lines: 2 mapped" in note
    assert len(store.inserted_lines) == 2


def test_record_maps_first_goal_too():
    ctx = make_ctx()
    assert "first goal: mapped" in record(ctx, DELAP, "Liam Delap", "U1")
    [row] = ctx.store.inserted_first_goal  # type: ignore[attr-defined]
    assert (row.selection, row.ticker) == ("Liam Delap", "KXEPLFIRSTGOAL-P-ARSLDELAP19")


def test_record_first_goal_leaves_optic_and_repoints_own():
    optic = FakeStore(first_goal_rows=[goal("g1", "Liam Delap", "ARSLDELAP19", part="P")])
    optic.first_goal_rows = [replace(optic.first_goal_rows[0], ticker="KXEPLFIRSTGOAL-P-ARSLDELAP19")]
    assert "first goal: already mapped" in record(make_ctx(optic), DELAP, "Liam Delap", "U1")
    assert optic.inserted_first_goal == []
    ours = FakeStore(first_goal_rows=[goal("g1", "Liam Delap", "ARSLDELAP9", source="HENRY", part="P")])
    ours.first_goal_rows = [replace(ours.first_goal_rows[0], ticker="KXEPLFIRSTGOAL-P-ARSLDELAP9")]
    ctx = make_ctx(ours)
    assert "first goal: mapped" in record(ctx, DELAP, "Liam Delap", "U1")
    published = ctx.publisher.published  # type: ignore[attr-defined]
    [msg] = [m for m in published if m["market_id"] == FIRST_GOAL_MARKET_ID]
    assert json.loads(msg["source_ids"])["market_id"] == "KXEPLFIRSTGOAL-P-ARSLDELAP19"
