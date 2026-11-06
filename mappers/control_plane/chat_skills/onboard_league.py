"""onboard_league skill — needs_code gate + evidenced books only."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_cart import append_cart_item, checklist_markdown, confirm_buttons
from mappers.control_plane.chat_catalog import (
    league_followup,
    match_sport,
    optic_id_for,
    slug_from_message,
    sport_for_slug,
)
from mappers.control_plane.chat_console import ConsolePage, entry_field, page_league, show_on_console
from mappers.control_plane.chat_intent import IntentScore, wants_all_sportsbooks, wants_league_onboard
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import (
    ALWAYS_TOOLS,
    SkillCtx,
    SkillResult,
    timed_step,
)
from mappers.control_plane.chat_tools_skill import (
    check_parser_profiles,
    league_payload_from_evidence,
    probe_all_books_parallel,
)
from mappers.control_plane.models import ChatResponse

NAME = "onboard_league"
TOOLS = ("check_parser_profiles", "probe_exchange_league", "suggest_markets", *ALWAYS_TOOLS)


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    if scored.intent != "mapping_league":
        return False
    return wants_league_onboard(message) or wants_all_sportsbooks(message)


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    league = page_league(page) or scored.league_hint or slug_from_message(message) or ""
    if league.lower() in {"add", "new", "league", "enable", "onboard"}:
        league = ""
    sport = entry_field(page, "sport") or match_sport(message) or sport_for_slug(league)
    optic = entry_field(page, "optic_league_id") or optic_id_for(league)
    return {"league": league.strip(), "sport": sport.strip(), "optic_league_id": optic.strip()}


def missing_slot(slots: dict[str, Any]) -> str | None:
    league = str(slots.get("league") or "").strip().lower()
    if not league or len(league) < 3 or league in {"add", "new", "league", "enable", "onboard", "soccer"}:
        return "Which league slug should I onboard (e.g. `add league serie_a`)?"
    return None


def run(ctx: SkillCtx) -> SkillResult:
    s = ctx.slots
    league = str(s.get("league") or "")
    store = ctx.tools.store
    sport = str(s.get("sport") or "") or sport_for_slug(league, store)
    optic = str(s.get("optic_league_id") or "") or optic_id_for(league, store)
    gate = timed_step(
        ctx, NAME, "check_parser_profiles",
        lambda: check_parser_profiles(ctx.tools.store, league, None),
    )
    if gate.get("needs_code"):
        return _needs_code_result(league, str(gate.get("message") or ""))
    probes = timed_step(
        ctx, NAME, "probe_exchange_league",
        lambda: probe_all_books_parallel(
            ctx.tools.store, league, optic_league_id=optic, sport=sport,
            deadline_sec=ctx.settings.chat_timeout_sec,
        ),
    )
    return _stage_onboard(ctx, league, sport, optic, probes)


def _needs_code_result(league: str, message: str) -> SkillResult:
    return SkillResult(
        outcome=oc.NEEDS_CODE,
        reply_markdown=(
            f"**{league}** needs engine work first:\n\n{message}\n\n"
            "Do not stage a league until parser profiles exist."
        ),
    )


def _stage_onboard(
    ctx: SkillCtx, league: str, sport: str, optic: str, probes: list[dict[str, Any]]
) -> SkillResult:
    payload = league_payload_from_evidence(ctx.tools.store, league, sport, optic, probes)
    evidenced = [p for p in probes if p.get("evidence")]
    skipped = [p for p in probes if not p.get("evidence")]
    prefill = {
        "tab": "league", "league": league, "sport": payload.sport,
        "optic_league_id": payload.optic_league_id, "fixture_source": "api",
        "enabled": True, "exchanges": [ex.model_dump(mode="json") for ex in payload.exchanges],
        "note": "From Mapper Chat onboard_league skill",
    }
    append_cart_item(ctx.bag, {
        "kind": "mapping_league",
        "label": f"League {league} ({len(evidenced)} evidenced books)",
        "payload": payload.model_dump(mode="json"),
    })
    lines = [
        f"Prefilling **{league}** with evidenced platforms: "
        f"{', '.join(p.get('book', '') for p in evidenced) or 'none'}.",
    ]
    if skipped:
        lines.append("\nIntentional skips (no live evidence):")
        for row in skipped:
            lines.append(f"- **{row.get('book')}**: {row.get('note') or row.get('error') or 'no evidence'}")
    lines.extend([f"\n{checklist_markdown(ctx.bag)}", "\nReply **yes** to add to cart, or edit the league form first."])
    ui = show_on_console(navigate="/entry", tab="league", prefill=prefill)
    return SkillResult(
        outcome=oc.OK, reply_markdown="\n".join(lines), ui_actions=ui,
        reply_buttons=confirm_buttons(), data={"evidenced": evidenced, "skipped": skipped},
    )


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    # A junk slug ("add", "league") still counts as missing, so re-read it.
    if missing_slot(slots) is None:
        return {}
    league = league_followup(message)
    return {"league": league} if league else {}
