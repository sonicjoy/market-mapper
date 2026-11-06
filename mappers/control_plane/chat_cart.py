"""Pending mixed cart for Mapper Chat (league + markets + aliases)."""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.chat_alias import handle_alias_confirm
from mappers.control_plane.chat_confirm_words import (
    PREFILL_SEND,
    is_no,
    is_yes,
)
from mappers.control_plane.chat_console import show_on_console
from mappers.control_plane.chat_pending import (
    PendingAlias,
    PendingCart,
    PendingPrefill,
    PendingSkill,
    get_pending,
    set_pending,
    staged_cart_items,
)
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.models import ChatReplyButton, ChatResponse

_OPTIC_SET = re.compile(
    r"(?:optic(?:\s+league)?(?:\s*(?:id|name))?|optic_league_id)"
    r"\s+(?:is|=|:)\s+[\"']?([a-z0-9][a-z0-9_-]*)",
    re.I,
)
_OPTIC_ASK = re.compile(r"\b(what'?s|what is|which)\b.{0,40}\boptic\b", re.I)


def cart_items(bag: ChatSession) -> list[dict[str, Any]]:
    """Return pending cart lines (empty if none)."""
    return staged_cart_items(bag)


def append_cart_item(bag: ChatSession, item: dict[str, Any]) -> str:
    """Stage one cart line; merge same-league rows, skip exact duplicates."""
    items = cart_items(bag)
    status = _stage_item(items, item)
    pending = get_pending(bag)
    flips: list[dict[str, Any]] = []
    if isinstance(pending, (PendingCart, PendingSkill)):
        flips = list(pending.awaiting_ignore_flip)
    set_pending(bag, PendingCart(cart_items=items, awaiting_ignore_flip=flips))
    return status


def _stage_item(items: list[dict[str, Any]], item: dict[str, Any]) -> str:
    if item.get("kind") == "mapping_league":
        return _stage_league_item(items, item)
    if any(it.get("payload") == item.get("payload") for it in items):
        return "duplicate"
    items.append(item)
    return "added"


def _stage_league_item(items: list[dict[str, Any]], item: dict[str, Any]) -> str:
    league = str((item.get("payload") or {}).get("league") or "")
    existing = next(
        (
            it
            for it in items
            if it.get("kind") == "mapping_league"
            and str((it.get("payload") or {}).get("league") or "") == league
        ),
        None,
    )
    if existing is None:
        items.append(item)
        return "added"
    changed = _merge_league_exchanges(existing["payload"], item.get("payload") or {})
    books = "+".join(sorted(_enabled_books(existing["payload"])))
    existing["label"] = f"League {league} ({books})"
    return "merged" if changed else "duplicate"


def _merge_league_exchanges(base: dict[str, Any], incoming: dict[str, Any]) -> bool:
    by_book = {str(e.get("sportsbook")): e for e in base.get("exchanges") or []}
    changed = False
    for ex in incoming.get("exchanges") or []:
        if not ex.get("enabled"):
            continue
        cur = by_book.get(str(ex.get("sportsbook")))
        if cur is None:
            base.setdefault("exchanges", []).append(dict(ex))
            changed = True
        elif not cur.get("enabled"):
            cur["enabled"] = True
            cur["source_league_id"] = cur.get("source_league_id") or ex.get("source_league_id")
            changed = True
    return changed


def _enabled_books(payload: dict[str, Any]) -> list[str]:
    return [str(e.get("sportsbook")) for e in payload.get("exchanges") or [] if e.get("enabled")]


def set_awaiting_ignores(bag: ChatSession, flips: list[dict[str, Any]]) -> None:
    items = cart_items(bag)
    set_pending(bag, PendingCart(cart_items=items, awaiting_ignore_flip=flips))


def checklist_markdown(bag: ChatSession) -> str:
    items = cart_items(bag)
    if not items:
        return "Pending cart is empty."
    lines = [f"- {it.get('label') or it.get('kind')}" for it in items]
    return f"**Pending cart ({len(items)}):**\n" + "\n".join(lines)


def confirm_buttons() -> list[ChatReplyButton]:
    return [
        ChatReplyButton(id="yes", label="Add all to cart", send="yes"),
        ChatReplyButton(id="no", label="Not now", send="no"),
    ]


def confirm_or_discard_cart(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
) -> ChatResponse | None:
    """Legacy yes/no on any pending bag that staged cart lines."""
    items = cart_items(bag)
    if not items:
        return None
    if is_no(message):
        set_pending(bag, None)
        return ChatResponse(
            reply_markdown=(
                f"Discarded {len(items)} staged line(s). Nothing was added to the cart."
            ),
            conversation_id=conversation_id,
        )
    if not is_yes(message):
        return None
    set_pending(bag, None)
    labels = "\n".join(f"- {it.get('label') or it.get('kind')}" for it in items)
    return ChatResponse(
        reply_markdown=f"Added {len(items)} item(s) to the cart:\n{labels}",
        conversation_id=conversation_id,
        ui_actions=[{"type": "cart_add", "items": items}],
    )


def handle_pending(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
    store: Any = None,
) -> ChatResponse | None:
    """Dispatch confirm/select/prefill for any pending state."""
    pending = get_pending(bag)
    if pending is None:
        return None
    league_fu = handle_pending_league_followup(
        bag=bag, conversation_id=conversation_id, message=message, store=store,
    )
    if league_fu is not None:
        return league_fu
    if isinstance(pending, PendingAlias):
        if is_no(message):
            set_pending(bag, None)
            return ChatResponse(
                reply_markdown="OK — discarded the pending alias offer.",
                conversation_id=conversation_id,
            )
        cart = confirm_or_discard_cart(
            bag=bag, conversation_id=conversation_id, message=message,
        )
        if cart is not None:
            return cart
        return handle_alias_confirm(
            bag=bag, conversation_id=conversation_id, message=message,
        )
    if isinstance(pending, PendingSkill):
        return _pending_skill_confirm(bag, conversation_id, message, pending)
    if isinstance(pending, PendingCart):
        return handle_mixed_cart_confirm(
            bag=bag, conversation_id=conversation_id, message=message,
        )
    if isinstance(pending, PendingPrefill):
        return handle_probe_prefill(
            bag=bag, conversation_id=conversation_id, message=message,
        )
    return None


def handle_probe_prefill(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
) -> ChatResponse | None:
    pending = get_pending(bag)
    if not isinstance(pending, PendingPrefill):
        return None
    text = message.strip().lower()
    if is_no(message):
        set_pending(bag, None)
        return ChatResponse(
            reply_markdown="OK — Editor was not changed.",
            conversation_id=conversation_id,
        )
    if text not in PREFILL_SEND and not is_yes(message):
        return None
    prefill = dict(pending.prefill)
    set_pending(bag, None)
    return ChatResponse(
        reply_markdown="Prefilling **Editor** for this symbol.",
        conversation_id=conversation_id,
        ui_actions=show_on_console(navigate="/entry", tab="alias", prefill=prefill),
    )


def handle_mixed_cart_confirm(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
) -> ChatResponse | None:
    pending = get_pending(bag)
    if not isinstance(pending, PendingCart):
        return None
    flips = list(pending.awaiting_ignore_flip)
    items = list(pending.cart_items)
    if is_no(message) and (items or flips):
        set_pending(bag, None)
        return ChatResponse(
            reply_markdown=(
                f"Discarded {len(items) + len(flips)} staged line(s). "
                "Nothing was added to the cart."
            ),
            conversation_id=conversation_id,
        )
    if flips and is_yes(message):
        return _accept_ignore_flips(bag, conversation_id, flips)
    if not is_yes(message) or not items:
        return None
    set_pending(bag, None)
    labels = "\n".join(f"- {it.get('label') or it.get('kind')}" for it in items)
    return ChatResponse(
        reply_markdown=f"Added {len(items)} item(s) to the cart:\n{labels}",
        conversation_id=conversation_id,
        ui_actions=[{"type": "cart_add", "items": items}],
    )


def handle_pending_league_followup(
    *,
    bag: ChatSession,
    conversation_id: str,
    message: str,
    store: Any = None,
) -> ChatResponse | None:
    item = _pending_league_item(bag)
    if item is None:
        return None
    payload = item.get("payload") or {}
    slug = str(payload.get("league") or "")
    if _OPTIC_ASK.search(message):
        return _optic_id_reply(conversation_id, slug, payload, store)
    found = _OPTIC_SET.search(message)
    if found is None:
        return None
    optic = found.group(1).strip()
    _apply_optic_id(payload, optic)
    item["payload"] = payload
    return ChatResponse(
        reply_markdown=(
            f"Set **{slug}** `optic_league_id` to `{optic}`. "
            f"Reply **yes** to add to cart, or `suggest aliases for {slug}` "
            "to harvest Optic competitors."
        ),
        conversation_id=conversation_id,
        reply_buttons=confirm_buttons(),
    )


def _pending_league_item(bag: ChatSession) -> dict[str, Any] | None:
    items = cart_items(bag)
    return next((it for it in items if it.get("kind") == "mapping_league"), None)


def _apply_optic_id(payload: dict[str, Any], optic: str) -> None:
    payload["optic_league_id"] = optic
    for ex in payload.get("exchanges") or []:
        if str(ex.get("sportsbook") or "") == "optic":
            ex["source_league_id"] = optic


def _optic_id_reply(
    conversation_id: str,
    slug: str,
    payload: dict[str, Any],
    store: Any,
) -> ChatResponse:
    optic = str(payload.get("optic_league_id") or "").strip()
    if not optic and store is not None and slug:
        rid = getattr(store, "current_rule_set_id", None)
        row = next(
            (lg for lg in store.leagues_for(rid or "") if lg.league == slug),
            None,
        )
        optic = str(row.optic_league_id or "").strip() if row else ""
    if optic:
        body = f"**{slug}** `optic_league_id` is `{optic}`."
    else:
        body = (
            f"**{slug}** has no `optic_league_id` yet. "
            "Reply `the optic league name is <id>` (Optic catalog id)."
        )
    return ChatResponse(reply_markdown=body, conversation_id=conversation_id)


def _pending_skill_confirm(
    bag: ChatSession,
    conversation_id: str,
    message: str,
    pending: PendingSkill,
) -> ChatResponse | None:
    """Cart / ignore-flip yes-no while a skill still waits on a slot.

    Every branch below ends in ``set_pending`` and would otherwise drop the open
    question along with the cart, so the skill is always put back afterwards and
    dispatch re-asks the slot on the next turn.
    """
    flips = list(pending.awaiting_ignore_flip)
    if flips and is_yes(message):
        reply = _accept_ignore_flips(bag, conversation_id, flips)
    elif flips and is_no(message):
        set_pending(bag, PendingCart(cart_items=list(pending.cart_items)))
        reply = ChatResponse(
            reply_markdown=f"OK — left {len(flips)} rule(s) ignored.",
            conversation_id=conversation_id,
        )
    else:
        reply = confirm_or_discard_cart(
            bag=bag, conversation_id=conversation_id, message=message,
        )
        if reply is None:
            return None
    _restore_skill(bag, pending)
    return reply


def _restore_skill(bag: ChatSession, pending: PendingSkill) -> None:
    """Re-open the skill's question over whatever the cart handler left behind."""
    now = get_pending(bag)
    left = now if isinstance(now, PendingCart) else PendingCart()
    set_pending(
        bag,
        PendingSkill(
            skill=pending.skill,
            slots=dict(pending.slots),
            cart_items=list(left.cart_items),
            awaiting_ignore_flip=list(left.awaiting_ignore_flip),
        ),
    )


def _accept_ignore_flips(
    bag: ChatSession, conversation_id: str, flips: list[dict[str, Any]],
) -> ChatResponse:
    for item in flips:
        append_cart_item(bag, item)
    pending = get_pending(bag)
    if isinstance(pending, PendingCart):
        set_pending(bag, PendingCart(cart_items=list(pending.cart_items), awaiting_ignore_flip=[]))
    return ChatResponse(
        reply_markdown=(
            f"Queued {len(flips)} ignored→map flip(s).\n\n"
            f"{checklist_markdown(bag)}\n\nAdd all to cart?"
        ),
        conversation_id=conversation_id,
        reply_buttons=confirm_buttons(),
    )
