"""Period scope for book source keys vs Optic canonical market types."""

from __future__ import annotations

from typing import Any

from mappers.vocab.poly_usa_console import is_smt_rule, wired_canonical

_PERIOD_PREFIXES: tuple[tuple[str, str], ...] = (
    ("1H", "1h"),
    ("2H", "2h"),
    ("1Q", "1q"),
    ("2Q", "2q"),
    ("3Q", "3q"),
    ("4Q", "4q"),
)


def source_period_scope(source_key: str) -> str | None:
    """Source-key period prefix (``1HSPREAD`` -> ``1h``), or None for full game."""
    needle = source_key.strip().upper()
    if not needle:
        return None
    for raw, norm in _PERIOD_PREFIXES:
        if needle == raw or (needle.startswith(raw) and len(needle) > len(raw)):
            return norm
    return None


def canonical_period_scope(canonical: str) -> str | None:
    """Period slug from canonical market type (``1h_point_spread`` -> ``1h``)."""
    lowered = canonical.strip().casefold()
    for _raw, norm in _PERIOD_PREFIXES:
        prefix = f"{norm}_"
        if lowered.startswith(prefix) or lowered == norm:
            return norm
    return None


def ai_canonical_allowed(
    cfg: Any,
    *,
    league: str,
    book: str,
    source_key: str,
    source_key_type: str,
    canonical: str,
    market_group: str,
) -> bool:
    """Reject AI picks that disagree with Python wiring or period."""
    if source_period_scope(source_key) != canonical_period_scope(canonical):
        return False
    if book == "polymarket_usa" and is_smt_rule(source_key_type):
        wired = wired_canonical(cfg, source_key)
        if wired is not None and canonical != wired:
            return False
    return True
