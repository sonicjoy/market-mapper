"""Wall-clock cap on skill steps so a live probe cannot outlast the gateway."""

from __future__ import annotations

import time

from pytest import MonkeyPatch

from mappers.control_plane.chat_console import ConsolePage
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_skills import outcomes as oc
from mappers.control_plane.chat_skills import probe_gap
from mappers.control_plane.chat_skills.protocol import (
    SkillCtx,
    StepDeadlineError,
    timed_step,
)
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.settings import Settings


def _ctx() -> SkillCtx:
    return SkillCtx(
        message="x",
        scored=IntentScore("entity_alias", 0.5),
        page=ConsolePage(),
        conversation_id="c1",
        settings=Settings(gcp_project="p"),
        tools=ChatToolContext(store=None),
        bag=ChatSession(conversation_id="c1"),
    )


def test_timed_step_raises_after_deadline() -> None:
    ctx = _ctx()
    started = time.time()
    try:
        timed_step(ctx, "probe_gap", "probe_crypto_gap", lambda: time.sleep(2), deadline_sec=0.05)
    except StepDeadlineError:
        assert time.time() - started < 1
        return
    raise AssertionError("expected StepDeadlineError")


def test_timed_step_returns_when_under_deadline() -> None:
    assert timed_step(_ctx(), "probe_gap", "probe_crypto_gap", lambda: 7, deadline_sec=1) == 7


def test_probe_gap_deadline_is_a_retryable_reply(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(probe_gap, "PROBE_DEADLINE_SEC", 0.05)
    monkeypatch.setattr(probe_gap, "run_probe_crypto_gap", lambda *_a, **_k: time.sleep(2))
    ctx = _ctx()
    ctx.slots = {
        "crypto": "NX.F.OPT.TENNIS-0182-260824-M.O.1.1.20261231",
        "kalshi": "",
        "league": "",
    }
    result = probe_gap.run(ctx)
    assert result.outcome == oc.DEADLINE
    assert "timed out" in result.reply_markdown
