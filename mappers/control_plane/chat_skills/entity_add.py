"""entity_add skill — person/club lookup miss → Optic bind or Editor."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_catalog import league_followup
from mappers.control_plane.chat_console import ConsolePage, merge_rules_view, page_league, show_on_console
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_optic_name import ALREADY, AMBIGUOUS, UNIQUE, bind_optic_name
from mappers.control_plane.chat_resolve import has_probe_source, is_entity_query
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import ALWAYS_TOOLS, SkillCtx, SkillResult, timed_step
from mappers.control_plane.chat_skills.render import cart_buttons, prefill_from_pin, staged_note
from mappers.control_plane.chat_tools_skill import stage_alias_pins
from mappers.control_plane.models import ChatResponse

NAME = "entity_add"
TOOLS = ("stage_pin", *ALWAYS_TOOLS)


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    if scored.intent == "audit" or has_probe_source(scored.resolved):
        return False
    if scored.resolved.has_fixture_vs:
        return False
    return is_entity_query(message.strip(), scored.resolved)


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    resolved = scored.resolved
    return {
        "subject": resolved.entity_name,
        "message": message,
        "league": resolved.league or page_league(page),
    }


def missing_slot(slots: dict[str, Any]) -> str | None:
    return None


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    if str(slots.get("league") or "").strip():
        return {}
    league = league_followup(message)
    return {"league": league} if league else {}


def run(ctx: SkillCtx) -> SkillResult:
    name = str(ctx.slots.get("subject") or ctx.scored.resolved.entity_name or "").strip()
    league = str(ctx.slots.get("league") or ctx.scored.league_hint or "").strip()
    if league:
        optic = _optic_name_offer(ctx, league, name, ctx.page)
        if optic is not None:
            return optic
    return _editor_prefill(name, league, ctx.page)


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def _optic_name_offer(
    ctx: SkillCtx, slug: str, name: str, page: ConsolePage,
) -> SkillResult | None:
    bind = timed_step(
        ctx, NAME, "optic_name",
        lambda: bind_optic_name(ctx.tools.store, name=name, league=slug),
    )
    if bind.status == UNIQUE and bind.pin:
        return _stage_optic_name(ctx, bind.pin, page)
    if bind.status == ALREADY:
        ui = show_on_console(rules=merge_rules_view(page, kind="entities", q=name))
        return SkillResult(
            outcome=oc.OK,
            reply_markdown=(
                f"**{name}** is already on **{slug}** as `{bind.canonical_key}`. Opened Rules."
            ),
            ui_actions=ui,
        )
    if bind.status == AMBIGUOUS:
        listed = ", ".join(f"**{n}**" for n in bind.names[:4])
        editor = _editor_prefill(name, slug, page)
        editor.reply_markdown = (
            f"**{name}** matches more than one Optic competitor ({listed}). "
            "I opened Editor — paste a ticker or Optic id."
        )
        return editor
    return None


def _stage_optic_name(
    ctx: SkillCtx, pin: dict[str, Any], page: ConsolePage,
) -> SkillResult | None:
    staged = stage_alias_pins(ctx.tools, [pin])
    if not staged.get("ok"):
        return None
    pins = list(staged.get("pins") or [])
    prefill = prefill_from_pin(pins[0], "optic", "external_id")
    ui = show_on_console(
        navigate="/entry", tab="alias", prefill=prefill,
        rules=merge_rules_view(page, kind="entities", q=str(prefill.get("entity_name") or "")),
    )
    lines = [
        f"Optic unique-bind: **{pin.get('canonical_name')}** "
        f"`{pin.get('canonical_key')}` on **{pin.get('league')}**.",
        staged_note(len(pins)),
    ]
    return SkillResult(
        outcome=oc.OK,
        reply_markdown="\n".join(lines),
        ui_actions=ui,
        reply_buttons=cart_buttons(len(pins)),
        tool_names=["optic_name", "stage_pin"],
    )


def _editor_prefill(name: str, slug: str, page: ConsolePage) -> SkillResult:
    prefill = {
        "tab": "alias", "mode": "create", "entity_name": name,
        "entity_type": "player", "league": slug,
        "note": "From Mapper Chat entity lookup",
    }
    ui = show_on_console(
        navigate="/entry", tab="alias", prefill=prefill,
        rules=merge_rules_view(page, kind="entities", q=name),
    )
    ask = f" Which league should I pin **{name}** on?" if not slug else ""
    extra = (
        " Not unique in the Optic 96h window — paste a ticker or Optic id."
        if slug
        else " I opened Editor to add it — paste a ticker or Optic id for evidence "
        "before carting (Chat will not invent a code)."
    )
    return SkillResult(
        outcome=oc.OK,
        reply_markdown=f"**{name}** is not on the tip.{ask}{extra}",
        ui_actions=ui,
    )
