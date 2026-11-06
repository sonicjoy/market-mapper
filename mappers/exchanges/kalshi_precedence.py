"""Which Kalshi ticker keeps an Optic row when two series map the same line.

``KXNFLPASSYDSPRECISE`` rungs land on the same (player, line, side) key as
``KXNFLPASSYDS``; the merge in ``pipeline.run`` is last-write-wins, so the
precise ticker used to displace the regular one on shared lines. A scope in
``SECONDARY_SCOPES`` never replaces a ticker already on the row.
"""

from __future__ import annotations

from typing import Any

# Kalshi event scopes whose series duplicate a primary series' lines.
SECONDARY_SCOPES: frozenset[str] = frozenset({"Passing Yards Range"})


def keeps_existing(existing: Any, incoming: Any) -> bool:
    """True when ``incoming`` is secondary and the row already has a ticker."""
    return (
        existing.kalshi_ticker is not None
        and incoming.kalshi_scope in SECONDARY_SCOPES
        and existing.kalshi_scope not in SECONDARY_SCOPES
    )
