"""Bind Polymarket US player props onto Optic player entities.

The gateway names a player in ``metadata.playerName``; this finds the one
Optic entity on the same fixture it refers to, or drops the bet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mappers.canonical_codes import names_fit
from mappers.market_types import MarketType, Scope
from mappers.shared import CanonicalRow, normalize_player_name

_AnyBet = tuple[str, str | None, float | None, str] | tuple[
    str, str | None, float | None, str, str | None
]
_FixtureKey = tuple[str, str, str]
_PlayerIndex = dict[_FixtureKey, frozenset[str]]


def build_player_index(
    row_index: Mapping[tuple, CanonicalRow],
    league: str,
) -> _PlayerIndex:
    """Per-fixture Optic player entities (PLAYER scope only)."""
    raw: dict[_FixtureKey, set[str]] = {}
    for row in row_index.values():
        if row.league != league or not row.entity:
            continue
        if not _is_player(row.market_type):
            continue
        raw.setdefault((row.start_date, row.home, row.away), set()).add(row.entity)
    return {fx: frozenset(ents) for fx, ents in raw.items()}


def bind_player_entities(
    bets: Sequence[_AnyBet],
    player_index: _PlayerIndex,
    start_date: str,
    home: str,
    away: str,
) -> list[_AnyBet]:
    """Rewrite player names onto a unique Optic entity, or drop."""
    out: list[_AnyBet] = []
    fx: _FixtureKey = (start_date, home, away)
    for bet in bets:
        market_type, entity, line, side = bet[0], bet[1], bet[2], bet[3]
        grouping = bet[4] if len(bet) == 5 else None
        if not _is_player(market_type) or not entity:
            out.append(bet)
            continue
        resolved = _resolve_player(entity, player_index, fx)
        if resolved is None:
            continue
        if grouping is None and len(bet) == 4:
            out.append((market_type, resolved, line, side))
        else:
            out.append((market_type, resolved, line, side, grouping))
    return out


def _resolve_player(
    name: str,
    player_index: _PlayerIndex,
    fx: _FixtureKey,
) -> str | None:
    """The one Optic entity on this fixture the gateway ``playerName`` names.

    An entity equal to the normalised name wins outright ("Josh Allen" is
    ``josh_allen``, not also ``josh_hines-allen``); otherwise exactly one
    entity must fit, or the bet drops.
    """
    entities = player_index.get(fx, frozenset())
    exact = [e for e in entities if e == normalize_player_name(name)]
    if len(exact) == 1:
        return exact[0]
    hits = [e for e in entities if names_fit(name, e, player=True)]
    return hits[0] if len(hits) == 1 else None


def _is_player(market_type: str) -> bool:
    try:
        return MarketType(market_type).scope is Scope.PLAYER
    except ValueError:
        return False
