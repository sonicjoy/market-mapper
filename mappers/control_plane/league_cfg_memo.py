"""Request-scoped memo over ``gap_market_bind.effective_league_cfg``.

Opt-in and scoped: a Venue-gaps node asks for the same league once per
sampled leg, and the tip cannot change mid-request. Outside
:func:`league_cfg_memo` every call rebuilds, so tests that mutate an
in-memory store under one rule_set_id keep seeing their edits.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from mappers.control_plane.gap_market_bind import effective_league_cfg as _build

_MEMO: ContextVar[dict[tuple[int, str, str], Any] | None] = ContextVar("league_cfg_memo", default=None)


@contextmanager
def league_cfg_memo() -> Iterator[None]:
    """Reuse league configs per (store, tip, league) inside this block."""
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def effective_league_cfg(store: Any, league: str) -> tuple[Any, Any, list[Any]] | None:
    """:func:`gap_market_bind.effective_league_cfg`, cached for the enclosing :func:`league_cfg_memo`."""
    memo = _MEMO.get()
    if memo is None:
        return _build(store, league)
    key = (id(store), str(getattr(store, "current_rule_set_id", "") or ""), league)
    if key not in memo:
        memo[key] = _build(store, league)
    return memo[key]
