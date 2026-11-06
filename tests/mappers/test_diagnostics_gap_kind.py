"""Gap-kind classification must not treat near-matches as unknown aliases."""

from __future__ import annotations

from mappers.diagnostics import no_match_detail
from mappers.exchanges.optic import Fixture
from mappers.pipeline import ScheduleEntry
from mappers.shared import MatchKey


def _entry(date: str, home: str, away: str, home_name: str, away_name: str):
    fx = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et=f"{date}T20:00:00",
        start_date=f"{date}T00:00:00Z",
        home=home,
        away=away,
        home_name=home_name,
        away_name=away_name,
        team_map={},
        odds=[],
        is_live=False,
    )
    return ScheduleEntry(fx)


def test_near_match_with_known_codes_is_not_unknown():
    """Wrong-claimant collisions (DEL→Delgadillo, real fixture is DEL3)
    still share a date with a near match; that must not flip has_unknown."""
    date = "2026-07-29"
    index = {
        MatchKey(date, "DEL3", "MEH"): [
            _entry(date, "DEL3", "MEH", "Matthew Dellavedova", "Arjun Mehrotra"),
        ],
    }
    detail, has_unknown = no_match_detail(
        index, date, away="MEH", home="DEL2",
        canonicals={"DEL2", "DEL3", "MEH"},
    )
    assert has_unknown is False
    assert "Near match" in detail


def test_truly_unknown_code_still_flags_unknown():
    date = "2026-07-29"
    index = {
        MatchKey(date, "THO", "MAK"): [
            _entry(date, "THO", "MAK", "Flynn Thomas", "Nazim Makhlouf"),
        ],
    }
    detail, has_unknown = no_match_detail(
        index, date, away="LAG", home="THO",
        canonicals={"THO", "MAK"},
    )
    assert has_unknown is True
    assert "Missing: LAG" in detail
