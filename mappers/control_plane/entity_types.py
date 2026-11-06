"""Match-side entity_type (home/away), not player-prop aliases.

Tennis competitors are people, but classify inverts match aliases from the
``team`` bucket. ``player`` is the props table. Traders do not pick this.
"""

from __future__ import annotations

from typing import Any

from mappers.seed.league_meta import invert_entity_type, league_settings_from_row

_FIGHTER = ("ufc", "boxing", "mma")
_MATCH = frozenset({"team", "fighter"})


def match_entity_type(league: str, *, sport: str = "", settings_type: str = "") -> str:
    """Entity type for a fixture side. Ignores ``player`` on league settings."""
    raw = (settings_type or "").strip().lower()
    if raw in _MATCH:
        return raw
    needle = f"{league} {sport}".lower()
    if any(token in needle for token in _FIGHTER):
        return "fighter"
    return "team"


def match_entity_type_for_row(row: Any) -> str:
    """Match-side type from a tip league row."""
    settings = league_settings_from_row(row) if row is not None else {}
    league = str(getattr(row, "league", "") or "") if row is not None else ""
    return invert_entity_type(league, settings)


def match_entity_type_for_league(store: Any, league: str) -> str:
    """Match-side type from the activated tip, else league-name fallback."""
    if store is None:
        return match_entity_type(league)
    rid = getattr(store, "current_rule_set_id", None)
    leagues_for = getattr(store, "leagues_for", None)
    if not rid or leagues_for is None:
        return match_entity_type(league)
    for lg in leagues_for(rid):
        if lg.league == league and not getattr(lg, "tombstone", False):
            return match_entity_type_for_row(lg)
    return match_entity_type(league)


def match_entity_type_for_pin(
    store: Any,
    league: str,
    key: str = "",
) -> str:
    """Reuse an existing canonical's type; else the league match-side default."""
    if store is not None and key:
        from mappers.control_plane.gap_fix_keys import entity_type_for

        got = entity_type_for(store, league, key)
        if got:
            return got
    return match_entity_type_for_league(store, league)
