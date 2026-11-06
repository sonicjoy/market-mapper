"""Tier-C provenance when MAPPING_SOT=bq (rule / alias ids from activated tip)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mappers.shared import CanonicalRow
from mappers.sport import Sport

if TYPE_CHECKING:
    from mappers.control_plane.rows import EntityRow
    from mappers.seed.sot import SotSnapshot


def _entity_type(slug: str, sport: Sport) -> str:
    if slug in ("ufc", "boxing_matches"):
        return "fighter"
    if sport == Sport.TENNIS:
        return "player"
    return "team"


def _alias_ids_for_canonicals(
    entities: list[EntityRow],
    *,
    league: str,
    entity_type: str,
    canonicals: set[str],
) -> list[str]:
    ids: list[str] = []
    for ent in entities:
        if (
            ent.league != league
            or ent.entity_type != entity_type
            or ent.canonical_key not in canonicals
            or not ent.enabled
            or ent.tombstone
        ):
            continue
        for alias in ent.aliases:
            if alias.get("enabled") is False:
                continue
            aid = alias.get("alias_id") or alias.get("alias_rule_id")
            if aid:
                ids.append(str(aid))
                continue
            sportsbook = alias.get("sportsbook") or ""
            kind = alias.get("alias_kind") or ""
            value = alias.get("alias_value") or ""
            if sportsbook and kind and value:
                ids.append(f"{league}:{ent.canonical_key}:{sportsbook}:{kind}")
    return sorted(set(ids))


def apply_bq_provenance(
    rows: list[CanonicalRow],
    *,
    league_slug: str,
    sport: Sport,
    snap: SotSnapshot,
) -> None:
    """Stamp entity_alias_ids from the coalesced BQ tip."""
    entity_type = _entity_type(league_slug, sport)
    for row in rows:
        canonicals = {row.home, row.away}
        if row.entity:
            canonicals.add(row.entity)
        alias_ids = _alias_ids_for_canonicals(
            snap.entities,
            league=league_slug,
            entity_type=entity_type,
            canonicals=canonicals,
        )
        if alias_ids and row.entity_alias_ids is None:
            row.entity_alias_ids = alias_ids

