"""SSE status is flushed before the chat turn runs."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable

from mappers.control_plane.chat_stream import iter_chat_sse, opening_status
from mappers.control_plane.models import ChatResponse


def _chunks(
    message: str,
    turn: Callable[[], ChatResponse],
    *,
    keepalive_sec: float = 15.0,
) -> list[str]:
    async def _collect() -> list[str]:
        return [c async for c in iter_chat_sse(message, turn, keepalive_sec=keepalive_sec)]

    return asyncio.run(_collect())


def test_opening_status_for_fix_gaps() -> None:
    assert "Proposed" in opening_status("fix gaps")
    assert opening_status("pin M05") == "Working…"
    assert "catalogue" in opening_status(
        "is this crypto symbol mapped: NX.F.OPT.TENNIS-0182-260824-M.O.1.1.20261231"
    )


def test_iter_chat_sse_status_before_turn() -> None:
    order: list[str] = []

    def turn() -> ChatResponse:
        order.append("turn")
        return ChatResponse(reply_markdown="done", conversation_id="c1")

    chunks = _chunks("fix gaps", turn)
    assert "event: status" in chunks[0]
    assert "Proposed" in chunks[0]
    assert order == ["turn"]
    assert any("event: token" in chunk for chunk in chunks)
    assert any("event: final" in chunk for chunk in chunks)


def test_status_yielded_before_turn_finishes() -> None:
    gate = threading.Event()

    def turn() -> ChatResponse:
        gate.wait(timeout=2)
        return ChatResponse(reply_markdown="done", conversation_id="c1")

    async def run() -> tuple[str, list[str]]:
        agen = iter_chat_sse("hi", turn, keepalive_sec=0.05)
        first = await anext(agen)
        gate.set()
        rest = [c async for c in agen]
        return first, rest

    first, rest = asyncio.run(run())
    assert "event: status" in first
    assert any("event: final" in chunk for chunk in rest)


def test_step_status_flushed_while_turn_runs() -> None:
    """Dock copy queued mid-turn must not wait for the 15s keepalive."""
    status: queue.Queue[str] = queue.Queue()
    gate = threading.Event()

    def turn() -> ChatResponse:
        status.put("Probing crypto.com…")
        gate.wait(timeout=2)
        return ChatResponse(reply_markdown="done", conversation_id="c1")

    async def run() -> list[str]:
        agen = iter_chat_sse("hi", turn, status_queue=status, keepalive_sec=15)
        seen: list[str] = []
        async for chunk in agen:
            seen.append(chunk)
            if "Probing crypto.com" in chunk:
                gate.set()
                break
        rest = [c async for c in agen]
        return seen + rest

    started = time.time()
    chunks = asyncio.run(run())
    assert time.time() - started < 2
    assert any("Probing crypto.com" in chunk for chunk in chunks)
    assert any("event: final" in chunk for chunk in chunks)


def test_turn_exception_still_emits_final() -> None:
    def turn() -> ChatResponse:
        raise RuntimeError("bq hung")

    chunks = _chunks("hi", turn)
    assert any("event: error" in chunk for chunk in chunks)
    assert any("event: final" in chunk for chunk in chunks)
    assert any("bq hung" in chunk for chunk in chunks)


def test_iter_chat_sse_keepalive_while_turn_runs() -> None:
    def turn() -> ChatResponse:
        time.sleep(0.08)
        return ChatResponse(reply_markdown="done", conversation_id="c1")

    chunks = _chunks("hi", turn, keepalive_sec=0.02)
    assert chunks[0].startswith("event: status")
    assert any(chunk.startswith(": keepalive") for chunk in chunks)
    assert any("event: final" in chunk for chunk in chunks)
