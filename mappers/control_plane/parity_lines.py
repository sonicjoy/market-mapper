"""Parse dual-read mismatch lines for the Parity page."""

from __future__ import annotations

from typing import Any

_DECLARATIVE = frozenset({"rule_parity_ok", "rule_parity_mismatch"})
# Longest book names first so "crypto.com" wins over a stray "crypto".
_SPORTSBOOKS = ("crypto.com", "polymarket", "kalshi", "optic", "px")


def parse_mismatch_line(line: str) -> dict[str, str]:
    """Split ``league: label live=... seed=...`` into table columns."""
    raw = line.strip()
    league, sep, rest = raw.partition(":")
    sportsbook = "—"
    haystack = rest.lower() if sep else raw.lower()
    for book in _SPORTSBOOKS:
        if book in haystack:
            sportsbook = book
            break
    return {
        "league": league.strip() if sep and league.strip() else "—",
        "sportsbook": sportsbook,
        "detail": raw,
    }


def latest_mismatch_rows(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Mismatch lines from the newest declarative parity event (empty if OK)."""
    for event in events:
        if event.get("event_type") not in _DECLARATIVE:
            continue
        if event.get("event_type") == "rule_parity_ok":
            return []
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return []
        lines = payload.get("mismatches") or []
        if not isinstance(lines, list):
            return []
        return [parse_mismatch_line(str(line)) for line in lines]
    return []
