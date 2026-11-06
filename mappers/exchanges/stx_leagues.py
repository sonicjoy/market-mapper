"""Which STX competitions map, onto which Optic leagues, and which are held.

STX names a competition with a display string (``competition`` on every market: ``NFL``, ``Serie A``, ``AFC``). The
table is keyed on that string, and STX's own ``sport`` must agree with the row. A mislabelled event is caught by the
fixture join, not here: Ontario demo listed "Argentina v Colombia" under ``MLB`` / ``Baseball`` (2026-10-28); it
joins no Optic MLB fixture and stays unmapped.

Optic league ids and the measured join (2026-10-28 Ontario demo v Optic REST v3, workspace
``docs/stx/MAPPING_FEASIBILITY.md`` §2): NFL 16/16, NBA 12/12, NHL 6/6, Serie A 5/5, ISL 1/1, NCAAF 52/57, AFC 4/11,
MLB 1/2. ``slug`` is the mmmapper run-set league; None means the league is not in the run set yet, so the pipeline
fetches no Optic fixtures for it (ISL; the three AFC leagues) and onboarding it comes first.

``hold`` keeps a competition out of the mapped set while still joining its fixtures, so the join stays measured:

* AFC -- one STX bucket over three Optic leagues, club spellings differ per club (6 of 11 events failed on a name).
* MLB -- not reviewed for STX (two events on demo, one of them not an MLB game).
* Cricket -- STX events carry no ESPN link and Optic cricket coverage for these competitions is not checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from mappers.sport import Sport

#: STX ``sport`` -> mmmapper sport.
SPORT_BY_STX_SPORT: dict[str, Sport] = {
    "Football": Sport.FOOTBALL,
    "Basketball": Sport.BASKETBALL,
    "Hockey": Sport.HOCKEY,
    "Soccer": Sport.SOCCER,
    "Baseball": Sport.BASEBALL,
    "Cricket": Sport.CRICKET,
}


@dataclass(frozen=True)
class StxCompetition:
    """One STX competition: its sport, the Optic league ids its fixtures live in, and why it is held (if it is)."""

    name: str
    sport: str
    optic_leagues: tuple[str, ...]
    slug: str | None
    hold: str | None = None


COMPETITIONS: dict[str, StxCompetition] = {
    c.name: c
    for c in (
        StxCompetition("NFL", "Football", ("nfl",), "nfl"),
        StxCompetition("NCAAF", "Football", ("ncaaf",), "ncaaf"),
        StxCompetition("NBA", "Basketball", ("nba",), "nba"),
        StxCompetition("NHL", "Hockey", ("nhl",), "nhl"),
        StxCompetition("Serie A", "Soccer", ("italy_-_serie_a",), "italy_serie_a"),
        StxCompetition("ISL", "Soccer", ("india_-_super_league",), None),
        StxCompetition(
            "AFC",
            "Soccer",
            ("afc_-_champions_league", "afc_-_champions_league_2", "afc_-_challenge_league"),
            None,
            hold="competition_held: AFC club spellings differ from Optic per club; no team pins reviewed",
        ),
        StxCompetition("MLB", "Baseball", ("mlb",), "mlb", hold="competition_held: MLB not reviewed for STX"),
        StxCompetition("Ranji Trophy", "Cricket", (), None, hold="competition_held: cricket not checked against Optic"),
        StxCompetition(
            "Sheffield Shield", "Cricket", (), None, hold="competition_held: cricket not checked against Optic"
        ),
        StxCompetition(
            "The Ford Trophy", "Cricket", (), None, hold="competition_held: cricket not checked against Optic"
        ),
        StxCompetition(
            "ICC Men's Cricket World Cup League 2",
            "Cricket",
            (),
            None,
            hold="competition_held: cricket not checked against Optic",
        ),
    )
}


def competition_for(name: str, sport: str) -> StxCompetition | None:
    """The table row for an STX ``competition``; None when unlisted or when STX's ``sport`` disagrees."""
    comp = COMPETITIONS.get(name)
    return comp if comp is not None and comp.sport == sport else None


def league_label(comp: StxCompetition, optic_league: str) -> str:
    """The ``league`` column for a row: the run-set slug, else the Optic league id the fixture is in."""
    return comp.slug or optic_league
