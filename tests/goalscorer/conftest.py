"""Freeze goalscorer's clock so history/lookup windows are deterministic."""

from datetime import UTC, datetime

import pytest

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
_MODULES = ("goalscorer.pregame", "goalscorer.single", "goalscorer.channel", "goalscorer.leagues", "goalscorer.listing")


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in _MODULES:
        monkeypatch.setattr(f"{module}.utcnow", lambda: NOW)
