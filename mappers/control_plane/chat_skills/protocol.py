"""Skill protocol and shared context for Mapper Chat."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from mappers.control_plane.chat_console import ConsolePage
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_log import log_chat_step
from mappers.control_plane.chat_resolve import ResolvedQuery
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.models import ChatReplyButton, ChatResponse
from mappers.control_plane.settings import Settings


@dataclass
class SkillResult:
    """Output of skill.run before render."""

    outcome: str
    reply_markdown: str = ""
    ui_actions: list[dict[str, Any]] = field(default_factory=list)
    reply_buttons: list[ChatReplyButton] = field(default_factory=list)
    verdict: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    needs_narration: bool = False
    tool_names: list[str] = field(default_factory=list)
    step_ms: dict[str, int] = field(default_factory=dict)


@dataclass
class SkillCtx:
    """Everything a skill needs for one turn."""

    message: str
    scored: IntentScore
    page: ConsolePage
    conversation_id: str
    settings: Settings
    tools: ChatToolContext
    bag: ChatSession
    slots: dict[str, Any] = field(default_factory=dict)
    slot_source: str = "message"
    resolved: ResolvedQuery = field(default_factory=ResolvedQuery)
    actor: str = ""
    status_cb: Any = None
    step_ms: dict[str, int] = field(default_factory=dict)
    tool_names: list[str] = field(default_factory=list)


# read_console / show_on_console are in every scoped set so a skill is never
# blind to the page it is driving; the plan caps the rest at three.
ALWAYS_TOOLS: tuple[str, ...] = ("read_console", "show_on_console")
MAX_TOOLS = 5


class ChatSkill(Protocol):
    NAME: str
    TOOLS: tuple[str, ...]

    def match(self, scored: IntentScore, message: str, page: ConsolePage) -> bool: ...

    def slots(self, message: str, page: ConsolePage, scored: IntentScore) -> dict[str, Any]: ...

    def missing_slot(self, slots: dict[str, Any]) -> str | None: ...

    def run(self, ctx: SkillCtx) -> SkillResult: ...

    def render(self, ctx: SkillCtx, result: SkillResult) -> ChatResponse: ...

    def fill_followup(self, slots: dict[str, Any], message: str) -> dict[str, Any]: ...


_STEP_STATUS = {
    "audit_count": "Counting mapped rows…",
    "check_parser_profiles": "Checking parser profiles…",
    "fixture_coverage": "Opening Coverage…",
    "lookup_rules": "Searching tip rules…",
    "optic_name": "Probing Optic competitors…",
    "probe_crypto_gap": "Probing crypto.com…",
    "probe_exchange_league": "Probing books in parallel…",
    "probe_source_mapping": "Checking catalogue mapping…",
    "propose_markets": "Staging market rules…",
}

_SKILL_STATUS = {
    "rules_lookup": "Searching tip rules…",
    "entity_add": "Looking up entity…",
    "fixture_coverage": "Opening Coverage…",
    "market_rules": "Suggesting market rules…",
    "onboard_league": "Onboarding the league…",
    "probe_gap": "Classifying the gap…",
    "alias_pin": "Suggesting alias pins…",
}


def announce(ctx: SkillCtx, text: str) -> None:
    """Push live dock copy before a slow step starts."""
    if ctx.status_cb and text:
        ctx.status_cb(text)


def skill_status(name: str) -> str:
    return _SKILL_STATUS.get(name, "Working…")


class StepDeadlineError(Exception):
    """A skill step exceeded its wall-clock budget."""


def log_step(ctx: SkillCtx, skill: str, step: str, *, tool: str = "", ms: int = 0, ok: bool = True) -> None:
    log_chat_step(
        conversation_id=ctx.conversation_id,
        skill=skill,
        step=step,
        tool=tool,
        duration_ms=ms,
        ok=ok,
    )
    ctx.step_ms[step] = ms
    name = tool or step
    if name not in ctx.tool_names:
        ctx.tool_names.append(name)


def timed_step(
    ctx: SkillCtx, skill: str, step: str, fn: Any, *, tool: str = "", deadline_sec: float = 0,
) -> Any:
    """Run one skill step, announcing it to the dock before the wait."""
    announce(ctx, _STEP_STATUS.get(step, f"{step.replace('_', ' ')}…"))
    started = time.time()
    try:
        out = _run_step(fn, deadline_sec)
        log_step(ctx, skill, step, tool=tool, ms=int((time.time() - started) * 1000), ok=True)
        return out
    except Exception:
        log_step(ctx, skill, step, tool=tool, ms=int((time.time() - started) * 1000), ok=False)
        raise


def _run_step(fn: Any, deadline_sec: float) -> Any:
    """Call ``fn`` on this thread, or on a daemon with a wall-clock cap."""
    if deadline_sec <= 0:
        return fn()
    box: list[Any] = []
    err: list[BaseException] = []

    def _call() -> None:
        try:
            box.append(fn())
        except BaseException as exc:
            err.append(exc)

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    worker.join(deadline_sec)
    if worker.is_alive():
        raise StepDeadlineError(f"step exceeded {deadline_sec:.0f}s")
    if err:
        raise err[0]
    return box[0]
