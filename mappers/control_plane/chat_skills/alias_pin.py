"""alias_pin skill — high-confidence entity_alias pins and sweeps."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.chat_cart import cart_items, checklist_markdown, confirm_buttons
from mappers.control_plane.chat_catalog import league_followup
from mappers.control_plane.chat_console import ConsolePage, show_on_console
from mappers.control_plane.chat_intent import (
    IntentScore,
    wants_crypto_sweep,
    wants_gap_fix,
)
from mappers.control_plane.chat_pending import PendingAlias, set_pending
from mappers.control_plane.chat_resolve import has_probe_source, is_entity_query
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import ALWAYS_TOOLS, SkillCtx, SkillResult
from mappers.control_plane.chat_tools_skill import stage_alias_pins
from mappers.control_plane.models import ChatReplyButton, ChatResponse

NAME = "alias_pin"
TOOLS = ("suggest_aliases", *ALWAYS_TOOLS)


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    if scored.intent != "entity_alias" or scored.confidence < 0.9:
        return False
    if is_entity_query(message, scored.resolved):
        return False
    return not has_probe_source(scored.resolved)


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    return {
        "league": scored.league_hint or "",
        "message": message,
        "code_hint": scored.code_hint or "",
        "sportsbook_hint": scored.sportsbook_hint or "",
    }


def missing_slot(slots: dict[str, Any]) -> str | None:
    message = str(slots.get("message") or "")
    if wants_gap_fix(message):
        return None
    if wants_crypto_sweep(message) and not str(slots.get("league") or "").strip():
        return "Which league should I sweep crypto ids for?"
    if not str(slots.get("league") or "").strip():
        return "Which league should I pin an alias for?"
    return None


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    origin = str(slots.get("message") or "")
    if wants_gap_fix(origin):
        return {}
    league = league_followup(message)
    if not league:
        return {}
    return {"league": league, "message": origin or message.strip()}


def run(ctx: SkillCtx) -> SkillResult:
    message = ctx.message
    scored = ctx.scored
    origin = str(ctx.slots.get("message") or message)
    if wants_gap_fix(origin) or wants_gap_fix(message):
        return _gap_review()
    if wants_crypto_sweep(origin) or wants_crypto_sweep(message):
        return _crypto_sweep(str(ctx.slots.get("league") or scored.league_hint or ""), ctx)
    league = str(ctx.slots.get("league") or scored.league_hint or "").strip()
    code = str(ctx.slots.get("code_hint") or scored.code_hint or "").strip()
    book = str(ctx.slots.get("sportsbook_hint") or scored.sportsbook_hint or "").strip()
    if code and book:
        return _single_pin(league, code, book, ctx)
    return _optic_suggest(league, ctx)


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def _gap_review() -> SkillResult:
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=(
            "Gap pins are harvested on each mapper tick and land in **Proposed**. "
            "Approve there — chat does not harvest (too slow from the console). "
            "Leftover RFQ rows: **Unmapped → Why**."
        ),
        ui_actions=show_on_console(navigate="/review"),
    )


def _single_pin(league: str, code: str, book: str, ctx: SkillCtx) -> SkillResult:
    pin = alias_payload(
        league,
        code,
        code,
        "team",
        [{
            "sportsbook": book,
            "alias_kind": "code",
            "alias_value": code,
        }],
        [],
    )
    staged = stage_alias_pins(ctx.tools, [pin])
    if not staged.get("ok"):
        blockers = list(staged.get("blockers") or [])
        note = "; ".join(blockers[:3]) if blockers else str(staged.get("error") or "blocked")
        return SkillResult(
            outcome=oc.PROBE_FAIL,
            reply_markdown=f"Could not stage **{book}** `{code}` on **{league}**: {note}",
        )
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=(
            f"Queued **{book}** `{code}` "
            f"on **{league}**.\n\n{checklist_markdown(ctx.bag)}\n\nAdd all to cart?"
        ),
        reply_buttons=confirm_buttons(),
    )


def _crypto_sweep(league: str, ctx: SkillCtx) -> SkillResult:
    result = ctx.tools.run("sweep_crypto_ids", {"league": league})
    suggestions = list(result.get("suggestions") or [])
    if not suggestions:
        return _crypto_sweep_empty(league, result)
    return _crypto_sweep_confirm(league, result, suggestions, ctx)


def _crypto_sweep_empty(league: str, result: dict[str, Any]) -> SkillResult:
    warnings = list(result.get("warnings") or [])
    note = "; ".join(warnings[:3]) if warnings else "no missing crypto_id pins"
    already = result.get("already_pinned") or 0
    extra = f" ({already} already on tip)" if already else ""
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=f"No missing crypto ids for **{league}**: {note}{extra}",
    )


def _crypto_sweep_confirm(
    league: str, result: dict[str, Any], suggestions: list[dict[str, Any]], ctx: SkillCtx,
) -> SkillResult:
    items = [
        {"kind": "entity_alias", "label": s.get("label") or s.get("id"), "payload": dict(s.get("payload") or {})}
        for s in suggestions if s.get("payload")
    ]
    prefill = _crypto_prefill(league, suggestions[0])
    keep = cart_items(ctx.bag)
    set_pending(ctx.bag, PendingAlias(cart_items=keep + items, prefill=prefill))
    ask, yes_label, tail = _crypto_confirm_copy(len(items), int(result.get("truncated") or 0))
    already = result.get("already_pinned") or 0
    skip = f" Skipped {already} already on tip." if already else ""
    preview = "\n".join(f"- {s.get('label')}" for s in suggestions[:10])
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=(
            f"Found **{len(items)}** missing crypto id(s) for **{league}**. "
            f"{ask}{skip}\n{preview}{tail}"
        ),
        reply_buttons=[
            ChatReplyButton(id="yes", label=yes_label, send="yes"),
            ChatReplyButton(id="no", label="Not now", send="no"),
        ],
        ui_actions=show_on_console(navigate="/entry", tab="alias", prefill=prefill),
    )


def _crypto_prefill(league: str, suggestion: dict[str, Any]) -> dict[str, Any]:
    payload = dict(suggestion.get("payload") or {})
    aliases = payload.get("aliases") or []
    first = aliases[0] if aliases else {}
    return {
        "tab": "alias",
        "league": payload.get("league") or league,
        "sportsbook": first.get("sportsbook", "crypto.com"),
        "code": first.get("alias_value", ""),
        "entity_name": payload.get("canonical_name") or "",
        "entity_type": payload.get("entity_type") or "team",
        "canonical_key": payload.get("canonical_key") or "",
        "alias_kind": first.get("alias_kind") or "crypto_id",
        "note": "From Mapper Chat crypto sweep",
    }


def _crypto_confirm_copy(count: int, more: int) -> tuple[str, str, str]:
    if more:
        return (
            f"Add these **{count}** to cart (capped; {more} more not included)?",
            "Yes, add these to cart",
            f"\n- …and {more} more not included (capped at {count})",
        )
    return f"Add all **{count}** to cart?", "Yes, add all to cart", ""


def _optic_suggest(league: str, ctx: SkillCtx) -> SkillResult:
    result = ctx.tools.run("suggest_aliases", {"league": league})
    suggestions = list(result.get("suggestions") or [])
    warnings = list(result.get("warnings") or [])
    if not suggestions:
        note = "; ".join(warnings) if warnings else "No Optic competitors found."
        return SkillResult(
            outcome=oc.PROBE_FAIL,
            reply_markdown=f"Could not suggest aliases for **{league}**: {note}",
        )
    top = suggestions[:5]
    buttons = [
        ChatReplyButton(
            id=f"sel_{i}",
            label=(s.get("label") or s.get("id") or f"#{i}")[:48],
            send=f"select:{s.get('id')}",
        )
        for i, s in enumerate(top)
    ]
    set_pending(ctx.bag, PendingAlias(
        suggestions={str(s.get("id")): s for s in top},
        league=league,
        cart_items=cart_items(ctx.bag),
    ))
    lines = "\n".join(f"- {s.get('label')}" for s in top)
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=f"Alias suggestions for **{league}** (pick one):\n{lines}",
        reply_buttons=buttons,
    )
