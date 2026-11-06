"""Thin dry-run for entity_alias proposals (resolve / collision checks)."""

from __future__ import annotations

from typing import Any

from mappers.alias_kinds import same_stored_id
from mappers.control_plane.dry_run_already import noop_blockers
from mappers.control_plane.models import AliasPin, EntityAliasPayload
from mappers.control_plane.store import EntityRow


def _copy_entities(entities: list[EntityRow]) -> list[EntityRow]:
    """Shallow-structure copy of entity rows."""
    return [
        EntityRow(
            league=e.league,
            entity_type=e.entity_type,
            canonical_key=e.canonical_key,
            canonical_name=e.canonical_name,
            aliases=[dict(a) for a in e.aliases],
            enabled=e.enabled,
            notes=e.notes,
        )
        for e in entities
    ]


def _merge_aliases(prior: list[dict[str, Any]], pins: list[AliasPin]) -> list[dict[str, Any]]:
    """Append new pins without duplicating existing triples."""
    existing = {(a.get("sportsbook"), a.get("alias_kind"), a.get("alias_value")) for a in prior}
    merged = [dict(a) for a in prior]
    for pin in pins:
        if pin.remove:
            continue
        key = (pin.sportsbook, pin.alias_kind, pin.alias_value)
        if key in existing or any(_matches_pin(alias, pin) for alias in merged):
            continue
        merged.append(
            {
                "sportsbook": pin.sportsbook,
                "alias_kind": pin.alias_kind,
                "alias_value": pin.alias_value,
                "disambiguation_id": pin.disambiguation_id,
                "disambiguation_name": pin.disambiguation_name,
                "enabled": True,
            }
        )
    return merged


def _target_aliases(prior: list[dict[str, Any]], payload: EntityAliasPayload) -> list[dict[str, Any]]:
    """Merge add-pins, then drop remove-pins from the target entity."""
    drops = [pin for pin in payload.aliases if pin.remove]
    merged = _merge_aliases(prior, payload.aliases)
    if not drops:
        return merged
    return [alias for alias in merged if not any(_matches_pin(alias, pin) for pin in drops)]


def _matches_pin(alias: dict[str, Any], pin: AliasPin) -> bool:
    """True when a stored alias is this pin, including legacy id kinds."""
    return same_stored_id(pin.sportsbook, pin.alias_kind, pin.alias_value, alias)


def _without_pins(aliases: list[dict[str, Any]], pins: list[AliasPin]) -> list[dict[str, Any]]:
    """Drop stored aliases that are any of ``pins``."""
    return [dict(alias) for alias in aliases if not any(_matches_pin(alias, pin) for pin in pins)]


def _same_canonical(ent: EntityRow, payload: EntityAliasPayload) -> bool:
    return ent.league == payload.league and ent.canonical_key == payload.canonical_key


def _prior_entity(entities: list[EntityRow], payload: EntityAliasPayload) -> EntityRow | None:
    """Exact entity_type match, else the live row for this canonical."""
    fallback: EntityRow | None = None
    for ent in entities:
        if not _same_canonical(ent, payload):
            continue
        if ent.entity_type == payload.entity_type:
            return ent
        if fallback is None:
            fallback = ent
    return fallback


def _is_chosen(ent: EntityRow, prior: EntityRow | None) -> bool:
    if prior is None:
        return False
    return (
        ent.league == prior.league
        and ent.canonical_key == prior.canonical_key
        and ent.entity_type == prior.entity_type
    )


def _strip_pins(ent: EntityRow, pins: list[AliasPin]) -> EntityRow:
    """Copy entity without any of the proposed alias triples."""
    return EntityRow(
        league=ent.league,
        entity_type=ent.entity_type,
        canonical_key=ent.canonical_key,
        canonical_name=ent.canonical_name,
        aliases=_without_pins(ent.aliases, pins),
        enabled=ent.enabled,
        notes=ent.notes,
    )


def apply_alias_payload(
    entities: list[EntityRow],
    payload: EntityAliasPayload,
) -> list[EntityRow]:
    """Merge aliases; optionally strip other owners when payload.reassign is set."""
    # reassign=True (Rules propose-change): move alias off other owners.
    # reassign=False: keep other owners so collisions stay multimaps needing disambiguation.
    prior = _prior_entity(entities, payload)
    move = bool(payload.reassign)
    others: list[EntityRow] = []
    for ent in _copy_entities(entities):
        if _is_chosen(ent, prior):
            continue
        strip = _same_canonical(ent, payload) or (move and ent.league == payload.league)
        others.append(_strip_pins(ent, payload.aliases) if strip else ent)
    base = [dict(alias) for alias in prior.aliases] if prior else []
    name = payload.canonical_name or (prior.canonical_name if prior else None)
    others.append(
        EntityRow(
            league=payload.league,
            entity_type=prior.entity_type if prior else payload.entity_type,
            canonical_key=payload.canonical_key,
            canonical_name=name,
            aliases=_target_aliases(base, payload),
            enabled=prior.enabled if prior else True,
            notes=prior.notes if prior else None,
        )
    )
    return others


def resolve_alias(
    entities: list[EntityRow],
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
) -> list[str]:
    """Return canonical keys that claim this alias (0 / 1 / many)."""
    hits: list[str] = []
    for ent in entities:
        if ent.league != league:
            continue
        for alias in ent.aliases:
            match = alias.get("enabled", True) and same_stored_id(
                sportsbook, alias_kind, alias_value, alias,
            )
            if match and ent.canonical_key not in hits:
                hits.append(ent.canonical_key)
    return hits


def _alias_live_notes(
    entities: list[EntityRow],
    payload: EntityAliasPayload,
) -> tuple[list[str], int]:
    """Warnings and change count vs the current tip (not the patched snapshot)."""
    notes: list[str] = []
    changing = 0
    for pin in payload.aliases:
        hits = resolve_alias(
            entities,
            league=payload.league,
            sportsbook=pin.sportsbook,
            alias_kind=pin.alias_kind,
            alias_value=pin.alias_value,
        )
        live = payload.canonical_key in hits
        if pin.remove:
            changing += 1 if live else 0
            continue
        others = [hit for hit in hits if hit != payload.canonical_key]
        if live and not (payload.reassign and others):
            who = payload.canonical_name or payload.canonical_key
            notes.append(
                f"Already live: {pin.sportsbook} {pin.alias_value} already maps to {who}."
            )
        else:
            changing += 1
    return notes, changing


def _pin_check(
    patched: list[EntityRow],
    payload: EntityAliasPayload,
    pin: AliasPin,
) -> dict[str, Any]:
    """One alias pin vs the patched snapshot."""
    claimants = resolve_alias(
        patched,
        league=payload.league,
        sportsbook=pin.sportsbook,
        alias_kind=pin.alias_kind,
        alias_value=pin.alias_value,
    )
    resolves = payload.canonical_key in claimants
    ambiguous = len(claimants) > 1
    disambiguated = bool(pin.disambiguation_id or pin.disambiguation_name)
    ok = (not resolves) if pin.remove else (resolves and (not ambiguous or disambiguated))
    return {
        "alias_value": pin.alias_value,
        "sportsbook": pin.sportsbook,
        "claimants": claimants,
        "resolves_to_canonical": resolves,
        "multimap": ambiguous,
        "disambiguated": disambiguated,
        "removed": pin.remove,
        "ok": ok,
    }


def failed_dry_run_message(dry: dict[str, Any]) -> str:
    """Stable prefix plus the first blocker, for the Approve error."""
    blockers = [str(item) for item in (dry.get("blockers") or []) if item]
    if not blockers:
        return "thin dry-run failed"
    return f"thin dry-run failed: {blockers[0]}"


def _kalshi_alias_blockers(payload: EntityAliasPayload) -> list[str]:
    """Kalshi maps from its own typed fields; it takes no tip aliases.

    A remove pin stays legal so a stale Kalshi alias can still be cleaned up.
    """
    return [
        f"kalshi alias {pin.alias_value!r}: Kalshi takes no tip aliases"
        for pin in payload.aliases
        if str(pin.sportsbook or "").strip().lower() == "kalshi" and not pin.remove
    ]


def thin_dry_run(
    entities: list[EntityRow],
    payload: EntityAliasPayload,
) -> dict[str, Any]:
    """Validate each proposed alias resolves; block when every pin is already live."""
    patched = apply_alias_payload(entities, payload)
    results: list[dict[str, Any]] = []
    ok = True
    for pin in payload.aliases:
        check = _pin_check(patched, payload, pin)
        results.append(check)
        ok = ok and bool(check["ok"])
    live_notes, changing = _alias_live_notes(entities, payload)
    blockers = _kalshi_alias_blockers(payload)
    blockers.extend(noop_blockers(change_count=changing, item_count=len(payload.aliases)))
    return {
        "ok": ok and not blockers,
        "blockers": blockers,
        "warnings": live_notes,
        "alias_checks": results,
        "entity_count": len(patched),
        "change_count": changing,
        "item_count": len(payload.aliases),
    }
