"""Which venues a bulk override may target, and how each venue's source ids are shaped.

fold+rank keys an ``opticodds_mapping`` row on
``lower(sportsbook)|source_ids.market_id|source_ids.selection_id``
(``BigQuery/sql/oom_fold_rank.sql``), so an override only competes with the
venue's own row when its ``source_ids`` carry exactly the fields that venue's
rows carry. Shapes below were read from live ``opticodds_mapping`` rows
(2026-09-26) and match MMutils ``handlers/mapping_keys.py`` row keys:

- Kalshi       ``{market_id: <ticker>, selection_id: yes|no}``
- Polymarket   ``{selection_id: <clob token>}`` (no market_id)
- Prophet X    ``{event_id, selection_id}`` (market_id absent from the key)
- Novig        ``{event_id, market_id, selection_id}``
- SX Bet       ``{event_id, market_id: <hash>, selection_id: <hash>|<side>}``

crypto.com and Polymarket (USA) consumers do not read ``opticodds_mapping``
at all (MMutils ``handlers/mapping_registry.py`` marks both ``blocked``;
mmcryptocom ``MappingService.java`` reads ``markets_us.market_mapping`` by
symbol), so an override there is accepted and changes nothing (mmmapper#19).

Only Kalshi carries overrides at all (902 rows in opticodds_mapping in the
30 days to 2026-09-26, from scripts and mm-synthetic; 0 for every other venue),
so the other shapes are unproven and bulk publish stays Kalshi-only until
``MAPPING_BULK_OVERRIDE_VENUES`` names them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from mappers.control_plane.console_sportsbook import sportsbook_lower

_ENABLED_ENV = "MAPPING_BULK_OVERRIDE_VENUES"
_DEFAULT_ENABLED = ("kalshi",)

# Sportsbooks whose consumer does not read opticodds_mapping. Unify with the
# Catalog guard's constant (mmmapper#19) when both branches land.
OVERRIDE_UNREAD_SPORTSBOOKS: dict[str, str] = {
    "crypto.com": (
        "crypto.com maps legs from markets_us.market_mapping by symbol and never reads "
        "opticodds_mapping, so an override changes nothing (mmmapper#19, mmcryptocom#22)."
    ),
    "polymarket (usa)": (
        "Polymarket (USA) is blocked from the opticodds_mapping cache (MMutils "
        "mapping_registry), so an override is not read (mmmapper#19)."
    ),
}


@dataclass(frozen=True)
class VenueShape:
    """Which ``source_ids`` fields a venue's rank key uses."""

    sportsbook: str
    uses_market_id: bool
    uses_selection_id: bool


VENUE_SHAPES: dict[str, VenueShape] = {
    "kalshi": VenueShape("Kalshi", uses_market_id=True, uses_selection_id=True),
    "polymarket": VenueShape("Polymarket", uses_market_id=False, uses_selection_id=True),
    "prophet x": VenueShape("Prophet X", uses_market_id=False, uses_selection_id=True),
    "novig": VenueShape("Novig", uses_market_id=True, uses_selection_id=True),
    "sx bet": VenueShape("SX Bet", uses_market_id=True, uses_selection_id=True),
}


def enabled_venues() -> frozenset[str]:
    """Lower-cased sportsbooks bulk publish may target (env override, default Kalshi)."""
    raw = (os.environ.get(_ENABLED_ENV) or "").strip()
    names = [part for part in raw.split(",") if part.strip()] if raw else list(_DEFAULT_ENABLED)
    return frozenset(sportsbook_lower(name.strip()) for name in names)


def venue_block_reason(sportsbook: str) -> str | None:
    """Why bulk override is refused for this sportsbook, or None when allowed."""
    if not (sportsbook or "").strip():
        return "sportsbook is required"
    key = sportsbook_lower(sportsbook)
    if key in OVERRIDE_UNREAD_SPORTSBOOKS:
        return OVERRIDE_UNREAD_SPORTSBOOKS[key]
    if key not in VENUE_SHAPES:
        return f"bulk override has no source-id shape for {sportsbook!r}"
    shape = VENUE_SHAPES[key]
    if not shape.uses_market_id:
        return (
            f"{shape.sportsbook} rows carry no source_ids.market_id, and the console override "
            "builder requires one; overriding it needs that builder changed first (mmmapper#21)"
        )
    if key not in enabled_venues():
        return (
            f"bulk override is not enabled for {shape.sportsbook}: no console override has ever "
            f"been verified there (set {_ENABLED_ENV} to opt in)"
        )
    return None


def shaped_source_ids(sportsbook: str, market_id: str, selection_id: str) -> tuple[str, str]:
    """(market_id, selection_id) as the venue's own rows carry them; unused fields blank."""
    shape = VENUE_SHAPES[sportsbook_lower(sportsbook)]
    market = market_id.strip() if shape.uses_market_id else ""
    selection = selection_id.strip() if shape.uses_selection_id else ""
    return market, selection
