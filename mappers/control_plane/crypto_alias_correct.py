"""Crypto id on the wrong Optic side: correction card, not already-mapped.

Tip ownership of each id is not a market_mapping hit. When the id sits on a
canonical other than the fixture side, draft a remove plus a reassign pin
onto the Optic owner. Same kernel for harvest and Chat.
"""

from __future__ import annotations

from typing import Any

from mappers.alias_kinds import crypto_pin
from mappers.canonical_codes import names_fit, person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.gap_fix_keys import crypto_aliases, key_for_code
from mappers.control_plane.gap_fix_name_bind import unique_side
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted
from mappers.control_plane.gap_fix_skip import partner_catalogue_label
from mappers.control_plane.gap_fix_tip import (
    TipLeagueIndex,
    indexed_has_optic,
    indexed_name,
    indexed_optic_key,
)
from mappers.px_name_bind import optic_competitor_for_catalogue_name

_WRONG = "wrong"
_OWNED = "owned"
_AMBIGUOUS = "ambiguous"


def optic_side_for_label(
    label: str,
    optic: dict[str, Any],
    league: str,
    *,
    partner_label: str = "",
) -> tuple[str, str]:
    """Map a catalogue participant onto Optic home/away by name, never index."""
    player = person_league(league)
    home = str(optic.get("home") or "")
    away = str(optic.get("away") or "")
    home_id = str(optic.get("home_id") or "")
    away_id = str(optic.get("away_id") or "")
    partner = partner_label.strip()
    if player and partner:
        hit = optic_competitor_for_catalogue_name(
            label, partner, home, away, home_id, away_id, player=True,
        )
        if hit[0]:
            return hit
    home_hit = bool(label) and names_fit(label, home, player=player)
    away_hit = bool(label) and names_fit(label, away, player=player)
    if home_hit and not away_hit:
        return home, str(optic.get("home_id") or "")
    if away_hit and not home_hit:
        return away, str(optic.get("away_id") or "")
    side = unique_side(label, home, away, person=player)
    if side == "home":
        return home, str(optic.get("home_id") or "")
    if side == "away":
        return away, str(optic.get("away_id") or "")
    return "", ""


def hold_kind(
    indexed: TipLeagueIndex,
    league: str,
    ids: list[str],
    labels: list[str],
    tip: list[dict[str, Any]],
    optic: dict[str, Any],
) -> str:
    """alias_mismatch, collision, or unmapped from Optic-side ownership."""
    by_id = {str(row.get("crypto_id") or ""): row for row in tip}
    states = [
        _side_state(
            indexed, league, label, optic, _owners(by_id, cid),
            partner_label=partner_catalogue_label(labels, label),
        )
        for cid, label in zip(ids, labels, strict=True)
    ]
    if _WRONG in states:
        return "alias_mismatch"
    if _AMBIGUOUS in states:
        return "collision"
    return "unmapped"


def pins_for_crypto_id(
    league: str,
    cid: str,
    label: str,
    optic: dict[str, Any],
    tip: dict[str, Any],
    used: set[str],
    entity_type: str,
    evidence: list[str],
    *,
    optic_drafted: OpticDrafted | None,
    indexed: TipLeagueIndex,
    partner_label: str = "",
) -> list[dict[str, Any]]:
    """Add pin, or remove-from-wrong-owner plus pin onto the Optic canonical."""
    owners = list((tip.get(cid) or {}).get("owners") or [])
    if not owners:
        pin = _add_pin(
            league, cid, label, optic, used, owners, entity_type, evidence,
            optic_drafted=optic_drafted, indexed=indexed,
            partner_label=partner_label,
        )
        return [pin] if pin else []
    return _move_pins(
        league, cid, label, optic, owners, entity_type, evidence, indexed,
        partner_label=partner_label,
    )


def _side_state(
    indexed: TipLeagueIndex,
    league: str,
    label: str,
    optic: dict[str, Any],
    owners: list[str],
    *,
    partner_label: str = "",
) -> str:
    """owned, wrong, or unknown when this id cannot be judged."""
    name, oid = optic_side_for_label(
        label, optic, league, partner_label=partner_label,
    )
    if not oid or not owners:
        return "unknown"
    keep = indexed_optic_key(indexed, oid)
    wanted = {owner.upper() for owner in owners}
    if keep:
        return _OWNED if wanted == {keep.upper()} else _WRONG
    if len(owners) != 1:
        return _AMBIGUOUS
    shown = name or label
    player = person_league(league)
    owner = owners[0]
    if names_fit(indexed_name(indexed, owner), shown, player=player):
        return _OWNED
    return "unknown"


def _owners(by_id: dict[str, Any], cid: str) -> list[str]:
    """Tip canonicals for one crypto id."""
    return [str(owner) for owner in ((by_id.get(cid) or {}).get("owners") or []) if owner]


def _add_pin(
    league: str,
    cid: str,
    label: str,
    optic: dict[str, Any],
    used: set[str],
    owners: list[str],
    entity_type: str,
    evidence: list[str],
    *,
    optic_drafted: OpticDrafted | None,
    indexed: TipLeagueIndex,
    partner_label: str = "",
) -> dict[str, Any] | None:
    """One Optic-backed crypto_id pin when the tip lacks this id."""
    name, oid = optic_side_for_label(
        label, optic, league, partner_label=partner_label,
    )
    if not name or not oid:
        return None
    key, _collide = key_for_code(
        None, league, oid, name, used, owners, optic_drafted=optic_drafted, tip=indexed,
    )
    if not key:
        return None
    include_optic = not indexed_has_optic(indexed, key, oid)
    return alias_payload(
        league, key, name, indexed.types.get(key) or entity_type,
        crypto_aliases(cid, oid, include_optic=include_optic),
        evidence,
    )


def _move_pins(
    league: str,
    cid: str,
    label: str,
    optic: dict[str, Any],
    owners: list[str],
    entity_type: str,
    evidence: list[str],
    indexed: TipLeagueIndex,
    *,
    partner_label: str = "",
) -> list[dict[str, Any]]:
    """Remove the id from other canonicals and pin it on the Optic side."""
    _name, oid = optic_side_for_label(
        label, optic, league, partner_label=partner_label,
    )
    keep = indexed_optic_key(indexed, oid) if oid else ""
    extras = [owner for owner in owners if owner.upper() != (keep or "").upper()]
    if not keep or not extras:
        return []
    keep_name = indexed_name(indexed, keep)
    note = f"note:{cid} belongs to {keep_name} ({keep})."
    refs = [*evidence, note]
    already = keep.upper() in {owner.upper() for owner in owners}
    pins = [_remove_pin(league, cid, owner, entity_type, refs, indexed) for owner in extras]
    if already:
        return pins
    for pin in pins:
        _mark_claim(pin, cid)
    claim = alias_payload(
        league, keep, keep_name, indexed.types.get(keep) or entity_type,
        [crypto_pin(cid)],
        refs,
    )
    claim["reassign"] = True
    pins.append(claim)
    return pins


def _mark_claim(pin: dict[str, Any], cid: str) -> dict[str, Any]:
    """This delete stays only when its reassign claim also survives verify."""
    pin["requires_claim"] = cid
    return pin


def _remove_pin(
    league: str,
    cid: str,
    owner: str,
    entity_type: str,
    evidence: list[str],
    indexed: TipLeagueIndex,
) -> dict[str, Any]:
    """Delete this crypto id from one wrong canonical."""
    alias: dict[str, Any] = {**crypto_pin(cid), "remove": True}
    return alias_payload(
        league, owner, indexed_name(indexed, owner),
        indexed.types.get(owner) or entity_type,
        [alias],
        evidence,
    )
