"""Pending alias confirm handlers for Mapper Chat."""

from __future__ import annotations

from mappers.control_plane.chat_confirm_words import is_select, is_yes, select_id
from mappers.control_plane.chat_console import show_on_console
from mappers.control_plane.chat_pending import (
    PendingAlias,
    get_pending,
    set_pending,
    staged_cart_items,
)
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.models import ChatReplyButton, ChatResponse


def handle_alias_confirm(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
) -> ChatResponse | None:
    """User confirmed pending suggestion(s) → cart_add ui_actions."""
    pending = get_pending(bag)
    if not isinstance(pending, PendingAlias):
        return None
    if is_select(message):
        return _select_card(pending, select_id(message), bag, conversation_id)
    if not is_yes(message):
        return None
    items = list(pending.cart_items)
    if not items:
        return ChatResponse(
            reply_markdown="Nothing pending to add — ask for an alias pin first.",
            conversation_id=conversation_id,
        )
    set_pending(bag, None)
    return ChatResponse(
        reply_markdown=f"Added {len(items)} alias item(s) to the cart.",
        conversation_id=conversation_id,
        ui_actions=[{"type": "cart_add", "items": items}],
    )


def _alias_prefill(payload: dict) -> dict:
    aliases = payload.get("aliases") or []
    first = aliases[0] if aliases else {}
    return {
        "tab": "alias",
        "league": payload.get("league"),
        "sportsbook": first.get("sportsbook", "optic"),
        "code": first.get("alias_value", ""),
        "entity_name": payload.get("canonical_name") or "",
        "entity_type": payload.get("entity_type") or "team",
        "canonical_key": payload.get("canonical_key") or "",
        "alias_kind": first.get("alias_kind") or "optic_id",
        "note": "From Mapper Chat suggest",
    }


def _select_card(
    pending: PendingAlias,
    sid: str,
    bag: ChatSession,
    conversation_id: str,
) -> ChatResponse:
    suggestions = pending.suggestions
    suggestion = suggestions.get(sid)
    if not suggestion:
        lowered = {k.lower(): v for k, v in suggestions.items()}
        suggestion = lowered.get(sid.lower())
    if not suggestion:
        return ChatResponse(
            reply_markdown="That suggestion expired — ask again.",
            conversation_id=conversation_id,
        )
    payload = dict(suggestion.get("payload") or {})
    prefill = _alias_prefill(payload)
    item = {
        "kind": "entity_alias",
        "label": suggestion.get("label") or sid,
        "payload": payload,
    }
    set_pending(
        bag,
        PendingAlias(
            suggestions=suggestions,
            cart_items=[*staged_cart_items(bag), item],
            prefill=prefill,
            league=pending.league,
        ),
    )
    return ChatResponse(
        reply_markdown=f"Prefilling **{item['label']}**. Add to cart?",
        conversation_id=conversation_id,
        reply_buttons=[
            ChatReplyButton(id="yes", label="Yes, add to cart", send="yes"),
            ChatReplyButton(id="no", label="Not now", send="no"),
        ],
        ui_actions=show_on_console(navigate="/entry", tab="alias", prefill=prefill),
    )
