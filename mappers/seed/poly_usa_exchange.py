"""Polymarket US as a first-class tip exchange pin.

The US book shares the sport's Polymarket market vocabulary (see
``poly_usa_generic_v1`` in ``mappers/profiles/registry.py``) but has its own
ticker grammar and its own league code, carried as the pin's
``source_league_id`` like every other exchange.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

POLY_USA_BOOK = "polymarket_usa"
POLY_BOOK = "polymarket"

# First-time pin defaults when a league has no polymarket_usa row yet.
# Live classify still reads the legacy tip pin, not this dict. Do not add
# live RFQ remaps here or on the tip; put them in mappers/exchanges/*_leagues.py.
# US inners with no Optic book. Harvest must not unique-match these onto
# an unrelated soccer/tennis league (SETKA → norway_3_division, 2026-08-29).
NO_OPTIC_US_INNERS: frozenset[str] = frozenset({
    "setkameua", "setkamemd", "setkamecz", "modus",
})

# Live polymarketus uses one inner for more than one Optic tour. Harvest
# must walk every slug here; two owners of `atp` is not us_code_collision.
SHARED_US_INNERS: dict[str, frozenset[str]] = {
    "atp": frozenset({"atp", "atp_challenger"}),
}

US_CODE_OVERRIDES: dict[str, str] = {
    "leagues_cup": "lgscup",
    "norway_eliteserien": "nor1",
    "europa_conference_league": "uecl",
    "liga_mx": "lmx",
    "uzbekistan_super_league": "uzb1",
    "itf_women": "itfwo",
    "itf_men": "itfme",
    "uefa_womens_champions_league": "uwcl",
    "ncaaf": "cfb",
    # No Polymarket pin to inherit from (2026-09-26 Poly US wave).
    "nhl": "nhl",
    "boxing_matches": "boxing",
}


def exchange_enabled(ex: dict[str, Any]) -> bool:
    """True unless the pin is explicitly disabled."""
    return ex.get("enabled", True) is not False


def find_exchange(exchanges: list[dict[str, Any]], sportsbook: str) -> dict[str, Any] | None:
    """First exchange pin for a sportsbook, enabled or not."""
    for ex in exchanges or []:
        if str(ex.get("sportsbook") or "") == sportsbook:
            return ex
    return None


def _pin_code(ex: dict[str, Any]) -> str:
    settings = ex.get("settings") or {}
    if isinstance(settings, dict):
        slug = str(settings.get("slug_prefix") or "").strip()
        if slug:
            return slug
    return str(ex.get("source_league_id") or "").strip()


def us_league_code(row: Any) -> str:
    """Inner polymarketus code from an enabled polymarket_usa pin."""
    usa = find_exchange(getattr(row, "exchanges", None) or [], POLY_USA_BOOK)
    if usa is None or not exchange_enabled(usa):
        return ""
    return _pin_code(usa)


def leagues_with_poly_usa(rows: list[Any]) -> frozenset[str]:
    """League slugs with an enabled polymarket_usa exchange pin."""
    out: set[str] = set()
    for row in rows:
        usa = find_exchange(getattr(row, "exchanges", None) or [], POLY_USA_BOOK)
        if usa is not None and exchange_enabled(usa):
            slug = str(getattr(row, "league", "") or "")
            if slug:
                out.add(slug)
    return frozenset(out)


def us_inner_owner_ok(key: str, owners: Sequence[Any]) -> bool:
    """True when US inner owners are unique or a declared shared family."""
    if len(owners) <= 1:
        return True
    allowed = SHARED_US_INNERS.get(key.strip().casefold())
    if not allowed:
        return False
    slugs = {str(getattr(row, "league", "") or "").casefold() for row in owners}
    return bool(slugs) and slugs <= allowed


def us_inner_targets(
    key: str, owners: Sequence[Any], rows: Sequence[Any],
) -> list[Any]:
    """Tip rows harvest should walk for this US inner (includes US-off siblings)."""
    allowed = SHARED_US_INNERS.get(key.strip().casefold())
    if not allowed:
        return list(owners)
    by_slug = {
        str(getattr(row, "league", "") or "").casefold(): row
        for row in rows
        if not getattr(row, "tombstone", False)
    }
    found = [by_slug[slug] for slug in sorted(allowed) if slug in by_slug]
    return found or list(owners)


def default_us_code(row: Any, poly_ex: dict[str, Any] | None) -> str:
    """First-time US pin default: bootstrap override, else the official slug."""
    league = str(getattr(row, "league", "") or "")
    if league in US_CODE_OVERRIDES:
        return US_CODE_OVERRIDES[league]
    if poly_ex is None:
        return ""
    return _pin_code(poly_ex)
