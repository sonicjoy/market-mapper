"""PX 3-letter abbr unique-binds onto Optic 4-char codes (HUL → HCA7)."""

from __future__ import annotations

from datetime import datetime

from mappers.exchanges import px
from mappers.exchanges.optic import Fixture
from mappers.pipeline import ScheduleEntry, _recover_px_event, match_event
from mappers.px_name_bind import pin_px_name_miss
from mappers.shared import AliasMap, MatchKey

_DATE = "2026-09-05"
_HULL_OID = "8CCE04981270F895"
_AVL_OID = "AVL1111AVL1111AV"


def _entry() -> ScheduleEntry:
    fx = Fixture(
        fixture_id="epl-fx-1",
        game_id="g1",
        sportradar_id=None,
        start_et=f"{_DATE}T12:30:00",
        start_date=f"{_DATE}T16:30:00Z",
        home="HCA7",
        away="AVL",
        home_name="Hull City AFC",
        away_name="Aston Villa FC",
        team_map={_HULL_OID: "HCA7", _AVL_OID: "AVL"},
        odds=[],
        is_live=False,
    )
    return ScheduleEntry(fx)


def _event(*, hul: str = "HUL", hull_name: str = "Hull City AFC") -> px.ParsedEvent:
    raw = px.Event(
        event_id=90114098,
        status="not_started",
        scheduled=f"{_DATE}T16:30:00Z",
        sport_name="Soccer",
        tournament_id=1,
        tournament_name="EPL",
        competitors=[
            px.Competitor(id=1, abbreviation=hul, name=hull_name, side="home"),
            px.Competitor(
                id=2, abbreviation="AVL", name="Aston Villa FC", side="away",
            ),
        ],
    )
    return px.ParsedEvent(raw=raw, match_key=MatchKey(_DATE, hul, "AVL"))


def test_pin_px_name_miss_rewrites_hul_to_hca7() -> None:
    event = _event()
    index = {MatchKey(_DATE, "HCA7", "AVL"): [_entry()]}
    aliases: AliasMap = {}
    assert pin_px_name_miss(event, index, aliases, player=False) is True
    assert aliases["HUL"] == "HCA7"
    assert event.match_key == MatchKey(_DATE, "HCA7", "AVL")
    assert match_event(event, index) is True


def test_pin_px_name_miss_fits_hull_city_club_suffix() -> None:
    event = _event(hull_name="Hull City")
    index = {MatchKey(_DATE, "HCA7", "AVL"): [_entry()]}
    aliases: AliasMap = {}
    assert pin_px_name_miss(event, index, aliases, player=False) is True
    assert aliases["HUL"] == "HCA7"


def test_pin_px_name_miss_refuses_to_steal_existing_alias() -> None:
    event = _event()
    index = {MatchKey(_DATE, "HCA7", "AVL"): [_entry()]}
    aliases: AliasMap = {"HUL": "OTHER"}
    assert pin_px_name_miss(event, index, aliases, player=False) is False
    assert aliases["HUL"] == "OTHER"


def test_recover_unknown_px_code_skips_instead_of_raising() -> None:
    event = _event(hul="ZZZ", hull_name="Not A Real Club")
    index = {MatchKey(_DATE, "HCA7", "AVL"): [_entry()]}
    status = _recover_px_event(
        event, index, {_DATE}, {}, {"AVL", "HCA7"}, {},
        player=False,
        fetch_time=datetime(2026, 9, 4, 8, 0),
        horizon_cutoff=datetime(2026, 9, 12, 8, 0),
        league_name="epl",
    )
    assert status == "skip"
