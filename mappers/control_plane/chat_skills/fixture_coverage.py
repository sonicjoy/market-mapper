"""fixture_coverage skill — team vs team paste opens Coverage."""

from __future__ import annotations

from typing import Any

from mappers.control_plane import chat_tools_fixture as fixture
from mappers.control_plane.chat_console import ConsolePage, coverage_href, page_league, show_on_console
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import ALWAYS_TOOLS, SkillCtx, SkillResult, timed_step
from mappers.control_plane.models import ChatResponse

NAME = "fixture_coverage"
TOOLS = ("fixture_coverage", *ALWAYS_TOOLS)


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    return scored.resolved.has_fixture_vs


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    return {"message": message, "league": scored.resolved.league or page_league(page)}


def missing_slot(slots: dict[str, Any]) -> str | None:
    return None


def run(ctx: SkillCtx) -> SkillResult:
    slot_league = str(ctx.slots.get("league") or page_league(ctx.page) or "").strip()
    cov = timed_step(
        ctx, NAME, "fixture_coverage",
        lambda: fixture.fixture_coverage(
            ctx.tools.store, ctx.message, league=slot_league,
        ),
    )
    sides = list(cov.get("sides") or [])
    missing = list(cov.get("missing") or [])
    lines = [str(cov.get("message") or "Fixture coverage:")]
    for side in sides[:4]:
        mark = "mapped" if side.get("mapped") else "missing"
        lines.append(f"- {side.get('name')}: **{mark}**")
    if missing:
        lines.append(f"\n{len(missing)} side(s) still need alias pins.")
    league = slot_league
    resolved = cov.get("resolved")
    if isinstance(resolved, dict) and resolved.get("league"):
        league = str(resolved.get("league"))
    ui = list(cov.get("ui_actions") or []) or show_on_console(
        navigate=coverage_href(league=league or slot_league or page_league(ctx.page)),
    )
    return SkillResult(outcome=oc.OK, reply_markdown="\n".join(lines), ui_actions=ui)


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
    )
