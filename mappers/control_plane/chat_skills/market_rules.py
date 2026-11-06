"""market_rules skill — named-book market staging regression guard."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_cart import cart_items, checklist_markdown, confirm_buttons
from mappers.control_plane.chat_catalog import league_followup, match_league, named_sportsbooks
from mappers.control_plane.chat_console import ConsolePage, page_league, page_sportsbook, show_on_console
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_prefill import market_prefill_from_cart
from mappers.control_plane.chat_resolve import poly_usa_parser_gaps
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import (
    ALWAYS_TOOLS,
    SkillCtx,
    SkillResult,
    timed_step,
)
from mappers.control_plane.models import ChatResponse

NAME = "market_rules"
TOOLS = ("lookup_rules", "suggest_markets", *ALWAYS_TOOLS)


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    if scored.intent != "mapping_market_rules":
        return False
    resolved = scored.resolved
    books = resolved.books or named_sportsbooks(message)
    return bool(books) and scored.confidence >= 0.75


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    resolved = scored.resolved
    league = (
        page_league(page)
        or scored.league_hint
        or resolved.league
        or match_league(message)
        or ""
    )
    books = list(resolved.books) or named_sportsbooks(message)
    book = books[0] if books else (scored.sportsbook_hint or page_sportsbook(page))
    return {
        "league": league.strip(),
        "sportsbook": book,
        "market_ids": list(resolved.market_ids),
    }


def missing_slot(slots: dict[str, Any]) -> str | None:
    if not slots.get("league"):
        return "Which league should I suggest market rules for?"
    return None


def run(ctx: SkillCtx) -> SkillResult:
    league = str(ctx.slots.get("league") or "")
    book = str(ctx.slots.get("sportsbook") or "")
    ids = tuple(str(x) for x in (ctx.slots.get("market_ids") or []) if x)
    gap = _parser_gap_result(league, book, ids)
    if gap is not None:
        return gap
    market = _market_filter(ctx.message, ids)
    out = timed_step(
        ctx,
        NAME,
        "propose_markets",
        lambda: ctx.tools.run(
            "propose_markets",
            {"league": league, "sportsbook": book, "market": market},
        ),
    )
    return _after_propose(ctx, league, book, market, out)


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    if slots.get("league"):
        return {}
    league = league_followup(message)
    return {"league": league} if league else {}


def _parser_gap_result(league: str, book: str, ids: tuple[str, ...]) -> SkillResult | None:
    if book != "polymarket_usa" or not ids:
        return None
    gaps = poly_usa_parser_gaps(ids)
    if not gaps:
        return None
    already = [mid for mid in ids if mid not in gaps]
    lines = [
        f"**{league or 'nfl'}** on **Polymarket US** needs parser work "
        "(`mappers/vocab/poly_usa_smt.py` enum table, Optic table, missing "
        "`MarketType`s). "
        "A mapping card will not enable these tickers.",
        "",
    ]
    if already:
        lines.append("Already parsed: " + ", ".join(f"`{m}`" for m in already))
    lines.append("needs_code: " + ", ".join(f"`{m}`" for m in gaps))
    return SkillResult(outcome=oc.NEEDS_CODE, reply_markdown="\n".join(lines))


def _market_filter(message: str, ids: tuple[str, ...]) -> str:
    if len(ids) == 1:
        return ids[0]
    if "moneyline" in message.lower() and not ids:
        return "moneyline"
    return ""


def _after_propose(
    ctx: SkillCtx, league: str, book: str, market: str, out: dict[str, Any],
) -> SkillResult:
    if out.get("needs_ignore_confirm"):
        return SkillResult(
            outcome=oc.ASK_SLOT,
            reply_markdown=str(out.get("message") or "Confirm ignored→map flip?"),
            reply_buttons=confirm_buttons(),
        )
    if not out.get("ok"):
        note = out.get("message") or out.get("error") or "No market rules staged."
        return SkillResult(
            outcome=oc.PROBE_FAIL,
            reply_markdown=f"No market-rule suggestions for **{league}**: {note}",
        )
    prefill = market_prefill_from_cart(
        cart_items(ctx.bag), league=league, sportsbook=book, market=market,
    )
    ui = show_on_console(navigate="/entry", tab="market", prefill=prefill)
    lines = [
        str(out.get("message") or f"Staged market rules for **{league}** on **{book}**."),
        "",
        checklist_markdown(ctx.bag),
        "",
        "Reply **yes** to add to cart.",
    ]
    return SkillResult(
        outcome=oc.OK,
        reply_markdown="\n".join(lines),
        ui_actions=ui,
        reply_buttons=confirm_buttons(),
    )
