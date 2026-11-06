"""Mapper Chat skill registry and dispatch."""

from __future__ import annotations

import re
from typing import Any, cast

from mappers.control_plane.chat_console import ConsolePage, console_has_context, page_league, page_sportsbook
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_pending import (
    PendingAlias,
    PendingCart,
    PendingSkill,
    get_pending,
    set_pending,
)
from mappers.control_plane.chat_resolve import ResolvedQuery
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_skills import (
    alias_pin,
    entity_add,
    fixture_coverage,
    market_rules,
    onboard_league,
    probe_gap,
    rules_lookup,
)
from mappers.control_plane.chat_skills import (
    outcomes as oc,
)
from mappers.control_plane.chat_skills.protocol import (
    ChatSkill,
    SkillCtx,
    SkillResult,
    announce,
    skill_status,
)
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.models import ChatResponse
from mappers.control_plane.settings import Settings

SKILLS: tuple[ChatSkill, ...] = cast(
    tuple[ChatSkill, ...],
    (probe_gap, fixture_coverage, entity_add, rules_lookup, alias_pin, onboard_league, market_rules),
)

_SKILL_BY_NAME: dict[str, ChatSkill] = {s.NAME: s for s in SKILLS}

_CLARIFY = "Could you clarify the league or mapping you want?"
_NON_WORD = re.compile(r"[^a-z0-9]+")


def dispatch_skill(
    *,
    message: str,
    scored: IntentScore,
    page: ConsolePage,
    conversation_id: str,
    settings: Settings,
    tools: ChatToolContext,
    bag: ChatSession,
    status_cb: Any = None,
    actor: str = "",
    resolved: ResolvedQuery | None = None,
) -> tuple[ChatResponse, str, str, SkillResult | None, str]:
    """Run skill playbook; return (response, path, outcome, skill_result, slot_source)."""
    resumed = _resume_skill(bag)
    if resumed and _abandon_skill_resume(scored, message, page, resumed["skill"], bag):
        _drop_skill_pending_keep_cart(bag)
        resumed = None
    if resumed:
        return _dispatch_resume(
            resumed, message=message, scored=scored, page=page, conversation_id=conversation_id,
            settings=settings, tools=tools, bag=bag, status_cb=status_cb, actor=actor,
            resolved=resolved or scored.resolved,
        )
    mod = _match_skill(scored, message, page)
    if mod is None:
        focus = _focus_skill(bag, scored)
        if focus:
            return _dispatch_resume(
                focus, message=message, scored=scored, page=page,
                conversation_id=conversation_id, settings=settings, tools=tools,
                bag=bag, status_cb=status_cb, actor=actor, slot_source="focus",
                resolved=resolved or scored.resolved,
            )
        return (
            ChatResponse(reply_markdown=_CLARIFY, conversation_id=conversation_id),
            "clarify", oc.ASK_SLOT, None, "",
        )
    slots = mod.slots(message, page, scored)
    slot_source = "console" if entry_slot_used(slots, page) else "message"
    missing = mod.missing_slot(slots)
    if missing:
        _save_skill_pending(bag, mod.NAME, slots)
        return _ask_slot(mod.NAME, missing, conversation_id, slot_source)
    return _run_skill(
        mod, message=message, scored=scored, page=page, slots=slots, slot_source=slot_source,
        conversation_id=conversation_id, settings=settings, tools=tools, bag=bag,
        status_cb=status_cb, actor=actor, resolved=resolved or scored.resolved,
    )


def _dispatch_resume(
    resumed: dict[str, Any], *, message: str, scored: IntentScore, page: ConsolePage,
    conversation_id: str, settings: Settings, tools: ChatToolContext, bag: ChatSession,
    status_cb: Any, actor: str = "", slot_source: str = "resume",
    resolved: ResolvedQuery | None = None,
) -> tuple[ChatResponse, str, str, SkillResult | None, str]:
    mod = _SKILL_BY_NAME.get(resumed["skill"])
    if mod is None:
        set_pending(bag, None)
        return (
            ChatResponse(reply_markdown=_CLARIFY, conversation_id=conversation_id),
            "clarify", oc.ASK_SLOT, None, "",
        )
    slots = dict(resumed.get("slots") or {})
    slots.update(_fill_followup(mod, slots, message))
    missing = mod.missing_slot(slots)
    if missing:
        _save_skill_pending(bag, mod.NAME, slots)
        return _ask_slot(mod.NAME, missing, conversation_id, "resume")
    return _run_skill(
        mod, message=message, scored=scored, page=page, slots=slots, slot_source=slot_source,
        conversation_id=conversation_id, settings=settings, tools=tools, bag=bag,
        status_cb=status_cb, actor=actor, resolved=resolved or scored.resolved,
    )


def _match_skill(scored: IntentScore, message: str, page: ConsolePage) -> ChatSkill | None:
    for candidate in SKILLS:
        if candidate.match(scored, message, page):
            return candidate
    return None


def _ask_slot(
    skill: str, missing: str, conversation_id: str, slot_source: str,
) -> tuple[ChatResponse, str, str, None, str]:
    return (
        ChatResponse(reply_markdown=missing, conversation_id=conversation_id),
        f"skill:{skill}", oc.ASK_SLOT, None, slot_source,
    )


def entry_slot_used(slots: dict[str, Any], page: ConsolePage) -> bool:
    """True when a required slot came from the console snapshot."""
    for key in ("league", "sport", "optic_league_id", "sportsbook"):
        if slots.get(key) and (
            page.entry.get(key)
            or (key == "league" and page_league(page))
            or (key == "sportsbook" and page_sportsbook(page))
        ):
            return True
    return console_has_context(page)


def _run_skill(
    mod: ChatSkill,
    *,
    message: str,
    scored: IntentScore,
    page: ConsolePage,
    slots: dict[str, Any],
    slot_source: str,
    conversation_id: str,
    settings: Settings,
    tools: ChatToolContext,
    bag: ChatSession,
    status_cb: Any,
    actor: str = "",
    resolved: ResolvedQuery | None = None,
) -> tuple[ChatResponse, str, str, SkillResult, str]:
    _clear_skill_pending(bag)
    ctx = SkillCtx(
        message=message,
        scored=scored,
        page=page,
        conversation_id=conversation_id,
        settings=settings,
        tools=tools,
        bag=bag,
        slots=slots,
        slot_source=slot_source,
        resolved=resolved or scored.resolved,
        status_cb=status_cb,
        actor=actor,
    )
    announce(ctx, skill_status(mod.NAME))
    result = mod.run(ctx)
    result.step_ms = {**ctx.step_ms, **result.step_ms}
    result.tool_names = list(dict.fromkeys([*ctx.tool_names, *result.tool_names]))
    response = mod.render(ctx, result)
    response.conversation_id = conversation_id
    outcome = _skill_outcome(result, response, page)
    _record_skill_turn(bag, mod, message, response, result, slots)
    return response, f"skill:{mod.NAME}", outcome, result, slot_source


def _skill_outcome(result: SkillResult, response: ChatResponse, page: ConsolePage) -> str:
    outcome = result.outcome or oc.OK
    if outcome == oc.OK and not response.ui_actions and page.path.startswith("/entry"):
        return oc.NO_UI
    return outcome


def _record_skill_turn(
    bag: ChatSession,
    mod: ChatSkill,
    message: str,
    response: ChatResponse,
    result: SkillResult,
    slots: dict[str, Any],
) -> None:
    bag.turns.append({"role": "user", "content": message})
    bag.turns.append({"role": "assistant", "content": response.reply_markdown})
    bag.remember(
        skill=mod.NAME,
        slots=slots,
        verdict=result.verdict,
        kind=str(result.data.get("kind") or ""),
        message=message,
    )


def _focus_skill(bag: ChatSession, scored: IntentScore) -> dict[str, Any] | None:
    """Resume the last completed skill when this turn matched nothing."""
    if not bag.has_focus() or _blocks_focus(scored):
        return None
    skill = bag.last_skill
    if skill not in _SKILL_BY_NAME:
        return None
    return {"skill": skill, "slots": dict(bag.last_slots)}


def _blocks_focus(scored: IntentScore) -> bool:
    """High-confidence new commands must not reuse the last subject."""
    if scored.intent == "confirm":
        return True
    if scored.confidence < 0.9:
        return False
    return scored.intent in {"entity_alias", "mapping_league", "mapping_market_rules"}


def _resume_skill(bag: ChatSession) -> dict[str, Any] | None:
    pending = get_pending(bag)
    if not isinstance(pending, PendingSkill) or not pending.skill:
        return None
    return {"skill": pending.skill, "slots": dict(pending.slots)}


def _abandon_skill_resume(
    scored: IntentScore,
    message: str,
    page: ConsolePage,
    pending_skill: str,
    bag: ChatSession,
) -> bool:
    """True when this turn is a new command rather than a fill for the open slot."""
    mod = _SKILL_BY_NAME.get(pending_skill)
    if mod is None:
        return True
    # yes/no belongs to the pending bag: cart confirm, else re-ask the slot.
    if scored.intent == "confirm":
        return False
    slots = dict((_resume_skill(bag) or {}).get("slots") or {})
    filled = _fill_followup(mod, slots, message)
    # Only a bare value resumes. "add league wta" also names a slug, but it
    # carries its own command around it, so it starts a new skill instead.
    if (
        filled
        and mod.missing_slot({**slots, **filled}) is None
        and _is_bare_slot_value(filled, message)
    ):
        return False
    matched = _match_skill(scored, message, page)
    if matched is None:
        return _blocks_focus(scored)
    if pending_skill != matched.NAME:
        return True
    # Same skill, but the message stands on its own ("pin ARS on kalshi for
    # epl" during a league ask) — restart it rather than merge stale slots.
    return mod.missing_slot(mod.slots(message, page, scored)) is None


def _is_bare_slot_value(filled: dict[str, Any], message: str) -> bool:
    """True when the message is only the value the skill asked for."""
    text = message.strip().lower()
    for value in filled.values():
        token = str(value or "").strip().lower()
        if not token:
            continue
        for variant in (token, token.replace("_", " "), token.replace("_", "-")):
            text = text.replace(variant, " ")
    return not _NON_WORD.sub("", text)


def _drop_skill_pending_keep_cart(bag: ChatSession) -> None:
    pending = get_pending(bag)
    if isinstance(pending, PendingSkill):
        cart = list(pending.cart_items)
        flips = list(pending.awaiting_ignore_flip)
        if cart or flips:
            set_pending(bag, PendingCart(cart_items=cart, awaiting_ignore_flip=flips))
            return
    set_pending(bag, None)


def _save_skill_pending(bag: ChatSession, skill: str, slots: dict[str, Any]) -> None:
    prev = get_pending(bag)
    keep_cart: list[dict[str, Any]] = []
    keep_flips: list[dict[str, Any]] = []
    if isinstance(prev, (PendingCart, PendingSkill)):
        keep_cart = list(prev.cart_items)
        keep_flips = list(prev.awaiting_ignore_flip)
    elif isinstance(prev, PendingAlias):
        keep_cart = list(prev.cart_items)
    set_pending(
        bag,
        PendingSkill(
            skill=skill,
            slots=slots,
            cart_items=keep_cart,
            awaiting_ignore_flip=keep_flips,
        ),
    )


def _clear_skill_pending(bag: ChatSession) -> None:
    pending = get_pending(bag)
    if isinstance(pending, PendingCart):
        if pending.cart_items or pending.awaiting_ignore_flip:
            set_pending(
                bag,
                PendingCart(
                    cart_items=list(pending.cart_items),
                    awaiting_ignore_flip=list(pending.awaiting_ignore_flip),
                ),
            )
        else:
            set_pending(bag, None)
        return
    cart: list[dict[str, Any]] = []
    flips: list[dict[str, Any]] = []
    if isinstance(pending, PendingSkill):
        cart = list(pending.cart_items)
        flips = list(pending.awaiting_ignore_flip)
    elif isinstance(pending, PendingAlias):
        cart = list(pending.cart_items)
    if cart or flips:
        set_pending(bag, PendingCart(cart_items=cart, awaiting_ignore_flip=flips))
    else:
        set_pending(bag, None)


def _fill_followup(mod: ChatSkill, slots: dict[str, Any], message: str) -> dict[str, Any]:
    """Fill the first empty required slot from a terse follow-up."""
    fn = getattr(mod, "fill_followup", None)
    if fn is not None:
        return fn(slots, message)
    if mod.missing_slot(slots):
        return _default_fill_followup(slots, message)
    return {}


def _default_fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    text = message.strip()
    return {"subject": text, "message": text} if text else {}
