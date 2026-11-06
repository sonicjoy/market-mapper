"""JSON-shaped entity_alias payloads for verify responses / staging cart."""

from __future__ import annotations

from typing import Any


def entity_alias_dict(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    canonical_key: str,
    canonical_name: str,
    reassign: bool,
    disambiguation_name: str | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Build a cart-ready EntityAliasPayload dict."""
    pin: dict[str, Any] = {
        "sportsbook": sportsbook,
        "alias_kind": alias_kind,
        "alias_value": alias_value,
    }
    if remove:
        pin["remove"] = True
    if disambiguation_name is not None:
        pin["disambiguation_name"] = disambiguation_name
    return {
        "kind": "entity_alias",
        "league": league,
        "canonical_key": canonical_key,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "reassign": reassign,
        "aliases": [pin],
    }


def alias_payload(
    league: str,
    canonical_key: str,
    canonical_name: str,
    entity_type: str,
    aliases: list[dict[str, Any]],
    evidence_refs: list[str],
) -> dict[str, Any]:
    """Cart-shaped entity_alias payload."""
    return {
        "kind": "entity_alias",
        "league": league,
        "canonical_key": canonical_key,
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "aliases": aliases,
        "evidence_refs": evidence_refs,
        "reassign": False,
    }
