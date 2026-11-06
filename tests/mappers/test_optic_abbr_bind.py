"""Book code binds onto fixture canonical via Optic competitor abbreviation."""

from __future__ import annotations

from mappers.exchanges import px
from mappers.exchanges.optic import Fixture
from mappers.optic_abbr_bind import (
    lookup_oriented,
    oriented_hit,
    pin_optic_abbr_codes,
    planned_optic_abbr_aliases,
)
from mappers.pipeline import ScheduleEntry, match_event
from mappers.shared import AliasMap, MatchKey

_DATE = "2026-09-19"
_MIL_OID = "EE920655996C0001"
_WHU_OID = "F6661C67A735972A"


def _fx() -> Fixture:
    return Fixture(
        fixture_id="elc-1",
        game_id="g1",
        sportradar_id=None,
        start_et=f"{_DATE}T09:00:00",
        start_date=f"{_DATE}T14:00:00Z",
        home="MFI2",
        away="WHUF6",
        home_name="Millwall",
        away_name="West Ham United",
        team_map={_MIL_OID: "MFI2", _WHU_OID: "WHUF6"},
        odds=[],
        is_live=False,
        home_optic_abbr="MIL",
        away_optic_abbr="WHU",
    )


def test_oriented_hit_accepts_optic_abbr_or_canonical() -> None:
    fx = _fx()
    assert oriented_hit("MIL", "WHU", fx)
    assert oriented_hit("MFI2", "WHUF6", fx)
    assert oriented_hit("MIL", "WHUF6", fx)
    assert not oriented_hit("WHU", "MIL", fx)


def test_lookup_oriented_finds_abbr_pair() -> None:
    entry = ScheduleEntry(_fx())
    index = {MatchKey(_DATE, "MFI2", "WHUF6"): [entry]}
    hits = lookup_oriented(index, _DATE, "MIL", "WHU")
    assert hits == [entry]


def test_planned_aliases_map_shorts_to_canonical() -> None:
    fx = _fx()
    assert planned_optic_abbr_aliases("MIL", "WHU", fx) == {
        "MIL": "MFI2", "WHU": "WHUF6",
    }


def test_px_match_event_rewrites_match_key_and_pins() -> None:
    entry = ScheduleEntry(_fx())
    index = {MatchKey(_DATE, "MFI2", "WHUF6"): [entry]}
    raw = px.Event(
        event_id=1,
        status="not_started",
        scheduled=f"{_DATE}T14:00:00Z",
        sport_name="Soccer",
        tournament_id=1,
        tournament_name="Championship",
        competitors=[
            px.Competitor(id=1, abbreviation="MIL", name="Millwall", side="home"),
            px.Competitor(
                id=2, abbreviation="WHU", name="West Ham United", side="away",
            ),
        ],
    )
    event = px.ParsedEvent(raw=raw, match_key=MatchKey(_DATE, "MIL", "WHU"))
    aliases: AliasMap = {}
    assert match_event(event, index, aliases) is True
    assert event.match_key == MatchKey(_DATE, "MFI2", "WHUF6")
    assert aliases["MIL"] == "MFI2"
    assert aliases["WHU"] == "WHUF6"
    assert pin_optic_abbr_codes("MIL", "WHU", _fx(), aliases) == {}
