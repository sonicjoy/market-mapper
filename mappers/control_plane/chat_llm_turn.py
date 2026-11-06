"""Scoped LLM fallback for unmatched on-topic Mapper Chat turns."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mappers.control_plane.chat_llm import ChatLLM, ChatLLMResult
from mappers.control_plane.chat_llm_cache import cached_chat_llm
from mappers.control_plane.chat_resolve import (
    market_ids_from_message,
    poly_usa_llm_prompt_fragment,
    poly_usa_parser_gaps,
)
from mappers.control_plane.chat_skills.outcomes import ASK_SLOT, LLM_ERROR, OK
from mappers.control_plane.chat_tools import ChatToolContext, tool_result_json
from mappers.control_plane.models import ChatResponse
from mappers.control_plane.settings import Settings

LLM_TOOLS: tuple[str, ...] = (
    "lookup_rules",
    "stage_pin",
    "propose_markets",
    "check_parser_profiles",
    "show_on_console",
)
_CLARIFY = "Could you clarify the league or mapping you want?"
_BASE_SYSTEM = """You are Mapper Chat on the mapping console.
Help with aliases, market rules, and leagues.
Never approve, activate, harvest, or write BigQuery.
stage_pin and propose_markets use the same Cart Verify kernel as Editor.
Do not invent codes."""


def system_prompt() -> str:
    """LLM system card; Poly US wired kinds come from the parser registry."""
    return (
        f"{_BASE_SYSTEM}\n{poly_usa_llm_prompt_fragment()}\n"
        "If lookup_rules finds no person/club, show_on_console /entry alias tab with "
        "entity_name. Do not onboard a person as a league.\n"
        "Prefer lookup_rules and check_parser_profiles before staging. Be brief."
    )


@dataclass
class LlmTurn:
    """Finished fallback turn (router logs path=llm)."""

    response: ChatResponse
    tokens: int = 0
    tool_names: list[str] = field(default_factory=list)
    outcome: str = OK


def should_run_llm(settings: Settings, llm: Any) -> bool:
    """Skip pytest fake; run when a real provider or injected non-fake client is set."""
    if llm is not None:
        return str(getattr(llm, "provider", "") or "") != "fake"
    return settings.chat_provider != "fake"


def blocked_propose_markets(message: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Reject Polymarket US staging when pasted ids need parser work."""
    book = str(args.get("sportsbook") or "")
    if book != "polymarket_usa":
        return None
    gaps = poly_usa_parser_gaps(market_ids_from_message(message))
    if not gaps:
        return None
    return {
        "ok": False,
        "needs_code": True,
        "gaps": list(gaps),
        "message": (
            "needs_code: Polymarket US Path 2 cannot parse these yet "
            f"({', '.join(gaps)}). Do not stage a mapping card."
        ),
    }


def run_llm_turn(
    *,
    message: str,
    tools: ChatToolContext,
    settings: Settings,
    conversation_id: str,
    llm: Any = None,
    status_cb: Any = None,
) -> LlmTurn:
    """Tool loop; feed results back as user text (no Gemini thought_signature replay)."""
    if status_cb:
        status_cb("Consulting the mapping model…")
    try:
        client = _client(settings, llm)
        return _loop(message, tools, settings, conversation_id, client)
    except Exception as exc:
        return LlmTurn(
            response=ChatResponse(
                reply_markdown=f"Agent unavailable: chat model failed ({type(exc).__name__}).",
                conversation_id=conversation_id,
            ),
            outcome=LLM_ERROR,
        )


def _client(settings: Settings, llm: Any) -> ChatLLM:
    if llm is not None:
        return llm
    return cached_chat_llm(settings)


def _loop(
    message: str,
    tools: ChatToolContext,
    settings: Settings,
    conversation_id: str,
    client: ChatLLM,
) -> LlmTurn:
    started = time.time()
    timeout = max(1.0, float(settings.chat_timeout_sec or 30.0))
    schemas = ChatToolContext.scoped_schemas(LLM_TOOLS)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": message},
    ]
    ui: list[dict[str, Any]] = []
    names: list[str] = []
    tokens = 0
    for _ in range(max(1, settings.chat_tool_rounds)):
        if time.time() - started > timeout:
            break
        result = client.complete(messages, schemas)
        tokens += result.input_tokens + result.output_tokens
        if not result.tool_calls:
            return _final(result, conversation_id, ui, names, tokens)
        blob, ui_add, named = _apply_tools(message, tools, result)
        ui.extend(ui_add)
        names.extend(named)
        messages.append({"role": "user", "content": blob})
    return LlmTurn(
        response=ChatResponse(
            reply_markdown=_CLARIFY,
            conversation_id=conversation_id,
            ui_actions=ui,
        ),
        tokens=tokens,
        tool_names=list(dict.fromkeys(names)),
        outcome=ASK_SLOT,
    )


def _final(
    result: ChatLLMResult,
    conversation_id: str,
    ui: list[dict[str, Any]],
    names: list[str],
    tokens: int,
) -> LlmTurn:
    text = (result.text or "").strip() or _CLARIFY
    return LlmTurn(
        response=ChatResponse(
            reply_markdown=text,
            conversation_id=conversation_id,
            ui_actions=ui,
        ),
        tokens=tokens,
        tool_names=list(dict.fromkeys(names)),
        outcome=OK,
    )


def _apply_tools(
    message: str,
    tools: ChatToolContext,
    result: ChatLLMResult,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    lines: list[str] = ["Tool results (do not replay function calls):"]
    ui: list[dict[str, Any]] = []
    names: list[str] = []
    for call in result.tool_calls:
        out = _exec_call(message, tools, call.name, dict(call.args or {}))
        names.append(call.name)
        ui.extend(_ui_from(out))
        lines.append(f"{call.name} -> {tool_result_json(_slim(out))}")
    return "\n".join(lines), ui, names


def _exec_call(
    message: str,
    tools: ChatToolContext,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if name not in LLM_TOOLS:
        return {"ok": False, "error": f"blocked_tool:{name}"}
    if name == "propose_markets":
        blocked = blocked_propose_markets(message, args)
        if blocked is not None:
            return blocked
    return tools.run(name, args)


def _ui_from(out: dict[str, Any]) -> list[dict[str, Any]]:
    raw = out.get("ui_actions") or []
    return [row for row in raw if isinstance(row, dict)]


def _slim(out: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in out.items() if key != "ui_actions"}
