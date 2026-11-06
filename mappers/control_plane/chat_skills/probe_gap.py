"""probe_gap skill — classify crypto gaps and look up other pasted ids with evidence.

Kalshi tickers get a read-only market_mapping lookup: Kalshi maps from its own
typed fields, so there is no tip alias to stage for it.
"""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.chat_console import (
    ConsolePage,
    coverage_href,
    show_on_console,
    unmapped_href,
)
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_resolve import (
    kalshi_ids,
    nx_ids,
    other_probe_id,
    probe_source_id,
)
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills.probe_gap_render import next_step, verdict_table
from mappers.control_plane.chat_skills.protocol import (
    ALWAYS_TOOLS,
    SkillCtx,
    SkillResult,
    StepDeadlineError,
    announce,
    timed_step,
)
from mappers.control_plane.chat_skills.render import cart_buttons, prefill_from_pin, staged_note
from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.chat_tools_mapping import probe_source_mapping
from mappers.control_plane.chat_tools_skill import stage_pins_from_rows
from mappers.control_plane.models import ChatResponse

NAME = "probe_gap"
TOOLS = ("probe_crypto_gap", "stage_pin", *ALWAYS_TOOLS)
PROBE_DEADLINE_SEC = 12.0
_MAX_SOURCES = 5
_NO_REVIEW = frozenset({"leave_collision", "mapped"})
_UNMAPPED = frozenset({"expected_residual", "horizon_wait", "actionable"})


def match(scored: IntentScore, message: str, page: ConsolePage) -> bool:
    resolved = scored.resolved
    return bool(kalshi_ids(resolved) or nx_ids(resolved) or probe_source_id(resolved))


def slots(message: str, _page: ConsolePage, scored: IntentScore) -> dict[str, Any]:
    resolved = scored.resolved
    kx = list(kalshi_ids(resolved))
    nx = list(nx_ids(resolved))
    other = probe_source_id(resolved)
    return {
        "kalshi": kx[0] if kx else "",
        "kalshi_all": kx,
        "crypto": nx[0] if nx else "",
        "crypto_all": nx,
        "other": other,
        "league": "",
    }


def missing_slot(slots: dict[str, Any]) -> str | None:
    if not slots.get("kalshi") and not slots.get("crypto") and not slots.get("other"):
        return "Paste a ticker, NX.F symbol, or sportsbook source id to probe."
    return None


def fill_followup(slots: dict[str, Any], message: str) -> dict[str, Any]:
    if slots.get("kalshi") or slots.get("crypto") or slots.get("other"):
        return {}
    text = message.strip()
    if not text:
        return {}
    if text.upper().startswith("KX"):
        ticker = text.upper()
        return {"kalshi": ticker, "kalshi_all": [ticker]}
    if text.upper().startswith("NX."):
        symbol = text.upper()
        return {"crypto": symbol, "crypto_all": [symbol]}
    other = other_probe_id(text)
    return {"other": other} if other else {}


def run(ctx: SkillCtx) -> SkillResult:
    s = ctx.slots or slots(ctx.message, ctx.page, ctx.scored)
    league = str(s.get("league") or "")
    nx = _id_list(s, "crypto_all", "crypto")
    # A bare id is looked up only when nothing typed was pasted: digits inside
    # an NX symbol must not become a second (PX) probe.
    other = "" if nx else str(s.get("other") or "").strip()
    sources = _id_list(s, "kalshi_all", "kalshi") or ([other] if other else [])
    if sources and nx:
        return _merge_probe_results(
            _run_source_probe(ctx, sources), _run_crypto_probe(ctx, nx, league),
        )
    if nx:
        return _run_crypto_probe(ctx, nx, league)
    return _run_source_probe(ctx, sources)


def _run_source_probe(ctx: SkillCtx, sources: list[str]) -> SkillResult:
    """Read-only market_mapping lookup (plus catalogue anatomy) per pasted id."""
    return _run_book(
        ctx,
        subject=sources[0],
        step="probe_source_mapping",
        fn=lambda: _probe_sources(sources),
        finish=_source_result,
    )


def _probe_sources(sources: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in sources[:_MAX_SOURCES]:
        rows.extend(probe_source_mapping(source).get("results") or [])
    return {"ok": True, "count": len(rows), "results": rows}


def _run_crypto_probe(ctx: SkillCtx, nx: list[str], league: str) -> SkillResult:
    return _run_book(
        ctx,
        subject=nx[0],
        step="probe_crypto_gap",
        fn=lambda: run_probe_crypto_gap(ctx.tools.store, {"symbols": nx, "league": league}),
        finish=_crypto_result,
    )


def _merge_probe_results(source: SkillResult, crypto: SkillResult) -> SkillResult:
    lines = [
        source.reply_markdown.strip(),
        "",
        crypto.reply_markdown.strip(),
    ]
    verdict = (
        "actionable"
        if "actionable" in {source.verdict, crypto.verdict}
        # A timed-out leg has no verdict; do not let it blank the other one.
        else source.verdict or crypto.verdict
    )
    return SkillResult(
        outcome=_merged_outcome(source.outcome, crypto.outcome),
        reply_markdown="\n".join(lines).strip(),
        # The console applies one navigation and one prefill per turn, so keep
        # the leg that can be acted on and drop the duplicate from the other.
        ui_actions=_pick_ui(source, crypto),
        reply_buttons=list(source.reply_buttons or []) or list(crypto.reply_buttons or []),
        verdict=verdict,
        data={**crypto.data, **source.data},
        tool_names=list(dict.fromkeys([*source.tool_names, *crypto.tool_names])),
        step_ms={**source.step_ms, **crypto.step_ms},
    )


def _merged_outcome(source: str, crypto: str) -> str:
    """A timed-out leg must stay visible in the turn log, not be masked by ok."""
    if oc.DEADLINE in {source, crypto}:
        return oc.DEADLINE
    return source if source == crypto else oc.OK


def _pick_ui(source: SkillResult, crypto: SkillResult) -> list[dict[str, Any]]:
    if crypto.verdict == "actionable" and source.verdict != "actionable":
        return list(crypto.ui_actions or [])
    return list(source.ui_actions or []) or list(crypto.ui_actions or [])


def _id_list(slots: dict[str, Any], key_all: str, key_one: str) -> list[str]:
    """Prefer the collected id list; fall back to the singular slot."""
    raw = list(slots.get(key_all) or [])
    if not raw and slots.get(key_one):
        raw = [str(slots[key_one])]
    return [str(x).strip() for x in raw if str(x).strip()]


def _run_book(
    ctx: SkillCtx,
    *,
    subject: str,
    step: str,
    fn: Any,
    finish: Any,
) -> SkillResult:
    try:
        probe = timed_step(ctx, NAME, step, fn, deadline_sec=PROBE_DEADLINE_SEC)
    except StepDeadlineError:
        announce(ctx, "Catalogue lookup timed out…")
        return _deadline_result(subject)
    return finish(ctx, probe, subject)


def _deadline_result(subject: str) -> SkillResult:
    return SkillResult(
        outcome=oc.DEADLINE,
        reply_markdown=(
            f"**{subject}** — catalogue lookup timed out ({int(PROBE_DEADLINE_SEC)}s). "
            "Retry the same symbol; a cold BigQuery job can miss this window."
        ),
    )


def render(ctx: SkillCtx, result: SkillResult) -> ChatResponse:
    return ChatResponse(
        reply_markdown=result.reply_markdown,
        conversation_id=ctx.conversation_id,
        ui_actions=result.ui_actions,
        reply_buttons=result.reply_buttons,
    )


def _source_result(ctx: SkillCtx, probe: dict[str, Any], source: str) -> SkillResult:
    rows = list(probe.get("results") or []) or [{}]
    return _render_rows(ctx, rows, source, book="source", alias_kind="code")


def _crypto_result(ctx: SkillCtx, probe: dict[str, Any], symbol: str) -> SkillResult:
    rows = list(probe.get("results") or []) or [{}]
    return _render_rows(ctx, rows, symbol, book="crypto.com", alias_kind="crypto_id")


def _render_rows(
    ctx: SkillCtx, rows: list[dict[str, Any]], subject: str, *, book: str, alias_kind: str,
) -> SkillResult:
    classify = _classify_crypto if book == "crypto.com" else _classify_source
    verdicts = [classify(row) for row in rows]
    lines = _why_lines(ctx.message, verdicts[0] if verdicts else "", rows[0] if rows else {})
    for row, verdict in zip(rows, verdicts, strict=True):
        lines.extend(verdict_table(_row_subject(row, subject), verdict, row))
        lines.append("")
    return _finish(ctx, rows, _overall(verdicts), book, alias_kind, lines)


def _why_lines(message: str, verdict: str, row: dict[str, Any]) -> list[str]:
    """Lead with the residual reason when the trader asked why."""
    if not re.search(r"\bwhy\b", message, re.I):
        return []
    return [f"**Why:** {next_step(verdict, row)}", ""]


def _row_kind(rows: list[dict[str, Any]]) -> str:
    return str((rows[0] if rows else {}).get("kind") or "")


def _row_subject(row: dict[str, Any], fallback: str) -> str:
    return str(
        row.get("market_ticker")
        or row.get("symbol")
        or row.get("event_ticker")
        or fallback
    )


def _overall(verdicts: list[str]) -> str:
    if not verdicts:
        return "expected_residual"
    if "actionable" in verdicts:
        return "actionable"
    if all(v == "mapped" for v in verdicts):
        return "mapped"
    return verdicts[0]


def _finish(
    ctx: SkillCtx,
    rows: list[dict[str, Any]],
    verdict: str,
    book: str,
    alias_kind: str,
    lines: list[str],
) -> SkillResult:
    if verdict == "actionable":
        return _actionable(ctx, rows, book, alias_kind, lines)
    return _non_actionable(verdict, rows, lines)


def _actionable(
    ctx: SkillCtx,
    rows: list[dict[str, Any]],
    book: str,
    alias_kind: str,
    lines: list[str],
) -> SkillResult:
    staged = stage_pins_from_rows(ctx.tools, rows, book=book)
    if not staged.get("ok"):
        lines.append(f"\nCould not draft a pin ({staged.get('error') or 'no evidence'}).")
        return _non_actionable("actionable", rows, lines)
    pins = list(staged.get("pins") or [])
    prefill = prefill_from_pin(pins[0], book, alias_kind)
    lines.append(staged_note(len(pins)))
    return SkillResult(
        outcome=oc.OK,
        reply_markdown="\n".join(lines).rstrip(),
        ui_actions=show_on_console(navigate="/entry", tab="alias", prefill=prefill),
        reply_buttons=cart_buttons(len(pins)),
        verdict="actionable",
        data={"kind": _row_kind(rows)},
    )


def _non_actionable(
    verdict: str,
    rows: list[dict[str, Any]],
    lines: list[str],
) -> SkillResult:
    body = "\n".join(lines).rstrip()
    if verdict in _NO_REVIEW:
        return SkillResult(
            outcome=oc.OK, reply_markdown=body, verdict=verdict, data={"kind": _row_kind(rows)},
        )
    if verdict == "maker_lag":
        return _maker_lag(rows, lines)
    if verdict in _UNMAPPED:
        lines.append("\nOpen **Unmapped → Why** for residual vs cart-fix.")
        row = rows[0] if rows else {}
        nav = unmapped_href(league=str(row.get("league") or ""))
    else:
        lines.append("\nGap harvest lands on **Proposed** after each mapper tick.")
        nav = "/review"
    return SkillResult(
        outcome=oc.OK,
        reply_markdown="\n".join(lines).rstrip(),
        ui_actions=show_on_console(navigate=nav),
        verdict=verdict,
        data={"kind": _row_kind(rows)},
    )


def _maker_lag(rows: list[dict[str, Any]], lines: list[str]) -> SkillResult:
    """Already on tip — Coverage, not Unmapped Why."""
    row = rows[0] if rows else {}
    raw = row.get("optic")
    optic = raw if isinstance(raw, dict) else {}
    lines.append("\nOpen **Coverage** for this fixture.")
    return SkillResult(
        outcome=oc.OK,
        reply_markdown="\n".join(lines).rstrip(),
        ui_actions=show_on_console(
            navigate=coverage_href(
                league=str(row.get("league") or ""),
                fixture=str(optic.get("fixture_id") or ""),
            ),
        ),
        verdict="maker_lag",
        data={"kind": _row_kind(rows)},
    )


def _classify_source(row: dict[str, Any]) -> str:
    if row.get("mapped_rows"):
        return "mapped"
    kind = str(row.get("kind") or "")
    if kind == "unknown_alias":
        return "actionable"
    if kind in {"already_mapped", "mapped"}:
        return "maker_lag"
    if kind in {"outside_horizon", "horizon"}:
        return "horizon_wait"
    if kind in {"collision", "disambig"}:
        return "leave_collision"
    if kind in {"title_miss", "missing_optic", "unmapped", "exact_score"}:
        return "expected_residual"
    if not row.get("league"):
        return "needs_league"
    return "expected_residual"


def _classify_crypto(row: dict[str, Any]) -> str:
    if row.get("mapped_rows"):
        return "mapped"
    kind = str(row.get("kind") or "")
    if kind in {
        "unknown_alias", "unknown_crypto_id", "actionable", "name_mismatch", "alias_mismatch",
    }:
        return "actionable"
    if kind == "unmapped":
        return "expected_residual"
    if kind in {"outside_horizon", "horizon"}:
        return "horizon_wait"
    if kind in {"catalogue_miss", "tournament_future", "completed_stale", "league_not_wired"}:
        return "expected_residual"
    if kind == "already_mapped":
        return "maker_lag"
    return "expected_residual"
