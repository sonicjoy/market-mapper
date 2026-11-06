"""Explore-console platform registry (Unmapped, Missing, filters).

One row per operator-facing platform id (URL / API ``platform`` param).
``sportsbook`` is the canonical ``market_mapping.sportsbook`` value when
different from ``id`` (e.g. explore id ``crypto`` → ``crypto.com``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Keep sportsbook keys aligned with chat_profiles.CHAT_SPORTSBOOKS /
# console/src/entryEnums.ts SPORTSBOOKS when adding a book.


@dataclass(frozen=True, slots=True)
class ExplorePlatform:
    id: str
    label: str
    sportsbook: str
    unmapped_inventory: bool = False
    missing_catalogue: bool = False


_EXPLORE: tuple[ExplorePlatform, ...] = (
    ExplorePlatform(
        id="kalshi",
        label="Kalshi",
        sportsbook="Kalshi",
        unmapped_inventory=True,
    ),
    ExplorePlatform(
        id="crypto",
        label="crypto.com",
        sportsbook="crypto.com",
        unmapped_inventory=True,
        missing_catalogue=True,
    ),
    ExplorePlatform(
        id="polymarket",
        label="Polymarket",
        sportsbook="Polymarket",
        unmapped_inventory=True,
    ),
    ExplorePlatform(
        id="polymarket_usa",
        label="Polymarket US",
        sportsbook="Polymarket (USA)",
    ),
    ExplorePlatform(
        id="px",
        label="ProphetX",
        sportsbook="Prophet X",
    ),
    ExplorePlatform(
        id="novig",
        label="Novig",
        sportsbook="Novig",
    ),
    ExplorePlatform(
        id="underdog",
        label="Underdog",
        sportsbook="Underdog",
        unmapped_inventory=True,
    ),
    ExplorePlatform(
        id="dkex",
        label="DraftKings Exchange",
        sportsbook="DKEX",
        unmapped_inventory=True,
    ),
    # SX: Unmapped rows come from rfq_latest + SX's public catalogue for titles.
    # No Missing: SX's whole book is not in a dataset this service reads.
    ExplorePlatform(
        id="sxbet",
        label="SX Bet",
        sportsbook="SX Bet",
        unmapped_inventory=True,
    ),
    ExplorePlatform(
        id="optic",
        label="Optic",
        sportsbook="optic",
    ),
    # Scores feed, not a venue: its Missing catalogue is TxODDS NBA fixtures with no single Optic match.
    ExplorePlatform(
        id="txodds",
        label="TxODDS",
        sportsbook="txodds",
        missing_catalogue=True,
    ),
)


def explore_platforms() -> tuple[ExplorePlatform, ...]:
    """All explore-console platform registry rows."""
    return _EXPLORE


def explore_platform(platform_id: str) -> ExplorePlatform | None:
    """Lookup one platform by explore id (URL / API param)."""
    want = (platform_id or "").strip().lower()
    if not want:
        return None
    for row in _EXPLORE:
        if row.id == want:
            return row
    return None


def explore_platforms_payload() -> list[dict[str, Any]]:
    """Serialize registry for GET /meta ``explore_platforms``."""
    return [
        {
            "id": row.id,
            "label": row.label,
            "sportsbook": row.sportsbook,
            "unmapped_inventory": row.unmapped_inventory,
            "missing_catalogue": row.missing_catalogue,
        }
        for row in _EXPLORE
    ]


def default_missing_platform_id() -> str:
    """First platform with ``missing_catalogue`` wired (crypto.com today)."""
    for row in _EXPLORE:
        if row.missing_catalogue:
            return row.id
    return _EXPLORE[0].id
