"""Regression: catalogue listed in the opposite order to Optic (2026-09-30).

mmmapper 1f843ccc let ``pair_fits`` accept either orientation, and
``aligned_pairs`` read that as "direct", so every reversed listing pinned
each competitor to its opponent — crypto.com UFC and PX both priced the
customer's favourite as the underdog.
"""

from __future__ import annotations

from mappers.crypto_id_name_bind import pin_crypto_ids_from_selections
from mappers.exchanges import px
from mappers.exchanges.crypto_com import Selection
from mappers.exchanges.crypto_name_guard import participant_contradicts_side
from mappers.exchanges.optic import Fixture
from mappers.pipeline import ScheduleEntry
from mappers.px_name_bind import NamedSide, aligned_pairs, pin_px_name_miss
from mappers.shared import AliasValue, MatchKey

_DATE = "2026-10-03"


def test_aligned_pairs_reversed_fighters_pair_by_name() -> None:
    pairs = aligned_pairs(
        NamedSide("CID_WHITEHEAD", "Bruce Whitehead"),
        NamedSide("CID_SMITH", "Jacobe Smith"),
        NamedSide("JSA2", "Jacobe Smith"),
        NamedSide("BWR9", "Bruce Whitehead"),
        player=True,
    )
    assert pairs is not None
    assert {(c.abbr, o.abbr) for c, o in pairs} == {
        ("CID_WHITEHEAD", "BWR9"), ("CID_SMITH", "JSA2"),
    }


def test_aligned_pairs_direct_order_unchanged() -> None:
    pairs = aligned_pairs(
        NamedSide("CID_SMITH", "Jacobe Smith"),
        NamedSide("CID_WHITEHEAD", "Bruce Whitehead"),
        NamedSide("JSA2", "Jacobe Smith"),
        NamedSide("BWR9", "Bruce Whitehead"),
        player=True,
    )
    assert pairs == [
        (NamedSide("CID_SMITH", "Jacobe Smith"), NamedSide("JSA2", "Jacobe Smith")),
        (NamedSide("CID_WHITEHEAD", "Bruce Whitehead"), NamedSide("BWR9", "Bruce Whitehead")),
    ]


def test_aligned_pairs_refuses_when_both_orientations_fit() -> None:
    """Identical labels on both sides give no orientation — never guess."""
    assert aligned_pairs(
        NamedSide("A", "Silva"),
        NamedSide("B", "Silva"),
        NamedSide("X", "Silva"),
        NamedSide("Y", "Silva"),
        player=True,
    ) is None


def test_aligned_pairs_refuses_when_neither_orientation_fits() -> None:
    assert aligned_pairs(
        NamedSide("A", "Jacobe Smith"),
        NamedSide("B", "Bruce Whitehead"),
        NamedSide("X", "Court McGee"),
        NamedSide("Y", "Eric Nolan"),
        player=True,
    ) is None


def _px_event(home: tuple[str, str], away: tuple[str, str]) -> px.ParsedEvent:
    raw = px.Event(
        event_id=1,
        status="not_started",
        scheduled=f"{_DATE}T16:30:00Z",
        sport_name="Soccer",
        tournament_id=1,
        tournament_name="EPL",
        competitors=[
            px.Competitor(id=1, abbreviation=home[0], name=home[1], side="home"),
            px.Competitor(id=2, abbreviation=away[0], name=away[1], side="away"),
        ],
    )
    return px.ParsedEvent(raw=raw, match_key=MatchKey(_DATE, home[0], away[0]))


def _entry(home: tuple[str, str], away: tuple[str, str]) -> ScheduleEntry:
    return ScheduleEntry(Fixture(
        fixture_id="fx", game_id="g", sportradar_id=None,
        start_et=f"{_DATE}T12:30:00", start_date=f"{_DATE}T16:30:00Z",
        home=home[0], away=away[0], home_name=home[1], away_name=away[1],
        team_map={}, odds=[], is_live=False,
    ))


def test_px_reversed_club_listing_pins_each_abbr_to_itself() -> None:
    index = {MatchKey(_DATE, "LEE", "HCA7"): [_entry(("LEE", "Leeds United"), ("HCA7", "Hull City"))]}
    event = _px_event(("HUL", "Hull City"), ("LDS", "Leeds United"))
    aliases: dict[str, AliasValue] = {}
    assert pin_px_name_miss(event, index, aliases, player=False)
    assert aliases == {"HUL": "HCA7", "LDS": "LEE"}
    assert event.match_key == MatchKey(_DATE, "HCA7", "LEE")


def test_px_reversed_fighter_listing_pins_each_abbr_to_itself() -> None:
    index = {MatchKey(_DATE, "JSMI", "BWHI"): [_entry(("JSMI", "Jacobe Smith"), ("BWHI", "Bruce Whitehead"))]}
    event = _px_event(("BW", "Bruce Whitehead"), ("JS", "Jacobe Smith"))
    aliases: dict[str, AliasValue] = {}
    assert pin_px_name_miss(event, index, aliases, player=True)
    assert aliases == {"BW": "BWHI", "JS": "JSMI"}


def _ufc_fixture() -> Fixture:
    return Fixture(
        fixture_id="ufc-fx-smith", game_id="g-smith", sportradar_id=None,
        start_et=f"{_DATE}T20:00:00", start_date=f"{_DATE}T00:00:00Z",
        home="JSA2", away="BWR9",
        home_name="Jacobe Smith", away_name="Bruce Whitehead",
        team_map={"oid-js": "JSA2", "oid-bw": "BWR9"}, odds=[], is_live=False,
    )


def _reversed_selection() -> Selection:
    """crypto.com lists Whitehead as home, Optic lists Smith as home."""
    return Selection(
        security_id="1", symbol="NX.F.OPT.UFC-00008-261003-M.O.1.1.20261229",
        league="UFC", sport="MMA", start_date=f"{_DATE}T16:30:00Z",
        home_participant="Bruce Whitehead", away_participant="Jacobe Smith",
        external_home_id="CID_WHITEHEAD", external_away_id="CID_SMITH",
        external_game_id="NX.F.OPT.UFC-00008-261003", market_group="Fight Line",
        contract_type="Moneyline", period="Full Fight", outcome_type=None, value=None,
        selection_name="Jacobe Smith to win", crypto_market_id="m1",
        crypto_outcome_id="o1", participant="Jacobe Smith", player_id="CID_SMITH",
    )


def test_crypto_reversed_catalogue_pins_ids_to_same_fighter() -> None:
    index = {MatchKey(_DATE, "JSA2", "BWR9"): [ScheduleEntry(_ufc_fixture())]}
    aliases: dict[str, AliasValue] = {}
    pinned = pin_crypto_ids_from_selections(
        {"egid": [_reversed_selection()]}, index, aliases, player=True,
    )
    assert pinned == 2
    assert aliases == {"CID_SMITH": "JSA2", "CID_WHITEHEAD": "BWR9"}


_NAMES = {"home": "JSA2", "away": "BWR9", "home_name": "Jacobe Smith", "away_name": "Bruce Whitehead"}


def test_participant_guard_drops_crossed_fighter() -> None:
    assert participant_contradicts_side("Jacobe Smith", "BWR9", **_NAMES, league="ufc")


def test_participant_guard_keeps_matching_fighter() -> None:
    assert not participant_contradicts_side("Jacobe Smith", "JSA2", **_NAMES, league="ufc")


def test_participant_guard_fails_closed_for_people() -> None:
    assert participant_contradicts_side(None, "JSA2", **_NAMES, league="ufc")
    assert participant_contradicts_side("Court McGee", "JSA2", **_NAMES, league="ufc")
    assert participant_contradicts_side(
        "Jacobe Smith", "JSA2", home="JSA2", away="BWR9", home_name="", away_name="", league="ufc",
    )


def test_participant_guard_club_drops_only_contradiction() -> None:
    clubs = {"home": "FNC", "away": "BIG", "home_name": "Fnatic", "away_name": "BIG"}
    assert participant_contradicts_side("Fnatic", "BIG", **clubs, league="cs2")
    assert not participant_contradicts_side("Fnatic", "FNC", **clubs, league="cs2")
    assert not participant_contradicts_side("Miami (OH)", "FNC", **clubs, league="cs2")
    assert not participant_contradicts_side(None, "FNC", **clubs, league="cs2")
