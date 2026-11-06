"""Small helpers shared by tip league factory modules."""

from __future__ import annotations

from typing import Any, TypeVar

_C = TypeVar("_C")


def narrow(kind: type[_C], built: object) -> _C | None:
    """Narrow a profile build result to the expected exchange config type."""
    if built is None or isinstance(built, kind):
        return built
    raise TypeError(f"profile built {type(built).__name__}, expected {kind.__name__}")


def exchange_map(row: Any) -> dict[str, dict[str, Any]]:
    """Enabled tip exchanges keyed by sportsbook."""
    out: dict[str, dict[str, Any]] = {}
    for ex in getattr(row, "exchanges", None) or []:
        if not ex.get("enabled", True):
            continue
        book = str(ex.get("sportsbook") or "").strip()
        if book:
            out[book] = ex
    return out
