"""Soccer goalscorer props: PX "To Score" yes/no and Optic anytime fold.

PX ships "<Player> To Score A Goal" / "<Player> To Score 2+ Goals" as
sup_moneyline YES/NO with the threshold only in the name, and with
outcome_id 1=NO (the reverse of its moneyline props).  Both land on
player_goals over/under N-0.5.  Optic's anytime_goal_scorer folds onto the
same player_goals 0.5 row so the PX leg has an Optic anchor.

Payloads are the live Argentina v Benin (PX event 90123170, 2026-10-06).
"""

from mappers.exchanges import px
from mappers.exchanges.optic import Fixture, Odd
from mappers.exchanges.optic import build_rows as optic_rows
from mappers.market_types import MarketType
from mappers.run import LEAGUES

WC_OPTIC = LEAGUES["world_cup"].OPTIC

PX_CFG = px.PxConfig(
    tournament_id=54,
    exact={},
    suffix=[
        (" To Score A Goal", MarketType.PLAYER_GOALS),
        (" To Score 2+ Goals", MarketType.PLAYER_GOALS),
    ],
)


def _px_market(market_id: int, name: str) -> px.Market:
    return px.Market(
        id=market_id, name=name, type="sup_moneyline", status="active",
        sport_event_id=90123170,
        selections=[
            {"display_name": "NO", "name": "NO", "outcome_id": 1,
             "strike": 0, "strike_id": f"{market_id}-no"},
            {"display_name": "YES", "name": "YES", "outcome_id": 2,
             "strike": 0, "strike_id": f"{market_id}-yes"},
        ],
    )


def _px_rows(market: px.Market) -> list[tuple[str, str | None, float | None, str, str | None]]:
    classified = px.classify_and_enrich(market, PX_CFG, {})
    rows = px.build_rows(
        "2026-10-06T23:00:00Z", "ARG", "BEN", [classified], {},
        league="international_friendlies")
    return sorted(
        (r.market_type, r.entity, r.line, r.side, r.px_line_id) for r in rows)


def test_px_to_score_a_goal_is_player_goals_over_half():
    market = _px_market(1500032312, "Lionel Messi To Score A Goal")
    assert _px_rows(market) == [
        ("player_goals", "lionel_messi", 0.5, "over", "1500032312-yes"),
        ("player_goals", "lionel_messi", 0.5, "under", "1500032312-no"),
    ]


def test_px_to_score_two_plus_is_player_goals_over_one_and_half():
    market = _px_market(1500032313, "Lionel Messi To Score 2+ Goals")
    assert _px_rows(market) == [
        ("player_goals", "lionel_messi", 1.5, "over", "1500032313-yes"),
        ("player_goals", "lionel_messi", 1.5, "under", "1500032313-no"),
    ]


def test_px_classifies_sup_moneyline_goals_as_yn_variant():
    match = px.classify_market(
        "Lionel Messi To Score A Goal", "sup_moneyline", PX_CFG)
    assert match.market_type == MarketType.PLAYER_GOALS_YN
    assert px.extract_player("Lionel Messi To Score A Goal", match.suffix or "") \
        == "Lionel Messi"


def test_px_yes_no_side_follows_display_name_not_outcome_id():
    assert px.resolve_side_label(
        px.Selection("l1", 1, 0.0, display_name="NO"), {}) == "no"
    assert px.resolve_side_label(
        px.Selection("l2", 2, 0.0, display_name="YES"), {}) == "yes"
    # moneyline props (1=YES) with no display_name keep the outcome_id map.
    assert px.resolve_side_label(px.Selection("l3", 1, 0.0), {}) == "yes"


def test_px_yes_no_threshold_only_for_goal_names():
    assert px._yes_no_threshold("Lionel Messi To Score A Goal") == 0.5
    assert px._yes_no_threshold("Lionel Messi To Score 3+ Goals") == 2.5
    assert px._yes_no_threshold("James Harden To Record a Double Double") is None


def _fixture(odds: list[Odd]) -> Fixture:
    return Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-10-06T19:00:00", start_date="2026-10-06T23:00:00Z",
        home="ARG", away="BEN", home_name="ARG", away_name="BEN",
        team_map={}, odds=odds, is_live=False,
    )


def _odd(market_id: str, selection: str, *, selection_line: str | None,
         points: float | None) -> Odd:
    return Odd(
        id=f"FIX1:{market_id}:{selection}:{selection_line}",
        market_id=market_id, selection=selection,
        selection_line=selection_line, points=points,
        player_id="P1", grouping_key="default",
    )


def _optic_keys(odds: list[Odd]) -> list[tuple[str, str | None, float | None, str]]:
    rows, _, _ = optic_rows(
        "2026-10-06T23:00:00Z", "ARG", "BEN", _fixture(odds), WC_OPTIC,
        league="world_cup")
    return sorted((r.market_type, r.entity, r.line, r.side) for r in rows)


def test_optic_anytime_is_anytime_goal_scorer():
    """Optic ships anytime as an affirmative leg, blank line, points 0."""
    odds = [_odd("anytime_goal_scorer", "Lionel Messi",
                 selection_line="", points=0.0)]
    assert _optic_keys(odds) == [("anytime_goal_scorer", "lionel_messi", None, "yes")]


def test_optic_anytime_skipped_when_player_goals_half_exists():
    """A book quoting both forms keeps the player_goals 0.5 odd only."""
    odds = [
        _odd("anytime_goal_scorer", "Lionel Messi",
             selection_line="", points=0.0),
        _odd("player_goals", "Lionel Messi", selection_line="over", points=0.5),
        _odd("player_goals", "Lionel Messi", selection_line="under", points=0.5),
    ]
    rows, lookup, _ = optic_rows(
        "2026-10-06T23:00:00Z", "ARG", "BEN", _fixture(odds), WC_OPTIC,
        league="world_cup")
    assert {(r.entity, r.line, r.side) for r in rows} == {
        ("lionel_messi", 0.5, "under"),
        ("lionel_messi", None, "yes"),
    }
    assert {lookup[r.optic_id or ""].market_id for r in rows} == {"player_goals"}
