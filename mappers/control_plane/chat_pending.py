"""Typed pending state for Mapper Chat confirm flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mappers.control_plane.chat_session import ChatSession


@dataclass
class PendingSkill:
    skill: str
    slots: dict[str, Any] = field(default_factory=dict)
    cart_items: list[dict[str, Any]] = field(default_factory=list)
    awaiting_ignore_flip: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PendingCart:
    cart_items: list[dict[str, Any]] = field(default_factory=list)
    awaiting_ignore_flip: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PendingAlias:
    suggestions: dict[str, Any] = field(default_factory=dict)
    cart_items: list[dict[str, Any]] = field(default_factory=list)
    prefill: dict[str, Any] = field(default_factory=dict)
    league: str = ""


@dataclass
class PendingPrefill:
    prefill: dict[str, Any] = field(default_factory=dict)


Pending = PendingSkill | PendingCart | PendingAlias | PendingPrefill


def pending_from_dict(raw: dict[str, Any] | None) -> Pending | None:
    """Migrate legacy dict pending bags (tests / harness)."""
    if not raw:
        return None
    kind = str(raw.get("kind") or "")
    if kind == "skill":
        return PendingSkill(
            skill=str(raw.get("skill") or ""),
            slots=dict(raw.get("slots") or {}),
            cart_items=list(raw.get("cart_items") or []),
            awaiting_ignore_flip=list(raw.get("awaiting_ignore_flip") or []),
        )
    if kind == "mixed_cart":
        return PendingCart(
            cart_items=list(raw.get("cart_items") or []),
            awaiting_ignore_flip=list(raw.get("awaiting_ignore_flip") or []),
        )
    if kind == "entity_alias":
        return PendingAlias(
            suggestions=dict(raw.get("suggestions") or {}),
            cart_items=list(raw.get("cart_items") or []),
            prefill=dict(raw.get("prefill") or {}),
            league=str(raw.get("league") or ""),
        )
    if kind == "probe_prefill":
        return PendingPrefill(prefill=dict(raw.get("prefill") or {}))
    if raw.get("cart_items"):
        return PendingCart(cart_items=list(raw.get("cart_items") or []))
    return None


def get_pending(bag: ChatSession) -> Pending | None:
    pending = bag.pending
    if pending is None:
        return None
    if isinstance(pending, dict):
        return pending_from_dict(pending)
    return pending


def set_pending(bag: ChatSession, pending: Pending | None) -> None:
    bag.pending = pending


def staged_cart_items(bag: ChatSession) -> list[dict[str, Any]]:
    """Cart lines staged on whichever pending state holds them."""
    pending = get_pending(bag)
    if isinstance(pending, (PendingCart, PendingSkill, PendingAlias)):
        return list(pending.cart_items)
    return []
