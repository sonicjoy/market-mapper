"""In-process daily chat token/turn budgets (per pod)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mappers.control_plane.settings import Settings


@dataclass
class _DayCounters:
    day: object
    turns: int = 0
    tokens: int = 0


def _today():
    return datetime.now(UTC).date()


@dataclass
class ChatBudget:
    """Soft daily caps; over → Agent unavailable."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _counters: _DayCounters = field(default_factory=lambda: _DayCounters(day=_today()))

    def check(self, settings: Settings) -> str | None:
        """Return error message if over budget, else None."""
        with self._lock:
            self._roll()
            if settings.chat_daily_turn_budget and self._counters.turns >= settings.chat_daily_turn_budget:
                return "daily turn budget exceeded"
            if (
                settings.chat_daily_token_budget
                and self._counters.tokens >= settings.chat_daily_token_budget
            ):
                return "daily token budget exceeded"
            return None

    def record(self, *, turns: int = 1, tokens: int = 0) -> None:
        """Accumulate usage after a successful turn."""
        with self._lock:
            self._roll()
            self._counters.turns += turns
            self._counters.tokens += max(0, tokens)

    def reset(self) -> None:
        """Tests only."""
        with self._lock:
            self._counters = _DayCounters(day=_today())

    def _roll(self) -> None:
        today = _today()
        if self._counters.day != today:
            self._counters = _DayCounters(day=today)


_BUDGET = ChatBudget()


def chat_budget() -> ChatBudget:
    """Process singleton budget tracker."""
    return _BUDGET
