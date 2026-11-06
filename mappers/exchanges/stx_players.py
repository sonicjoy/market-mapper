"""STX player props: the player by exact full name, on the STX roster AND among the Optic fixture's players.

An STX prop names its player only by display name (``stat_detail.player``); the second ``specifier`` field is not the
roster id (0 of 396 found, 2026-10-28) and the market carries no team (``concepts__market-shape.md:545``). So:

1. **Roster** (``GET /api/v1/events/{id}/players``): the name must appear exactly once, on one of the event's two
   teams. No roster (NCAAF UGA v FLA had ``teams: []``) is unmapped, never guessed.
2. **Optic**: exactly one Optic ``player_id`` among the fixture's player selections has that exact normalised name.
   Last names are never enough: ATL v MIA lists Aaron Wiggins and Andrew Wiggins.

Measured on four games (NFL GB v CAR, NHL WSH v PHI, NBA ATL v MIA, NCAAF UGA v FLA): 106 of 106 STX prop players
match exactly one Optic player, 0 ambiguous; 396 of 396 prop markets on the three rostered games match one roster
name.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from mappers.exchanges.stx_names import exact_name


@dataclass(frozen=True)
class Roster:
    """An STX event roster: exact player name -> ``(team name, roster player id)`` for every listing."""

    listings: dict[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True)
class PlayerMatch:
    """A resolved prop player: the Optic id and name, and the STX roster team and id."""

    optic_player_id: str
    optic_name: str
    roster_team: str
    roster_player_id: str


def roster_from_payload(payload: dict[str, Any] | None) -> Roster | None:
    """A roster from the ``/events/{id}/players`` body; None when STX lists no team."""
    teams = (payload or {}).get("teams") or []
    listings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for team in teams:
        if not isinstance(team, dict):
            continue
        for p in team.get("players") or []:
            if isinstance(p, dict) and p.get("name"):
                listings[exact_name(p["name"])].append((str(team.get("team") or ""), str(p.get("player_id") or "")))
    return Roster({k: tuple(v) for k, v in listings.items()}) if listings else None


def optic_player_index(selections: Iterable[tuple[Any, Any]]) -> dict[str, dict[str, str]]:
    """``{exact name: {Optic player_id: Optic name}}`` from ``(player_id, selection name)`` pairs of one fixture."""
    idx: dict[str, dict[str, str]] = defaultdict(dict)
    for player_id, name in selections:
        if player_id and name:
            idx[exact_name(name)][str(player_id)] = str(name)
    return dict(idx)


def _roster_listing(name: str, roster: Roster | None, teams: tuple[str, ...]) -> tuple[str, str] | str:
    if roster is None:
        return "no_roster: STX lists no players for the event"
    listed = set(roster.listings.get(exact_name(name), ()))
    if not listed:
        return f"player_not_on_roster: {name!r}"
    if len(listed) > 1:
        return f"player_ambiguous_on_roster: {name!r} listed {len(listed)} times"
    team, roster_id = next(iter(listed))
    if exact_name(team) not in {exact_name(t) for t in teams}:
        return f"roster_team_not_in_event: {name!r} on {team!r}"
    return team, roster_id


def resolve_player(
    name: str, teams: tuple[str, ...], roster: Roster | None, optic: dict[str, dict[str, str]] | None
) -> PlayerMatch | str:
    """The Optic player an STX prop names, or the reason there is none (``"<code>: <detail>"``)."""
    listing = _roster_listing(name, roster, teams)
    if isinstance(listing, str):
        return listing
    if not optic:
        return "no_optic_players: the Optic fixture carries no player selections"
    hits = optic.get(exact_name(name), {})
    if not hits:
        return f"player_not_in_optic: {name!r}"
    if len(hits) > 1:
        return f"player_ambiguous_in_optic: {name!r} has {len(hits)} Optic ids"
    ((player_id, optic_name),) = hits.items()
    return PlayerMatch(player_id, optic_name, listing[0], listing[1])
