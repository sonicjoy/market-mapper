"""Sportsbooks whose quoting service does not read ``opticodds_mapping``.

A console ``mapping_override`` materialises into ``opticodds_us.opticodds_mapping``.
These venues map legs from ``markets_us.market_mapping`` instead, so an active
override there reports ``materialised`` while quoting is unchanged. Publishing
one is refused; deactivating one (cleanup) stays allowed.

While ``MAPPING_OVERRIDE_LANE`` covers a venue (``console_override_lane.lane_venue``),
its overrides reach ``market_mapping`` through the pipeline lane (mmmapper#24), so
the venue is no longer blocked here.

Mirrors the ``blocked`` rows of MMutils ``handlers/mapping_registry.py``. Remove a
row only when that venue's consumer reads the opticodds_mapping cache.
"""

from __future__ import annotations

from mappers.control_plane.console_override_lane import lane_venue
from mappers.control_plane.console_sportsbook import canonical_sportsbook

_UNREAD_BY_LOWER: dict[str, str] = {
    "crypto.com": (
        "crypto.com maps legs from markets_us.market_mapping by source_ids.symbol "
        "(mmcryptocom MappingService), not opticodds_mapping, so this override would change nothing. "
        "Fix the gap with a rule (Editor / Venue gaps) until mmcryptocom#22 lands."
    ),
    "polymarket (usa)": (
        "Polymarket (USA) builds its mapping store from markets_us.market_mapping "
        "(mmpolymarketusrfq mapping_lever), not opticodds_mapping, so this override would change nothing. "
        "Fix the gap with a rule (Editor) instead."
    ),
}


def override_unread_reason(sportsbook: str) -> str | None:
    """Why an active override for ``sportsbook`` would be a no-op, or None when it is read."""
    try:
        key = canonical_sportsbook(sportsbook).lower()
    except ValueError:
        return None
    if lane_venue(sportsbook):
        return None
    return _UNREAD_BY_LOWER.get(key)


def override_unread_sportsbooks() -> dict[str, str]:
    """Canonical sportsbook name -> reason, for the console shell (``/meta``)."""
    return {
        canonical_sportsbook(key): reason for key, reason in _UNREAD_BY_LOWER.items() if not lane_venue(key)
    }
