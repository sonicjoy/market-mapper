"""rules_lookup skill — audit, counts, and tip Rules search."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from mappers.control_plane.chat_audit_count import audit_rule_counts, format_audit_count_reply
from mappers.control_plane.chat_catalog import named_league, named_sportsbooks
from mappers.control_plane.chat_confirm_words import is_no, is_yes
from mappers.control_plane.chat_console import (
    ConsolePage,
    merge_rules_view,
    page_league,
    rules_kind,
    rules_query_from_page,
    show_on_console,
)
from mappers.control_plane.chat_intent import (
    IntentScore,
    audit_kind,
    audit_subject,
    is_count_question,
)
from mappers.control_plane.chat_resolve import OPTIC_HEX, has_probe_source
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.protocol import ALWAYS_TOOLS, SkillCtx, SkillResult, timed_step
from mappers.control_plane.console_rules_query import search_human_rules
from mappers.control_plane.models import ChatResponse

NAME = "rules_lookup"
TOOLS = ("lookup_rules", *ALWAYS_TOOLS)
_ASK_SUBJECT = (
    "Which league, code, or Optic id should I look up? "
    "For a league's `optic_league_id`, name the slug (e.g. `optic id for epl`)."
)
_LEAGUE_NOUN = re.compile(r"\bleagues?\b", re.I)
_PLATFORM_NOUN = re.compile(r"\b(platforms?|sportsbooks?|books?|exchanges?)\b", re.I)
_MARKET_KW = re.compile(
    r"\b(market[_\s-]?rules?|markets?|taxonomy|spread|moneyline|total)\b",
    re.I,
)
_COVERAGE_Q = re.compile(r"\b(is|are|do we have|did we)\b.*\b(mapped|pinned|covered)\b", re.I)
_COUNT_SKIP = frozenset({
    "how", "many", "much", "count", "number", "ignored", "ignore", "market", "markets",
    "rules", "rule", "leagues", "league", "aliases", "entities", "do", "we", "map",
    "mapped", "have", "the", "of", "a", "an",
})
# A lookup subject is one token a Rules query can match: a slug, ticker, or id.
_SUBJECT_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,63}")
_SUBJECT_WRAP = "`'\"“”‘’ .,?!"


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    if has_probe_source(scored.resolved):
        return False
    if scored.intent == "audit":
        return True
    if _COVERAGE_Q.search(message.strip()):
        return True
    return bool(is_count_question(message))


def _optic_hex_subject(resolved: Any) -> str:
    for sid in getattr(resolved, "source_ids", ()) or ():
        if getattr(sid, "kind", None) == OPTIC_HEX:
            return str(sid.value)
    return ""


def _named_league_subject(message: str) -> str:
    """Subject of a platform/market audit (``which platforms map mlb`` → ``mlb``).

    Only a real league slug counts. Picking "the last token that is not a stop
    word" turns ``which sportsbooks do we support`` into a Rules query for
    ``support``.
    """
    return named_league(message) or ""


def _audit_without_named_subject(message: str) -> bool:
    if _PLATFORM_NOUN.search(message):
        return True
    if _LEAGUE_NOUN.search(message) and re.search(r"\b(missing|which)\b", message, re.I):
        return True
    return bool(_MARKET_KW.search(message) and named_sportsbooks(message))


def slots(message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    resolved = scored.resolved
    subj = (
        resolved.entity_name
        or audit_subject(message)
        or _optic_hex_subject(resolved)
        or scored.league_hint
        or scored.code_hint
        or (_named_league_subject(message) if _audit_without_named_subject(message) else "")
        or ""
    )
    return {"subject": subj, "message": message, "league": resolved.league or page_league(page)}


def missing_slot(slots: dict[str, Any]) -> str | None:
    message = str(slots.get("message") or "")
    if is_count_question(message):
        return None
    if str(slots.get("subject") or "").strip():
        return None
    if _audit_without_named_subject(message):
        return None
    return _ASK_SUBJECT


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    """Absorb a terse subject (``raphinha``, ``epl``, an Optic hex) — never prose.

    A sentence here means the trader changed the subject, so leave the slot open
    and let dispatch route the turn instead of searching Rules for the sentence.
    """
    if str(slots.get("subject") or "").strip():
        return {}
    # Traders paste codes the way the console renders them: `epl`, "ARS", epl.
    text = message.strip().strip(_SUBJECT_WRAP)
    if not text or is_yes(text) or is_no(text):
        return {}
    if not _SUBJECT_TOKEN.fullmatch(text):
        return {}
    return {"subject": text}


def run(ctx: SkillCtx) -> SkillResult:
    message = ctx.message
    page = ctx.page
    store = ctx.tools.store
    subject = str(ctx.slots.get("subject") or "")
    kind = audit_kind(
        message, code_hint=ctx.scored.code_hint, league_hint=ctx.scored.league_hint,
        page_kind=rules_kind(page),
    )
    q = _resolve_lookup_q(message, ctx.scored, subject)
    query = rules_query_from_page(page, kind=kind, **({"q": q} if q else {}))
    if is_count_question(message):
        counts = timed_step(
            ctx, NAME, "audit_count", lambda: audit_rule_counts(store, query),
        )
        reply = format_audit_count_reply(
            query, counts, wants_ignored="ignor" in message.lower(),
        )
        ui = show_on_console(rules=merge_rules_view(page, kind=kind, q=q or None))
        return SkillResult(
            outcome=oc.OK, reply_markdown=reply, ui_actions=ui,
            tool_names=["audit_rule_counts"],
        )
    data = timed_step(
        ctx, NAME, "lookup_rules",
        lambda: search_human_rules(store, replace(query, limit=15, offset=0)),
    )
    return _lookup_result(ctx, kind, q, data, page)


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def _resolve_lookup_q(message: str, scored: IntentScore, subject: str) -> str:
    if subject:
        return subject
    if is_count_question(message) and _LEAGUE_NOUN.search(message) and not scored.league_hint:
        return ""
    if is_count_question(message):
        for tok in re.findall(r"\b([a-z][a-z0-9_.-]{1,31})\b", message.lower()):
            if tok not in _COUNT_SKIP:
                return tok
        return ""
    for sid in scored.resolved.source_ids:
        if sid.kind == OPTIC_HEX:
            return sid.value
    if scored.code_hint:
        return scored.code_hint
    if scored.league_hint:
        return scored.league_hint
    return ""


def _lookup_result(
    ctx: SkillCtx, kind: str, q: str, data: dict[str, Any], page: ConsolePage,
) -> SkillResult:
    count = int(data.get("count") or 0)
    lines = [f"**{count}** `{kind}` row(s) matching `{q}`."]
    rows = data.get("entities") or data.get("leagues") or data.get("market_rules") or []
    for row in list(rows)[:8]:
        lines.append(_row_line(kind, row))
    if kind == "entities" and count == 0:
        lines.append(_empty_roster_hint(
            ctx.tools.store, ctx.scored.league_hint or str(ctx.slots.get("league") or ""), q,
        ))
    ui = show_on_console(rules=merge_rules_view(page, kind=kind, q=q or None))
    return SkillResult(outcome=oc.OK, reply_markdown="\n".join(lines), ui_actions=ui)


def _row_line(kind: str, row: dict[str, Any]) -> str:
    if kind == "entities":
        pins = row.get("aliases") or []
        books = ", ".join(f"`{pin.get('code')}` ({pin.get('sportsbook')})" for pin in pins[:6])
        return (
            f"- **{row.get('canonical_key')}** {row.get('entity_name', '')}"
            + (f" — {books}" if books else "")
        )
    if kind == "leagues":
        return f"- **{row.get('league')}** sport={row.get('sport')} optic={row.get('optic_league_id')}"
    return f"- {row.get('sportsbook')} `{row.get('source_key')}` → {row.get('canonical_market_type')}"


def _empty_roster_hint(store: Any, league: str | None, q: str) -> str:
    slug = (league or q or "").strip()
    if not slug or store is None:
        return (
            "Empty roster until Optic competitor pins. Set `optic_league_id`, "
            "then `suggest aliases for <slug>`."
        )
    rid = getattr(store, "current_rule_set_id", None)
    row = next((lg for lg in store.leagues_for(rid or "") if lg.league == slug), None)
    if row is None:
        return f"No entities for `{slug}`. Onboard first (`add league {slug}`), then harvest Optic aliases."
    if not row.optic_league_id:
        return (
            f"**{slug}** is on the tip with 0 entities. Set `optic_league_id`, "
            f"then `suggest aliases for {slug}`."
        )
    return f"**{slug}** has 0 entities. Try `suggest aliases for {slug}` (do not onboard the league again)."
