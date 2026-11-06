"""Mapper Chat turn router — confirm paths and skill dispatch."""

from __future__ import annotations

import queue
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mappers.control_plane.chat_budget import chat_budget
from mappers.control_plane.chat_cart import handle_pending
from mappers.control_plane.chat_console import ConsolePage, page_league, parse_page_context
from mappers.control_plane.chat_intent import score_intent
from mappers.control_plane.chat_llm_turn import run_llm_turn, should_run_llm
from mappers.control_plane.chat_log import log_chat_turn
from mappers.control_plane.chat_resolve import resolve_query
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_skills import dispatch_skill
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_tip_cache import tip_league_slugs
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.chat_topic import is_on_topic
from mappers.control_plane.entry import LiveLookup, NullLiveLookup
from mappers.control_plane.models import ChatRequest, ChatResponse
from mappers.control_plane.settings import Settings


def handle_chat_turn(
    body: ChatRequest,
    *,
    settings: Settings,
    store: Any,
    live: LiveLookup | None = None,
    llm: Any = None,
    status_queue: queue.Queue[str] | None = None,
    actor: str = "",
    evidence_fn: Any = None,
) -> ChatResponse:
    """Run one chat turn; skills first, then optional scoped LLM fallback."""
    unavailable = _unavailable(body, settings)
    if unavailable is not None:
        return unavailable
    ctx = _turn_context(body, store, live, status_queue, actor, evidence_fn)
    early = _confirm_paths(
        message=ctx.message, bag=ctx.bag, conversation_id=ctx.conversation_id,
        store=store,
    )
    if early is not None:
        ctx.bag.answered_turns += 1
        return _finish(early[0], settings, ctx, path=early[1], outcome=oc.CONFIRM)
    tip_leagues = tip_league_slugs(store)
    resolved = resolve_query(
        ctx.message, tip_leagues=tip_leagues, page_league=page_league(ctx.page),
    )
    scored = score_intent(ctx.message, tip_leagues=tip_leagues, resolved=resolved)
    response, path, outcome, skill_result, slot_source = dispatch_skill(
        message=ctx.message, scored=scored, page=ctx.page, conversation_id=ctx.conversation_id,
        settings=settings, tools=ctx.tools, bag=ctx.bag, status_cb=ctx.status_cb, actor=ctx.actor,
        resolved=resolved,
    )
    return _after_skill_dispatch(
        response, path, outcome, skill_result, slot_source,
        ctx=ctx, scored=scored, settings=settings, llm=llm,
    )


@dataclass
class _TurnCtx:
    conversation_id: str
    started: float
    bag: Any
    page: ConsolePage
    tools: ChatToolContext
    message: str
    status_cb: Callable[[str], None]
    actor: str = ""


def _turn_context(
    body: ChatRequest,
    store: Any,
    live: LiveLookup | None,
    status_queue: queue.Queue[str] | None,
    actor: str = "",
    evidence_fn: Any = None,
) -> _TurnCtx:
    conversation_id = body.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    started = time.time()
    bag = session_bag().get_or_create(conversation_id)
    page = parse_page_context(body.page_context if isinstance(body.page_context, dict) else None)
    tools = ChatToolContext(
        store,
        live or NullLiveLookup(),
        bag=bag,
        page=page,
        evidence_fn=evidence_fn,
    )
    message = (body.message or "").strip()

    def status_cb(text: str) -> None:
        if status_queue is not None:
            status_queue.put(text)

    return _TurnCtx(
        conversation_id=conversation_id,
        started=started,
        bag=bag,
        page=page,
        tools=tools,
        message=message,
        status_cb=status_cb,
        actor=actor,
    )


def _after_skill_dispatch(
    response: ChatResponse,
    path: str,
    outcome: str,
    skill_result: Any,
    slot_source: str,
    *,
    ctx: _TurnCtx,
    scored: Any,
    settings: Settings,
    llm: Any = None,
) -> ChatResponse:
    bag = ctx.bag
    if path == "clarify":
        llm_out = _maybe_llm(ctx, scored, settings, llm)
        if llm_out is not None:
            bag.answered_turns += 1
            return llm_out
    bag.answered_turns += 1
    session_bag().touch(bag)
    if path == "clarify" or outcome == oc.ASK_SLOT:
        return _finish(response, settings, ctx, path=path, intent=scored.intent, outcome=outcome)
    return _finish(
        response, settings, ctx, path=path, intent=scored.intent, outcome=outcome,
        tool_names=list(skill_result.tool_names) if skill_result else [],
        step_ms=dict(skill_result.step_ms) if skill_result else {},
        verdict=skill_result.verdict if skill_result else "",
        slot_source=slot_source,
    )


def _maybe_llm(ctx: _TurnCtx, scored: Any, settings: Settings, llm: Any) -> ChatResponse | None:
    """On-topic unmatched turns; fake provider stays on the cheap clarify path."""
    if not should_run_llm(settings, llm):
        return None
    if not is_on_topic(
        ctx.message, scored=scored, bag=ctx.bag, settings=settings, page=ctx.page,
    ):
        return None
    turn = run_llm_turn(
        message=ctx.message,
        tools=ctx.tools,
        settings=settings,
        conversation_id=ctx.conversation_id,
        llm=llm,
        status_cb=ctx.status_cb,
    )
    session_bag().touch(ctx.bag)
    return _finish(
        turn.response, settings, ctx, path="llm", intent=scored.intent,
        outcome=turn.outcome, tokens=turn.tokens, tool_names=turn.tool_names,
        provider=str(getattr(llm, "provider", "") or settings.chat_provider),
        model=str(getattr(llm, "model", "") or settings.chat_model),
    )


def _unavailable(body: ChatRequest, settings: Settings) -> ChatResponse | None:
    """Feature flag and daily budget, checked before any per-turn work."""
    if not settings.chat_enabled:
        return ChatResponse(
            reply_markdown="Mapper Chat is disabled on this deploy (`MAPPING_CP_CHAT`).",
            agent_available=False,
            conversation_id=body.conversation_id,
        )
    over = chat_budget().check(settings)
    if over:
        return ChatResponse(
            reply_markdown=f"Agent unavailable: {over}",
            agent_available=False,
            conversation_id=body.conversation_id,
        )
    return None


def _confirm_paths(
    *, message: str, bag: Any, conversation_id: str, store: Any = None,
) -> tuple[ChatResponse, str] | None:
    """select:/yes for alias cards, mixed cart, and skill follow-ups."""
    confirmed = handle_pending(
        bag=bag, conversation_id=conversation_id, message=message, store=store,
    )
    if confirmed is not None:
        return confirmed, "confirm"
    return None


def _finish(
    response: ChatResponse,
    settings: Settings,
    ctx: _TurnCtx,
    *,
    path: str,
    provider: str = "",
    model: str = "",
    intent: str = "",
    outcome: str = "",
    tokens: int = 0,
    tool_names: list[str] | None = None,
    step_ms: dict[str, int] | None = None,
    verdict: str = "",
    slot_source: str = "",
) -> ChatResponse:
    if response.agent_available:
        chat_budget().record(turns=1, tokens=tokens)
    log_chat_turn(
        path=path,
        outcome=outcome or path,
        intent=intent or path,
        verdict=verdict,
        actor=ctx.actor,
        provider=provider or settings.chat_provider,
        model=model or settings.chat_model,
        agent_available=response.agent_available,
        conversation_id=response.conversation_id,
        duration_ms=int((time.time() - ctx.started) * 1000),
        tokens=tokens,
        message=ctx.message,
        reply=response.reply_markdown,
        page_path=ctx.page.path,
        page_tab=ctx.page.tab,
        slot_source=slot_source,
        tool_names=tool_names or [],
        step_ms=step_ms or {},
        ui_action_types=[a.get("type") for a in response.ui_actions],
    )
    return response
