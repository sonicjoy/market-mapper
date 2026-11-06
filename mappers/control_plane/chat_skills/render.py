"""Shared Mapper Chat reply helpers (cart offer, Editor prefill)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_cart import confirm_buttons
from mappers.control_plane.models import ChatReplyButton


def prefill_from_pin(pin: dict[str, Any], book: str, alias_kind: str) -> dict[str, Any]:
    """Entry alias-tab fields from a drafted pin."""
    alias = (pin.get("aliases") or [{}])[0]
    return {
        "tab": "alias",
        "league": pin.get("league", ""),
        "sportsbook": alias.get("sportsbook") or book,
        "code": alias.get("alias_value", ""),
        "canonical_key": pin.get("canonical_key", ""),
        "entity_name": pin.get("canonical_name", ""),
        "entity_type": pin.get("entity_type", "team"),
        "alias_kind": alias.get("alias_kind") or alias_kind,
    }


def cart_buttons(count: int) -> list[ChatReplyButton]:
    if count <= 0:
        return []
    if count == 1:
        return [
            ChatReplyButton(id="yes", label="Add to cart", send="yes"),
            ChatReplyButton(id="no", label="Not now", send="no"),
        ]
    return confirm_buttons()


def prefill_buttons() -> list[ChatReplyButton]:
    return [
        ChatReplyButton(id="prefill", label="Prefill Editor", send="prefill entry"),
        ChatReplyButton(id="no", label="Not now", send="no"),
    ]


def staged_note(count: int) -> str:
    if count <= 1:
        return "\nStaged alias pin — Editor is prefilled. Add to cart?"
    return f"\nStaged {count} alias pins — Editor is prefilled with the first. Add all to cart?"
