"""Sportsbook alias kinds the legacy BQ tip invert reads (tip is retiring).

Seed writes Optic and crypto.com ids as ``external_id``
(``mappers/seed/entities.py``). Harvest used to write ``optic_id`` /
``crypto_id``, which classify ignores. Lookups accept both; new pins
write ``external_id``.
"""

from __future__ import annotations

from typing import Any

OPTIC_ID_KINDS = frozenset({"external_id", "optic_id"})
CRYPTO_ID_KINDS = frozenset({"external_id", "crypto_id"})
ID_KIND = "external_id"


def alias_value(alias: dict[str, Any]) -> str:
    """Trimmed alias_value, or empty."""
    return str(alias.get("alias_value") or "").strip()


def is_optic_id(alias: dict[str, Any], oid: str | None = None) -> bool:
    """True when this row is an Optic competitor id (optionally ``oid``)."""
    if str(alias.get("sportsbook") or "").lower() != "optic":
        return False
    if str(alias.get("alias_kind") or "") not in OPTIC_ID_KINDS:
        return False
    value = alias_value(alias)
    if not value:
        return False
    return oid is None or value == oid


def is_crypto_id(alias: dict[str, Any], cid: str | None = None) -> bool:
    """True when this row is a crypto.com security id (optionally ``cid``)."""
    if str(alias.get("sportsbook") or "").lower() != "crypto.com":
        return False
    if str(alias.get("alias_kind") or "") not in CRYPTO_ID_KINDS:
        return False
    value = alias_value(alias)
    if not value:
        return False
    return cid is None or value == cid


def optic_pin(oid: str) -> dict[str, str]:
    """Legacy tip-readable Optic competitor pin."""
    return {"sportsbook": "optic", "alias_kind": ID_KIND, "alias_value": oid}


def crypto_pin(cid: str) -> dict[str, str]:
    """Legacy tip-readable crypto.com security pin."""
    return {
        "sportsbook": "crypto.com",
        "alias_kind": ID_KIND,
        "alias_value": cid,
    }


def same_stored_id(
    sportsbook: str,
    kind: str,
    value: str,
    alias: dict[str, Any],
) -> bool:
    """True when ``alias`` is this pin, including legacy ``crypto_id`` / ``optic_id``."""
    if str(alias.get("sportsbook") or "") != sportsbook or alias_value(alias) != value:
        return False
    stored = str(alias.get("alias_kind") or "")
    if stored == kind:
        return True
    if sportsbook == "crypto.com" and stored in CRYPTO_ID_KINDS and kind in CRYPTO_ID_KINDS:
        return True
    return sportsbook == "optic" and stored in OPTIC_ID_KINDS and kind in OPTIC_ID_KINDS
