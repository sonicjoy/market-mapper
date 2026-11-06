"""SSE streaming helpers for Mapper Chat."""

from __future__ import annotations

import asyncio
import json
import queue
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from mappers.control_plane.chat_intent import wants_crypto_sweep, wants_gap_fix
from mappers.control_plane.chat_resolve import has_probe_source, resolve_query
from mappers.control_plane.models import ChatResponse

_KEEPALIVE = ": keepalive\n\n"
_KEEPALIVE_SEC = 15.0
_POLL_SEC = 0.2


def opening_status(message: str) -> str:
    """Immediate dock copy while the turn (harvest / LLM) is still running."""
    text = (message or "").strip()
    if wants_gap_fix(text):
        return "Gap pins land in Proposed after each mapper tick…"
    if wants_crypto_sweep(text):
        return "Sweeping crypto.com team ids…"
    if has_probe_source(resolve_query(text)):
        return "Probing live catalogue…"
    return "Working…"


async def iter_chat_sse(
    message: str,
    turn: Callable[[], ChatResponse],
    *,
    status_queue: queue.Queue[str] | None = None,
    keepalive_sec: float = _KEEPALIVE_SEC,
) -> AsyncIterator[str]:
    """Yield status first, per-step status from queue, keepalives, then tokens."""
    yield _sse("status", {"text": opening_status(message)})
    async for chunk in _keepalive_until(turn, keepalive_sec, status_queue):
        yield chunk


async def _keepalive_until(
    turn: Callable[[], ChatResponse],
    keepalive_sec: float,
    status_queue: queue.Queue[str] | None,
) -> AsyncIterator[str]:
    """Run turn in a worker thread; flush step status often, keepalive on interval."""
    pending = asyncio.get_running_loop().run_in_executor(None, turn)
    next_keep = time.monotonic() + keepalive_sec
    while True:
        for event in _drain_status(status_queue):
            yield event
        timeout = _wait_timeout(keepalive_sec, next_keep)
        done, _ = await asyncio.wait({pending}, timeout=timeout)
        if done:
            break
        if keepalive_sec > 0 and time.monotonic() >= next_keep:
            yield _KEEPALIVE
            next_keep = time.monotonic() + keepalive_sec
    for event in _drain_status(status_queue):
        yield event
    try:
        response = pending.result()
    except Exception as exc:
        for chunk in _turn_failure_sse(exc):
            yield chunk
        return
    for chunk in chat_response_to_sse(response):
        yield chunk


def _drain_status(status_queue: queue.Queue[str] | None) -> list[str]:
    events: list[str] = []
    if status_queue is None:
        return events
    while True:
        try:
            events.append(_sse("status", {"text": status_queue.get_nowait()}))
        except queue.Empty:
            return events


def _wait_timeout(keepalive_sec: float, next_keep: float) -> float:
    if keepalive_sec <= 0:
        return _POLL_SEC
    until_keep = max(0.0, next_keep - time.monotonic())
    return min(_POLL_SEC, until_keep) or 0.0


def _turn_failure_sse(exc: BaseException) -> Iterator[str]:
    """Keep the dock socket open: a failed turn still gets a final envelope."""
    detail = f"{type(exc).__name__}: {exc}"[:160]
    yield _sse("status", {"text": "Turn failed — sending what we have…"})
    yield _sse("error", {"text": detail})
    yield from chat_response_to_sse(
        ChatResponse(
            reply_markdown=(
                "The chat turn failed before a reply was ready. "
                f"Retry the same question.\n\n`{detail}`"
            ),
        )
    )


def chat_response_to_sse(response: ChatResponse) -> Iterator[str]:
    """Yield SSE events: token chunks then a final JSON envelope."""
    text = response.reply_markdown or ""
    step = 48
    for i in range(0, max(len(text), 1), step):
        piece = text[i : i + step]
        yield _sse("token", {"text": piece})
    payload: dict[str, Any] = response.model_dump()
    yield _sse("final", payload)
    yield "data: [DONE]\n\n"


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
