"""Stamp a DKEX catalogue onto Optic rows for one league.

Identity is typed end to end:

* **fixture** -- a competition's start time (exact UTC minute, then the
  UTC day, unique match only) plus the two teams DKEX tags ``role``
  home / away, each run through ``team_side`` (plus the DKEX city
  abbreviation rule in ``dkex_names``) against the Optic fixture, or for
  tennis and UFC through ``person_side_for``.  Both names must land, on
  different sides.
* **team** -- a market's ``parameters.participant`` id -> the event
  participant with that id -> the fixture side its name matched.
* **player** -- the participant's name, ``names_fit`` against the
  fixture's Optic player selections; exactly one hit or nothing.

An entity that does not resolve drops its whole market, never one side.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mappers.exchanges import dkex
from mappers.exchanges.dkex import DkexConfig, DkexMarket
from mappers.exchanges.dkex_catalogue_read import (
    DkexEvent,
    DkexTally,
    read_catalogue,
    start_key,
)
from mappers.exchanges.dkex_names import (
    optic_id_side,
    person_side_for,
    team_side_for,
)
from mappers.exchanges.dkex_near_start import near_start_fixture
from mappers.exchanges.dkex_players import PlayerPool
from mappers.market_types import Scope
from mappers.shared import CanonicalRow

Attach = Callable[..., str]

# Tests import the private alias from this module.
_start_key = start_key


def _fixture_index(entries: list) -> tuple[dict[str, list], dict[str, list]]:
    """Index this run fixtures by UTC minute and calendar day."""
    by_start: dict[str, list] = {}
    by_day: dict[str, list] = {}
    for entry in entries:
        key = start_key(entry.fixture.start_date)
        if not key:
            continue
        by_start.setdefault(key, []).append(entry)
        by_day.setdefault(key[:10], []).append(entry)
    return by_start, by_day


def _side_for(
    name: str, fx: Any, *,
    club_short: bool = False, person: bool = False,
) -> str | None:
    """Fixture side (``fx.home`` / ``fx.away``) a DKEX team name names, or None.

    A code pin (``OPTIC_IDS_BY_DKEX_NAME``, by Optic competitor id) is
    tried first; the raw name goes through the shared matcher either
    way, and a pin and the name must not disagree.
    """
    home, away = str(fx.home), str(fx.away)
    names = {"home": home, "away": away,
             "home_name": fx.home_name, "away_name": fx.away_name}

    def fit(claimed: str) -> str | None:
        if person:
            return person_side_for(claimed, **names)
        return team_side_for(claimed, **names, club_short=club_short)

    by_name = fit(name)
    by_id = optic_id_side(name, getattr(fx, "team_map", None) or {})
    if by_id is not None:
        return by_id if by_name in (None, by_id) else None
    return by_name


def _fixture_sides(
    event: DkexEvent, fx: Any, *,
    club_short: bool = False, person: bool = False,
) -> dict[str, str] | None:
    """{participant id -> fixture side} when both event teams land on ``fx``."""
    home, away = event.home, event.away
    if home is None or away is None:
        return None
    home_side = _side_for(home.name, fx, club_short=club_short, person=person)
    away_side = _side_for(away.name, fx, club_short=club_short, person=person)
    if home_side is None or away_side is None or home_side == away_side:
        return None
    return {home.id: home_side, away.id: away_side}


def _resolve_fixture(
    event: DkexEvent, candidates: list, *,
    club_short: bool = False, person: bool = False,
) -> tuple[Any, dict[str, str]] | None:
    """The one candidate fixture both event teams name, or None."""
    hits: list[tuple[Any, dict[str, str]]] = []
    for entry in candidates:
        sides = _fixture_sides(
            event, entry.fixture, club_short=club_short, person=person)
        if sides is not None:
            hits.append((entry, sides))
    if len(hits) != 1:
        return None
    return hits[0]


def _anchored_fixture(
    event: DkexEvent, candidates: list, *,
    club_short: bool = False, person: bool = False,
) -> tuple[Any, dict[str, str]] | None:
    """The one same-minute fixture exactly one event team names, the other team its opponent.

    For a club DKEX names by a place or short form no rule reaches
    (``Sporting Lisbon`` for ``Sporting Clube de Portugal``): when the
    other team lands on the opposite side it is a plain match, and when it
    lands nowhere it is the side left over.  Exactly one fixture may qualify.
    """
    home, away = event.home, event.away
    if home is None or away is None:
        return None
    hits: list[tuple[Any, dict[str, str]]] = []
    for entry in candidates:
        fx = entry.fixture
        h = _side_for(home.name, fx, club_short=club_short, person=person)
        a = _side_for(away.name, fx, club_short=club_short, person=person)
        if (h is None) == (a is None):
            continue
        anchor, anchor_side = (home, h) if h is not None else (away, a)
        if anchor_side is None:
            continue
        other = away if anchor is home else home
        opposite = str(fx.away) if anchor_side == str(fx.home) else str(fx.home)
        hits.append((entry, {anchor.id: anchor_side, other.id: opposite}))
    return hits[0] if len(hits) == 1 else None


def _match_event(
    event: DkexEvent,
    by_start: dict[str, list],
    by_day: dict[str, list],
    *,
    club_short: bool = False,
    person: bool = False,
) -> tuple[Any, dict[str, str]] | None:
    """Resolve a DKEX event to an Optic fixture: every exact minute, then the day.

    The day fallback exists because DKEX carries placeholder kickoffs
    (16:00 UTC) for TBD college games and flexed NFL games; it accepts
    only a unique match.
    """
    for minute_key in sorted(event.starts):
        resolved = _resolve_fixture(
            event, by_start.get(minute_key, []),
            club_short=club_short, person=person)
        if resolved is not None:
            return resolved
        resolved = _anchored_fixture(
            event, by_start.get(minute_key, []),
            club_short=club_short, person=person)
        if resolved is not None:
            return resolved
    for day_key in sorted({s[:10] for s in event.starts}):
        resolved = _resolve_fixture(
            event, by_day.get(day_key, []),
            club_short=club_short, person=person)
        if resolved is not None:
            return resolved
    if person:
        # Two named competitors identify a bout or match; the day DKEX lists
        # can sit a day off Optic's (late kickoffs, UTC rollover).
        for day_key in sorted({s[:10] for s in event.starts}):
            for shift in (-1, 1):
                near = (date.fromisoformat(day_key) + timedelta(days=shift)).isoformat()
                resolved = _resolve_fixture(
                    event, by_day.get(near, []), club_short=club_short, person=person)
                if resolved is not None:
                    return resolved
    return near_start_fixture(event, by_day, lambda fx: _fixture_sides(
        event, fx, club_short=club_short, person=person))


def _entities(
    m: DkexMarket, scope: Scope, sides: dict[str, str], players: PlayerPool,
) -> tuple[str | None, str | None]:
    """(team side, player) for one market from its typed participant."""
    part = m.participant
    if part is None:
        # "No Goalscorer" is a player-scope contract with no participant.
        if scope is Scope.PLAYER and m.name.lower().startswith("no "):
            return None, players.resolve(f"label:{m.name}", m.name)
        return None, None
    if scope is Scope.PLAYER:
        return None, players.resolve(part.id, part.name)
    return sides.get(part.id), None


def _stamp_market(
    m: DkexMarket,
    *,
    dcfg: DkexConfig,
    league_slug: str,
    fx: Any,
    sides: dict[str, str],
    players: PlayerPool,
    row_index: dict[tuple, CanonicalRow],
    alt_dkex: dict[tuple[tuple, str], CanonicalRow],
    all_rows: list[CanonicalRow],
    tally: DkexTally,
    unmapped_markets: set[str],
    attach: Attach,
) -> None:
    """Build and attach rows for one DKEX market."""
    mt = dcfg.market_type(m)
    if mt is None:
        if not dcfg.deliberately_unmapped(m):
            unmapped_markets.add(f"{m.market}/{m.period}")
        return
    team, player = _entities(m, mt.scope, sides, players)
    rows = dkex.build_rows(
        m,
        mt,
        line=dcfg.line_for(m),
        home=fx.home,
        away=fx.away,
        start_date=fx.start_date,
        league=league_slug,
        team=team,
        player=player,
    )
    if not rows:
        tally.unbuildable += 1
        return
    for dr in rows:
        outcome = attach(row_index, alt_dkex, all_rows, dr)
        if outcome == "stamped":
            tally.stamped += 1
        elif outcome == "satellite":
            tally.satellites += 1
        elif outcome == "duplicate":
            tally.duplicates += 1
        else:
            tally.dropped_no_optic += 1


def _report(league_slug: str, tally: DkexTally, unmapped_markets: set[str]) -> None:
    """Emit per-league stderr summary for the DKEX pass."""
    if unmapped_markets:
        print(
            f"  dkex [{league_slug}]: unmapped market(s) "
            f"{', '.join(sorted(unmapped_markets))} -- add to market_types "
            f"or ignored_markets",
            file=sys.stderr,
        )
    print(
        f"  dkex [{league_slug}]: {tally.matched_events}/{tally.events} "
        f"events matched ({tally.swapped_events} with DKEX home/away "
        f"opposite Optic), {tally.stamped} stamped, {tally.satellites} "
        f"satellite tickers, {tally.dropped_no_optic} dropped (optic didn't "
        f"price), {tally.no_fixture} no fixture, {tally.no_roles} no "
        f"home/away roles, {tally.unbuildable} unbuildable, "
        f"{tally.duplicates} duplicate, {tally.combos} combos, "
        f"{tally.not_open} not open, {tally.untyped} untyped, "
        f"{tally.unreadable} unreadable, {tally.other_league} other league, "
        f"{tally.ignored_only} ignored-only",
        file=sys.stderr,
    )


def _fixture_players(
    event: DkexEvent, fx: Any, dcfg: DkexConfig, league_slug: str,
) -> PlayerPool:
    """The fixture's player pool, with participants that share a player dropped."""
    players = PlayerPool(fx)
    participants = {
        m.participant.id: m.participant.name
        for m in event.markets
        if m.participant is not None and (mt := dcfg.market_type(m)) is not None
        and mt.scope is Scope.PLAYER
    }
    for player, names in players.drop_collisions(participants):
        print(f"  dkex [{league_slug}]: {names} all resolve to {player!r}; dropped",
              file=sys.stderr)
    return players


def _process_one_event(
    event: DkexEvent,
    *,
    dcfg: DkexConfig,
    league_slug: str,
    by_start: dict[str, list],
    by_day: dict[str, list],
    row_index: dict[tuple, CanonicalRow],
    alt_dkex: dict[tuple[tuple, str], CanonicalRow],
    all_rows: list[CanonicalRow],
    tally: DkexTally,
    unmapped_markets: set[str],
    attach: Attach,
) -> None:
    """Match and stamp one DKEX competition."""
    mappable = [m for m in event.markets if dcfg.market_type(m) is not None]
    if not mappable:
        tally.ignored_only += len(event.markets)
        return
    if not event.has_roles():
        tally.no_roles += len(mappable)
        return
    resolved = (
        _match_event(event, by_start, by_day,
                     club_short=dcfg.club_short_names, person=dcfg.person_names)
        if event.starts else None
    )
    if resolved is None:
        tally.no_fixture += len(mappable)
        return
    entry, sides = resolved
    fx = entry.fixture
    tally.matched_events += 1
    home = event.home
    if home is not None and sides.get(home.id) == str(fx.away):
        tally.swapped_events += 1
    players = _fixture_players(event, fx, dcfg, league_slug)
    for m in event.markets:
        _stamp_market(
            m, dcfg=dcfg, league_slug=league_slug, fx=fx, sides=sides,
            players=players, row_index=row_index, alt_dkex=alt_dkex,
            all_rows=all_rows, tally=tally,
            unmapped_markets=unmapped_markets, attach=attach,
        )


def run_pass(
    league_slug: str,
    dcfg: DkexConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    data_dir: Path,
    attach: Attach,
) -> DkexTally:
    """Match one league's DKEX catalogue onto this run's optic rows."""
    tally = DkexTally()
    events = read_catalogue(data_dir, dcfg, tally)
    if not events:
        print(f"  dkex [{league_slug}]: no catalogue rows", file=sys.stderr)
        return tally
    tally.events = len(events)
    by_start, by_day = _fixture_index(entries)
    alt_dkex: dict[tuple[tuple, str], CanonicalRow] = {}
    unmapped_markets: set[str] = set()
    for event in events.values():
        _process_one_event(
            event, dcfg=dcfg, league_slug=league_slug, by_start=by_start,
            by_day=by_day, row_index=row_index,
            alt_dkex=alt_dkex, all_rows=all_rows, tally=tally,
            unmapped_markets=unmapped_markets, attach=attach,
        )
    _report(league_slug, tally, unmapped_markets)
    return tally
