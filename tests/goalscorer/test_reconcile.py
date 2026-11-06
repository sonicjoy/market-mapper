"""Post-game reconcile: unmapped tickers → recorded or review cards."""

from datetime import date

from goalscorer.cards import ACTION_ACCEPT, BLOCK_REVIEW
from goalscorer.models import LineMapping
from goalscorer.reconcile import code_names, find_review_items, missing_first_goals, missing_lines, run_reconcile
from tests.goalscorer.fakes import FakeLeagues, FakeStore, fixture, goal, make_ctx, moneyline

PART = "26SEP26ARSCHE"
TICKERS = [
    f"KXEPLGOAL-{PART}-ARSBSAKA7-1",  # already mapped
    f"KXEPLGOAL-{PART}-ARSMMERIN1-1",  # new, suggestible
    f"KXEPLGOAL-{PART}-CHEXNEWBO99-1",  # new, no match
    f"KXEPLGOAL-{PART}-CHECPALME20-1",  # new, known from history
    "KXEPLGOAL-26SEP26LIVEVE-LIVMSALAH11-1",  # other fixture
]


def _store():
    return FakeStore(
        fixture_rows=[fixture()],
        moneyline_rows={"g1": moneyline()},
        mappings=[goal("g1", "Bukayo Saka", "ARSBSAKA7-1", part=PART)],
        names={"g1": {"Mikel Merino", "Bukayo Saka", "Cole Palmer"}},
        tickers=TICKERS,
        history={"c-che": [goal("p2", "Cole Palmer", "CHECPALME20-1", day=20)]},
    )


def test_find_review_items_only_unmapped_codes_on_our_fixtures():
    store = _store()
    items = find_review_items(
        [fixture()], FakeLeagues().active(), store.moneyline_rows, TICKERS, store.mappings, store.names
    )
    by_code = {i.player_code: i for i in items}
    assert set(by_code) == {"ARSMMERIN1-1", "CHEXNEWBO99-1", "CHECPALME20-1"}
    assert by_code["ARSMMERIN1-1"].suggested == "Mikel Merino"
    assert by_code["CHEXNEWBO99-1"].suggested is None
    assert by_code["ARSMMERIN1-1"].league == "England - Premier League"


def test_find_review_items_one_card_per_player_whichever_lines_traded():
    store = _store()
    multi = [
        f"KXEPLGOAL-{PART}-ARSBSAKA7-2",  # Saka's anytime is mapped → no card
        f"KXEPLGOAL-{PART}-ARSMMERIN1-1",
        f"KXEPLGOAL-{PART}-ARSMMERIN1-2",
        f"KXEPLGOAL-{PART}-ARSMMERIN1-3",
        f"KXEPLGOAL-{PART}-CHEXNEWBO99-3",  # only his 3+ traded
    ]
    items = find_review_items(
        [fixture()], FakeLeagues().active(), store.moneyline_rows, multi, store.mappings, store.names
    )
    assert [(i.player_code, i.ticker) for i in items] == [
        ("ARSMMERIN1-1", f"KXEPLGOAL-{PART}-ARSMMERIN1-1"),
        ("CHEXNEWBO99-1", f"KXEPLGOAL-{PART}-CHEXNEWBO99-1"),
    ]
    assert items[0].base_code == "ARSMMERIN1"


def test_find_review_items_does_not_count_a_multi_goal_row_as_mapped():
    store = _store()
    on_2plus = [goal("g1", "Bukayo Saka", "ARSBSAKA7-2", part=PART)]
    items = find_review_items(
        [fixture()], FakeLeagues().active(), store.moneyline_rows, [TICKERS[0]], on_2plus, store.names
    )
    assert [(i.player_code, i.suggested) for i in items] == [("ARSBSAKA7-1", "Bukayo Saka")]


def test_code_names_newest_wins():
    history = {"c": [goal("a", "Old Name", "XX1-1", day=1), goal("b", "New Name", "XX1-1", day=9)]}
    assert code_names(history) == {"XX1-1": "New Name"}


def test_code_names_keys_on_the_anytime_code():
    history = {"c": [goal("a", "Bruno Fernandes", "MUNBFERNA8-3", day=1)]}
    assert code_names(history) == {"MUNBFERNA8-1": "Bruno Fernandes"}


def test_run_reconcile_records_known_and_posts_cards_for_the_rest():
    ctx = make_ctx(_store())
    report = run_reconcile(ctx, date(2026, 9, 26))
    assert [i.player_code for i in report.auto] == ["CHECPALME20-1"]
    assert report.recorded == 1
    assert [(r.selection, r.ticker) for r in ctx.store.inserted] == [  # type: ignore[attr-defined]
        ("Cole Palmer", f"KXEPLGOAL-{PART}-CHECPALME20-1")
    ]
    assert [(r.selection, r.ticker, r.points) for r in ctx.store.inserted_lines] == [  # type: ignore[attr-defined]
        ("Cole Palmer", f"KXEPLGOAL-{PART}-CHECPALME20-2", 1.5),
        ("Cole Palmer", f"KXEPLGOAL-{PART}-CHECPALME20-3", 2.5),
    ]
    assert report.lines_recorded == 2
    assert [(r.selection, r.ticker) for r in ctx.store.inserted_first_goal] == [  # type: ignore[attr-defined]
        ("Cole Palmer", f"KXEPLFIRSTGOAL-{PART}-CHECPALME20")
    ]
    assert report.first_goal_recorded == 1
    posts = ctx.slack.posts  # type: ignore[attr-defined]
    assert len(posts) == len(report.review)  # cards only, no summary line
    card = posts[0][1]
    actions = next(b for b in card if b.get("block_id") == BLOCK_REVIEW)
    assert any(e.get("action_id") == ACTION_ACCEPT for e in actions["elements"])


def test_run_reconcile_dry_run_writes_nothing():
    ctx = make_ctx(_store(), dry_run=True)
    report = run_reconcile(ctx, date(2026, 9, 26))
    assert report.auto and report.recorded == 0
    store = ctx.store
    assert store.inserted == store.inserted_lines == store.inserted_first_goal == []  # type: ignore[attr-defined]


def test_run_reconcile_team_filter():
    ctx = make_ctx(_store())
    assert run_reconcile(ctx, date(2026, 9, 26), team="liverpool").fixtures == 0


def test_missing_lines_fills_traded_lines_of_already_mapped_players():
    store = _store()
    traded = [
        f"KXEPLGOAL-{PART}-ARSBSAKA7-2",  # Saka mapped on 1+, no 2+ row → record
        f"KXEPLGOAL-{PART}-ARSBSAKA7-3",  # already has a row → skip
        f"KXEPLGOAL-{PART}-ARSMMERIN1-2",  # anytime unmapped → that's a review card, not this
    ]
    lines = [LineMapping("g1", "Bukayo Saka", 2.5, "GREG", f"KXEPLGOAL-{PART}-ARSBSAKA7-3")]
    rows = missing_lines([fixture()], FakeLeagues().active(), store.moneyline_rows, traded, store.mappings, lines)
    assert [(r.selection, r.ticker, r.points) for r in rows] == [("Bukayo Saka", f"KXEPLGOAL-{PART}-ARSBSAKA7-2", 1.5)]


def test_find_review_items_counts_a_first_goal_leg_as_the_player():
    store = _store()
    traded = [f"KXEPLFIRSTGOAL-{PART}-ARSMMERIN1", f"KXEPLFIRSTGOAL-{PART}-ARSBSAKA7"]  # Saka mapped on 1+
    items = find_review_items(
        [fixture()], FakeLeagues().active(), store.moneyline_rows, traded, store.mappings, store.names
    )
    assert [(i.player_code, i.ticker) for i in items] == [("ARSMMERIN1-1", f"KXEPLGOAL-{PART}-ARSMMERIN1-1")]


def test_missing_first_goals_fills_traded_first_goal_of_already_mapped_players():
    store = _store()
    leagues = FakeLeagues().active()
    traded = [f"KXEPLFIRSTGOAL-{PART}-ARSBSAKA7", f"KXEPLFIRSTGOAL-{PART}-ARSMMERIN1"]
    rows = missing_first_goals([fixture()], leagues, store.moneyline_rows, traded, store.mappings, [])
    assert [(r.selection, r.ticker) for r in rows] == [("Bukayo Saka", f"KXEPLFIRSTGOAL-{PART}-ARSBSAKA7")]
    optic = [goal("g1", "Bukayo Saka", "ARSBSAKA7", part=PART)]
    assert missing_first_goals([fixture()], leagues, store.moneyline_rows, traded, store.mappings, optic) == []


def test_run_reconcile_reads_first_goal_legs():
    store = _store()
    store.tickers = [f"KXEPLFIRSTGOAL-{PART}-CHEXNEWBO99"]
    ctx = make_ctx(store)
    report = run_reconcile(ctx, date(2026, 9, 26))
    assert [i.player_code for i in report.review] == ["CHEXNEWBO99-1"]
    assert ctx.slack.posts[0][0] == "Unmapped player CHEXNEWBO99 (Arsenal vs Chelsea)"  # type: ignore[attr-defined]
