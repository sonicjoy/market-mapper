"""Join an STX event to exactly one Optic fixture: same league set, same kickoff minute, BOTH teams, same orientation.

STX carries no Optic ids and Optic lists no STX book (2026-10-28), so the join is on three typed keys with no fuzzy
step: the competition's Optic leagues (``stx_leagues``), the exact UTC kickoff minute, and both role-tagged teams,
each landing on its own side by a pin (``stx_names``), the exact normalised name, or the exact abbreviation.

**Orientation is never flipped.** When STX's home team is Optic's away team (a neutral site: Navy v Notre Dame at
Gillette Stadium, 2026-10-31, ESPN and STX say Navy is home, Optic says Notre Dame), the event is left unmapped as
``orientation_flip``. Every spread and winner on it would otherwise price the wrong team.

Measured on Ontario demo v Optic REST v3 (2026-10-28, rule without pins): 97 of 110 game events join exactly one
fixture, 0 join two, every join at a kickoff delta of 0 minutes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from mappers.exchanges.dkex_catalogue_read import start_key
from mappers.exchanges.stx import AWAY, HOME, StxMarket, StxParticipant
from mappers.exchanges.stx_leagues import StxCompetition
from mappers.exchanges.stx_names import exact_name, pinned_id


@dataclass(frozen=True)
class OpticSide:
    """One side of an Optic fixture: competitor id(s), name, Optic abbreviation and the code rows key on."""

    id: str
    name: str
    abbr: str
    code: str
    alias_ids: frozenset[str] = field(default_factory=frozenset)

    def has_id(self, optic_id: str) -> bool:
        """True when ``optic_id`` is this side's competitor record or one folded onto it."""
        return optic_id == self.id or optic_id in self.alias_ids


@dataclass(frozen=True)
class OpticFixtureRef:
    """The Optic fixture fields the STX join reads."""

    fixture_id: str
    league_id: str
    start_date: str
    status: str
    home: OpticSide
    away: OpticSide


@dataclass(frozen=True)
class FixtureJoin:
    """One STX event's join: the fixture and how each team landed, or the reason there is none."""

    event_id: str
    fixture: OpticFixtureRef | None = None
    reason: str | None = None
    methods: tuple[str, str] = ("", "")


def _side_from_competitors(comps: Any, fallback: dict[str, Any]) -> OpticSide | None:
    first = (comps or [None])[0] if isinstance(comps, list) else None
    rec = first if isinstance(first, dict) else fallback
    if not isinstance(rec, dict) or not rec.get("id"):
        return None
    abbr = str(rec.get("abbreviation") or rec.get("abbr") or "").strip()
    return OpticSide(id=str(rec["id"]), name=str(rec.get("name") or ""), abbr=abbr, code=abbr)


def fixture_from_record(rec: dict[str, Any]) -> OpticFixtureRef | None:
    """An Optic fixture from a ``/fixtures`` record: Optic's own shape or the trimmed ``{home: {id, name, abbr}}``."""
    league = rec.get("league")
    league_id = str(league.get("id") or "") if isinstance(league, dict) else str(league or "")
    home = _side_from_competitors(rec.get("home_competitors"), rec.get("home") or {})
    away = _side_from_competitors(rec.get("away_competitors"), rec.get("away") or {})
    if not (rec.get("id") and rec.get("start_date") and home and away):
        return None
    return OpticFixtureRef(
        fixture_id=str(rec["id"]),
        league_id=league_id,
        start_date=str(rec["start_date"]),
        status=str(rec.get("status") or ""),
        home=home,
        away=away,
    )


def fixture_from_mmmapper(fx: Any) -> OpticFixtureRef:
    """An Optic fixture from the pipeline's ``optic.Fixture``: codes and folded ids come from its ``team_map``."""

    def side(code: str, name: str, abbr: str) -> OpticSide:
        ids = sorted(i for i, c in fx.team_map.items() if c == code)
        return OpticSide(
            id=ids[0] if ids else "", name=name, abbr=abbr or code, code=code, alias_ids=frozenset(ids[1:])
        )

    return OpticFixtureRef(
        fixture_id=fx.fixture_id,
        league_id=fx.league_id,
        start_date=fx.start_date,
        status="live" if fx.is_live else "unplayed",
        home=side(fx.home, fx.home_name, fx.home_optic_abbr),
        away=side(fx.away, fx.away_name, fx.away_optic_abbr),
    )


def index_fixtures(fixtures: Iterable[OpticFixtureRef]) -> dict[tuple[str, str], list[OpticFixtureRef]]:
    """``{(Optic league id, UTC kickoff minute): fixtures}``."""
    idx: dict[tuple[str, str], list[OpticFixtureRef]] = defaultdict(list)
    for fx in fixtures:
        if key := start_key(fx.start_date):
            idx[(fx.league_id, key)].append(fx)
    return idx


def lands(
    team: StxParticipant, side: OpticSide, competition: str, pins: dict[tuple[str, str], str] | None = None
) -> str | None:
    """How an STX team lands on an Optic side (``pin`` / ``name`` / ``abbr``), or None.

    A pinned team lands ONLY on its pinned id: the name rules are not consulted, so a pin can never be overridden by a
    coincidental abbreviation.
    """
    pinned = pinned_id(competition, team.name, pins)
    if pinned is not None:
        return "pin" if side.has_id(pinned) else None
    if exact_name(team.name) and exact_name(team.name) == exact_name(side.name):
        return "name"
    if team.abbreviation and side.abbr and team.abbreviation.upper() == side.abbr.upper():
        return "abbr"
    return None


def _unresolved(
    home: StxParticipant,
    away: StxParticipant,
    cands: list[OpticFixtureRef],
    comp: StxCompetition,
    pins: dict[tuple[str, str], str] | None,
) -> str:
    for fx in cands:
        h, a = lands(home, fx.home, comp.name, pins), lands(away, fx.away, comp.name, pins)
        if h and not a:
            return (
                f"team_unresolved: away {away.name!r} ({away.abbreviation}) v Optic {fx.away.name!r} "
                f"({fx.away.abbr}) on {fx.fixture_id}"
            )
        if a and not h:
            return (
                f"team_unresolved: home {home.name!r} ({home.abbreviation}) v Optic {fx.home.name!r} "
                f"({fx.home.abbr}) on {fx.fixture_id}"
            )
    return f"no_team_lands: neither STX team lands on the {len(cands)} Optic fixture(s) at the kickoff"


def join_event(
    event_id: str,
    home: StxParticipant,
    away: StxParticipant,
    start: str,
    comp: StxCompetition,
    index: dict[tuple[str, str], list[OpticFixtureRef]],
    pins: dict[tuple[str, str], str] | None = None,
) -> FixtureJoin:
    """The Optic fixture this STX event is, or why none qualifies (``no_fixture``, ``orientation_flip``, ...)."""
    minute = start_key(start)
    cands = [fx for league in comp.optic_leagues for fx in index.get((league, minute), [])]
    if not cands:
        return FixtureJoin(
            event_id,
            reason=f"no_fixture: no Optic fixture in {'/'.join(comp.optic_leagues) or '-'} at {minute or start}",
        )
    straight: list[tuple[OpticFixtureRef, tuple[str, str]]] = []
    for fx in cands:
        h, a = lands(home, fx.home, comp.name, pins), lands(away, fx.away, comp.name, pins)
        if h and a:
            straight.append((fx, (h, a)))
    flipped = [fx for fx in cands if lands(home, fx.away, comp.name, pins) and lands(away, fx.home, comp.name, pins)]
    if flipped:
        return FixtureJoin(
            event_id,
            reason=f"orientation_flip: STX home {home.name!r} is Optic away on {flipped[0].fixture_id}; never flipped",
        )
    if len(straight) > 1:
        return FixtureJoin(event_id, reason=f"ambiguous_fixture: {len(straight)} fixtures at {minute}")
    if straight:
        fx, methods = straight[0]
        return FixtureJoin(event_id, fixture=fx, methods=methods)
    return FixtureJoin(event_id, reason=_unresolved(home, away, cands, comp, pins))


def join_market_event(
    m: StxMarket,
    comp: StxCompetition,
    index: dict[tuple[str, str], list[OpticFixtureRef]],
    pins: dict[tuple[str, str], str] | None = None,
) -> FixtureJoin:
    """:func:`join_event` for the event a market belongs to (its participants are the event's)."""
    home, away = m.participant(HOME), m.participant(AWAY)
    if home is None or away is None:
        return FixtureJoin(m.event_id, reason="not_a_game: no home / away participants")
    return join_event(m.event_id, home, away, m.event_start, comp, index, pins)
