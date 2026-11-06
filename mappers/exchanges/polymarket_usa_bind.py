"""Read the Polymarket US id off an Optic ``Polymarket (USA)`` source_ids blob.

Binding and verification live in ``polymarket_usa_structured`` (typed
gateway fields); this module only normalises the id Optic carries.
"""

from __future__ import annotations


def usa_market_id(src: object) -> str:
    """US id from an Optic ``Polymarket (USA)`` source_ids blob."""
    if not isinstance(src, dict):
        return ""
    for key in ("market_id", "selection_id"):
        val = str(src.get(key) or "").strip()
        if val:
            return val.casefold()
    return ""


def usa_symbol_of(src: object) -> str:
    """US symbol (opaque ``market_id``) an Optic passthrough carries; never parsed."""
    if not isinstance(src, dict):
        return ""
    val = str(src.get("market_id") or "").strip()
    return val.casefold() if val else ""
