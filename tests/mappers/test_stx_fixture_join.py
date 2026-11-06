"""STX fixture join on the 2026-10-28 capture: the measured counts, every named failure, the neutral-site guard."""

from __future__ import annotations

from collections import Counter

import pytest

from mappers.exchanges.stx import AWAY, HOME, StxParticipant
from mappers.exchanges.stx_fixtures import FixtureJoin, OpticSide, index_fixtures, join_market_event, lands
from mappers.exchanges.stx_leagues import COMPETITIONS, competition_for
from mappers.exchanges.stx_names import OPTIC_ID_BY_STX_TEAM, exact_name
from tests.mappers import _stx_capture as cap


def _events() -> dict[str, tuple]:
    """One market per joinable game event (competition with Optic leagues), as the trial selected them."""
    out: dict[str, tuple] = {}
    for m in cap.markets():
        comp = competition_for(m.competition, m.sport)
        if comp and comp.optic_leagues and m.event_type.endswith(("_game", "_match")):
            out.setdefault(m.event_id, (m, comp))
    return out


def _joins(pins: dict | None) -> dict[str, tuple]:
    idx = index_fixtures(cap.fixtures())
    return {eid: (m, comp, join_market_event(m, comp, idx, pins)) for eid, (m, comp) in _events().items()}


RULE_ONLY = {}  # no pins: the rule exactly as measured


def test_same_110_events_as_the_trial():
    assert set(_events()) == set(cap.trial_join())
    assert len(_events()) == 110


def test_rule_alone_joins_97_of_110_exactly_as_measured():
    joins = _joins(RULE_ONLY)
    joined = {eid: j.fixture.fixture_id for eid, (_, _, j) in joins.items() if j.fixture}
    assert len(joined) == 97
    for eid, trial in cap.trial_join().items():
        assert trial["joined"] == ([joined[eid]] if eid in joined else []), eid
    per_comp = Counter((comp.name, j.fixture is not None) for _, comp, j in joins.values())
    assert per_comp == Counter(
        {
            ("NFL", True): 16,
            ("NBA", True): 12,
            ("NHL", True): 6,
            ("Serie A", True): 5,
            ("ISL", True): 1,
            ("NCAAF", True): 52,
            ("NCAAF", False): 5,
            ("AFC", True): 4,
            ("AFC", False): 7,
            ("MLB", True): 1,
            ("MLB", False): 1,
        }
    )


def test_no_join_is_ambiguous_and_every_kickoff_delta_is_zero():
    for m, _, j in _joins(RULE_ONLY).values():
        assert not (j.reason or "").startswith("ambiguous_fixture")
        if j.fixture:
            assert j.fixture.start_date[:16] == m.event_start[:16]


def _reason(joins: dict, home: str) -> str:
    hits = [j.reason for m, _, j in joins.values() if m.participant(HOME).name == home]
    assert len(hits) == 1, home
    return hits[0] or ""


@pytest.mark.parametrize(
    ("home", "code"),
    [
        ("Indiana Hoosiers", "team_unresolved"),  # IU v Optic IND
        ("Boise State Broncos", "team_unresolved"),  # BOIS v Optic BSU
        ("New Mexico State Aggies", "team_unresolved"),  # away JXST v Optic JVST
        ("Navy Midshipmen", "orientation_flip"),  # neutral site: Optic has Notre Dame home
        ("Florida Atlantic Owls", "no_fixture"),  # Optic has no FAU v FIU
        ("Argentina", "no_fixture"),  # labelled MLB, not an MLB game
        ("The Cong-Viettel FC", "team_unresolved"),  # AFC spellings ...
        ("Persib Bandung", "team_unresolved"),
        ("FC Nasaf", "team_unresolved"),
        ("Al-Nahda Club", "team_unresolved"),
        ("Al-Khaldiya SC", "team_unresolved"),
        ("Tampines Rovers FC", "team_unresolved"),
        (
            "Al Jazira Club",
            "no_team_lands",
        ),  # Optic 202610288376E69B "Al-Jazira" v "Al-Muharraq": both spellings differ
    ],
)
def test_each_of_the_13_named_failures_has_its_reason(home, code):
    assert _reason(_joins(RULE_ONLY), home).split(":", 1)[0] == code


def test_neutral_site_flip_stays_unmapped_never_flipped():
    reason = _reason(_joins(None), "Navy Midshipmen")
    assert reason.startswith("orientation_flip")
    assert "202610312F495783" in reason


def test_learned_team_table_is_reproduced_with_no_conflicts():
    """Every one of the trial's 186 STX team -> Optic competitor pairs comes out of the joins; no Optic id twice."""
    landed: dict[tuple[str, str], set[str]] = {}
    for m, comp, j in _joins(RULE_ONLY).values():
        if j.fixture is None:
            continue
        for role, side in ((HOME, j.fixture.home), (AWAY, j.fixture.away)):
            landed.setdefault((comp.name, m.participant(role).name), set()).add(side.id)
    table = cap.trial_team_table()
    assert len(table) == 186
    for row in table:
        assert landed[(row["competition"], row["stx_name"])] == {row["optic"][0]["id"]}, row
    by_optic = Counter(next(iter(ids)) for ids in landed.values())
    assert max(by_optic.values()) == 1


def test_code_pins_close_the_three_ncaaf_abbreviation_variants():
    joins = _joins(None)
    assert sum(1 for _, _, j in joins.values() if j.fixture) == 100
    pinned = {
        m.participant(HOME).name: j
        for m, _, j in joins.values()
        if m.participant(HOME).name in ("Indiana Hoosiers", "Boise State Broncos", "New Mexico State Aggies")
    }
    assert {name: j.fixture.fixture_id for name, j in pinned.items()} == {
        "Indiana Hoosiers": "2026103182BC9DFC",
        "Boise State Broncos": "20261031474C54C9",
        "New Mexico State Aggies": "2026102832B7EC9F",
    }
    assert pinned["Indiana Hoosiers"].methods == ("pin", "abbr")


def test_pins_name_ncaaf_teams_only():
    assert {comp for comp, _ in OPTIC_ID_BY_STX_TEAM} == {"NCAAF"}


def test_a_pinned_team_lands_only_on_its_pinned_id():
    team = StxParticipant("Indiana Hoosiers", HOME, "IND")
    wrong = OpticSide(id="NOT-INDIANA", name="Indiana", abbr="IND", code="IND")
    right = OpticSide(id="FCDF1C894B1B", name="Indiana", abbr="IND", code="IND")
    assert lands(team, wrong, "NCAAF") is None  # name and abbreviation agree, the pin does not
    assert lands(team, right, "NCAAF") == "pin"
    assert lands(team, wrong, "NCAAF", pins={}) == "abbr"  # without the pin the abbreviation would bind it


def test_exact_name_folds_nothing_but_case_accents_and_punctuation():
    assert exact_name("A.J. Dillon") == exact_name("AJ Dillon")
    assert exact_name("St. Louis Blues") == "st louis blues"
    assert exact_name("Aaron Wiggins") != exact_name("Andrew Wiggins")
    assert exact_name("Indiana Hoosiers") != exact_name("Indiana")


def test_join_needs_both_participants():
    m = next(m for m in cap.markets() if m.rules == "superbowl_champion")
    j = join_market_event(m, COMPETITIONS["NFL"], index_fixtures(cap.fixtures()))
    assert j == FixtureJoin(m.event_id, reason="not_a_game: no home / away participants")


def test_competition_needs_matching_sport():
    assert competition_for("NFL", "Football") is COMPETITIONS["NFL"]
    assert competition_for("NFL", "Basketball") is None
    assert competition_for("Bitcoin", "Economy") is None
