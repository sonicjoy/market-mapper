"""Seed Kalshi team codes onto polymarket_usa entity aliases.

Polymarket US is unrelated to Polymarket: its market vocabulary is the
gateway enum table (``mappers.vocab.poly_usa_smt``), so no Polymarket kind
rule is ever copied onto it. Only team codes are seeded here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK, leagues_with_poly_usa

_KALSHI_BOOK = "kalshi"
_CODE_KIND = "code"


def _alias_triple(alias: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(alias.get("sportsbook") or ""),
        str(alias.get("alias_kind") or ""),
        str(alias.get("alias_value") or "").strip(),
    )


def _alias_live(alias: dict[str, Any]) -> bool:
    return alias.get("enabled", True) is not False and bool(_alias_triple(alias)[2])


def _kalshi_code_owners(
    entities: list[EntityRow],
    usa_leagues: frozenset[str],
) -> dict[tuple[str, str], list[str]]:
    """(league, kalshi code) → canonical keys that claim it."""
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ent in entities:
        if ent.league not in usa_leagues or not ent.enabled or ent.tombstone:
            continue
        for alias in ent.aliases:
            if not _alias_live(alias):
                continue
            sportsbook, kind, value = _alias_triple(alias)
            if sportsbook != _KALSHI_BOOK or kind != _CODE_KIND:
                continue
            keys = owners[(ent.league, value)]
            if ent.canonical_key not in keys:
                keys.append(ent.canonical_key)
    return owners


def _usa_code_values(ent: EntityRow) -> set[str]:
    return {
        value
        for sportsbook, kind, value in (_alias_triple(a) for a in ent.aliases)
        if sportsbook == POLY_USA_BOOK and kind == _CODE_KIND and value
    }


def _usa_pin_from_kalshi(alias: dict[str, Any], value: str) -> AliasPin:
    did = alias.get("disambiguation_id")
    dname = alias.get("disambiguation_name")
    return AliasPin(
        sportsbook=POLY_USA_BOOK,
        alias_kind=_CODE_KIND,
        alias_value=value,
        disambiguation_id=str(did) if did else None,
        disambiguation_name=str(dname) if dname else None,
    )


def _kalshi_pins_for_entity(
    ent: EntityRow,
    owners: dict[tuple[str, str], list[str]],
) -> list[AliasPin]:
    have_usa = _usa_code_values(ent)
    pins: list[AliasPin] = []
    seen: set[str] = set()
    for alias in ent.aliases:
        if not _alias_live(alias):
            continue
        sportsbook, kind, value = _alias_triple(alias)
        if sportsbook != _KALSHI_BOOK or kind != _CODE_KIND:
            continue
        if value in have_usa or value in seen:
            continue
        if len(owners.get((ent.league, value), ())) != 1:
            continue
        seen.add(value)
        pins.append(_usa_pin_from_kalshi(alias, value))
    return pins


def copy_kalshi_code_payloads(
    entities: list[EntityRow],
    usa_leagues: frozenset[str],
) -> list[EntityAliasPayload]:
    """Unambiguous Kalshi ticker codes not yet pinned as polymarket_usa codes.

    Codes claimed by more than one canonical in the league stay on Kalshi
    fallback — copying them would fail alias dry-run as an undisambiguated
    multimap.
    """
    owners = _kalshi_code_owners(entities, usa_leagues)
    out: list[EntityAliasPayload] = []
    for ent in entities:
        if ent.league not in usa_leagues or not ent.enabled or ent.tombstone:
            continue
        pins = _kalshi_pins_for_entity(ent, owners)
        if not pins:
            continue
        et = ent.entity_type if ent.entity_type in ("team", "player", "fighter") else "team"
        out.append(
            EntityAliasPayload(
                league=ent.league,
                canonical_key=ent.canonical_key,
                entity_type=et,
                canonical_name=ent.canonical_name,
                aliases=pins,
            )
        )
    out.sort(key=lambda p: (p.league, p.entity_type, p.canonical_key))
    return out


def build_usa_taxonomy_payload(
    leagues: list[LeagueRow],
    entities: list[EntityRow],
    rules: list[MarketRuleRow],
) -> BatchChangesPayload:
    """Batch of Kalshi-seeded US team codes (``rules`` is unused)."""
    _ = rules
    usa_leagues = leagues_with_poly_usa(leagues)
    entity_aliases = copy_kalshi_code_payloads(entities, usa_leagues)
    if not entity_aliases:
        raise RuntimeError(
            "no polymarket_usa taxonomy updates needed — Kalshi codes "
            "already copied",
        )
    return BatchChangesPayload(entity_aliases=entity_aliases)
