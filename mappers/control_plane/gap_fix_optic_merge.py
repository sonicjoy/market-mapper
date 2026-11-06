"""Collapse harvest pins that share one Optic competitor id."""

from __future__ import annotations

from typing import Any

from mappers.alias_kinds import alias_value, is_optic_id
from mappers.control_plane.gap_fix_walk import remember_harvest_key

OpticDrafted = dict[tuple[str, str], str]


def optic_draft_key(drafted: OpticDrafted | None, league: str, oid: str) -> str:
    """Canonical already drafted for this league/optic id in this harvest pass."""
    if not drafted or not oid:
        return ""
    return drafted.get((league, oid), "")


def register_optic_draft(
    drafted: OpticDrafted | None,
    league: str,
    oid: str,
    key: str,
) -> None:
    """Remember one optic id → canonical for later pins in the same harvest."""
    if drafted is not None and oid and key and (league, oid) not in drafted:
        drafted[(league, oid)] = key


def seed_optic_drafts(drafted: OpticDrafted, pins: list[dict[str, Any]]) -> None:
    """Fill the map from pins already in this harvest (first canonical wins)."""
    for pin in pins:
        register_optic_draft(
            drafted,
            str(pin.get("league") or ""),
            pin_optic_id(pin),
            str(pin.get("canonical_key") or ""),
        )


def merge_pins_by_optic_id(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold duplicate Optic external_id pins onto the first canonical."""
    out: list[dict[str, Any]] = []
    leaders: dict[tuple[str, str], dict[str, Any]] = {}
    for pin in pins:
        oid = pin_optic_id(pin)
        league = str(pin.get("league") or "")
        if not oid or str(pin.get("kind") or "") != "entity_alias":
            out.append(pin)
            continue
        slot = (league, oid)
        leader = leaders.get(slot)
        if leader is None:
            leaders[slot] = pin
            out.append(pin)
            continue
        fold_pin_aliases(leader, pin)
        remember_harvest_key(leader, pin)
    return out


def pin_optic_id(pin: dict[str, Any]) -> str:
    """Optic competitor id on a harvest pin, else empty."""
    for alias in pin.get("aliases") or []:
        if is_optic_id(alias):
            return alias_value(alias)
    return ""


def fold_pin_aliases(keep: dict[str, Any], drop: dict[str, Any]) -> None:
    """Move non-Optic aliases and evidence from drop onto keep."""
    seen = {
        (
            alias.get("sportsbook"),
            alias.get("alias_kind"),
            alias.get("alias_value"),
            alias.get("remove"),
        )
        for alias in keep.get("aliases") or []
    }
    merged = [dict(alias) for alias in keep.get("aliases") or []]
    for alias in drop.get("aliases") or []:
        if is_optic_id(alias):
            continue
        key = (
            alias.get("sportsbook"),
            alias.get("alias_kind"),
            alias.get("alias_value"),
            alias.get("remove"),
        )
        if key in seen:
            continue
        merged.append(dict(alias))
        seen.add(key)
    keep["aliases"] = merged
    if drop.get("reassign"):
        keep["reassign"] = True
    refs = list(keep.get("evidence_refs") or [])
    known = set(refs)
    for ref in drop.get("evidence_refs") or []:
        text = str(ref)
        if text not in known:
            refs.append(text)
            known.add(text)
    keep["evidence_refs"] = refs
