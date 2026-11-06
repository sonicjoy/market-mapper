"""Path 2 fixture bind helpers: typed US team abbreviations onto Optic sides."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime


def resolve_team_code(
    code: str,
    usa_aliases: Mapping[str, str],
    kalshi_aliases: Mapping[str, str],
    *,
    fixture_sides: set[str] | None = None,
) -> str:
    """Map a gateway team abbreviation to a fixture side token.

    Tip aliases may map a short book code onto a canonical key (``WHU`` →
    ``WHUF6``). Path 2 bind accepts either the canonical or the Optic
    competitor abbreviation; when ``fixture_sides`` is set, only accept an
    alias target that appears on that fixture, otherwise keep the
    abbreviation.
    """
    token = code.upper()
    sides = {s.casefold() for s in (fixture_sides or ()) if s}
    for aliases in (usa_aliases, kalshi_aliases):
        for key in (code, code.upper(), code.casefold()):
            hit = aliases.get(key)
            if not isinstance(hit, str) or not hit:
                continue
            resolved = hit.upper()
            if sides and resolved.casefold() not in sides:
                continue
            return resolved
    return token


def parse_kickoff(value: str | None) -> datetime | None:
    """Parse a UTC instant from the public gateway or Optic ``start_date``."""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif text.endswith("+00"):
        text = text[:-3] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
