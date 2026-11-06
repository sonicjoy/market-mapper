"""Explore -> Override patterns: repeated mapping overrides grouped into rule candidates.

An override fixes one selection in one fixture. When the same shape keeps being
overridden across fixtures, the durable fix is a rule: a market rule (venue market
type -> Optic market) or an alias (venue code -> tip entity). This module only
*groups*; drafting goes through the existing kernel in ``override_clusters_draft``.

Two cluster kinds, both counted in distinct fixtures (``game_id``), because a rule
only earns its keep when the shape repeats across games:

* ``market_rule`` - (venue, league, source_key_type, source_key, Optic market_id)
* ``alias``       - (venue, league, venue code, Optic selection name)

No venue is clustered today. Kalshi maps from its own typed fields (no tip market
rule or code alias to propose), and Prophet X overrides arrive without
``source_ids.market_id``. Every row is reported as ``unsupported_book`` rather than
silently dropped; a venue with a typed source key can add its clusterer here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MIN_GAMES = 3
SAMPLE_KEYS = 5


@dataclass
class OverrideCluster:
    """One repeated override shape, ready for drafting."""

    cluster_id: str
    kind: str
    sportsbook: str
    league: str
    optic_market_id: str
    source_key_type: str = ""
    source_key: str = ""
    code: str = ""
    selection: str = ""
    games: set[str] = field(default_factory=set)
    keys: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    active: int = 0

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view (sets sorted, keys sampled)."""
        return {
            "cluster_id": self.cluster_id,
            "kind": self.kind,
            "sportsbook": self.sportsbook,
            "league": self.league,
            "optic_market_id": self.optic_market_id,
            "source_key_type": self.source_key_type,
            "source_key": self.source_key,
            "code": self.code,
            "selection": self.selection,
            "games": len(self.games),
            "overrides": len(self.keys),
            "active": self.active,
            "sources": sorted(self.sources),
            "sample_keys": self.keys[:SAMPLE_KEYS],
        }


def cluster_id_for(kind: str, *parts: str) -> str:
    """Stable short id: kind prefix + 12 hex of the identity tuple."""
    digest = hashlib.sha1("|".join([kind, *parts]).encode("utf-8"), usedforsecurity=False)
    return f"{kind}:{digest.hexdigest()[:12]}"


def _book(row: dict[str, Any]) -> str:
    return str(row.get("sportsbook") or "").strip().lower()


def cluster_overrides(
    rows: Iterable[dict[str, Any]],
    store: Any | None,
    *,
    min_games: int = DEFAULT_MIN_GAMES,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Group override rows into rule candidates; biggest (most games) first."""
    clusters: dict[str, OverrideCluster] = {}
    unparsed: dict[str, int] = {}
    for row in rows:
        if not include_inactive and not row.get("active"):
            continue
        _ = store
        key = f"{_book(row)}:unsupported_book"
        unparsed[key] = unparsed.get(key, 0) + 1
    kept = [c for c in clusters.values() if len(c.games) >= max(1, min_games)]
    kept.sort(key=lambda c: (-len(c.games), -len(c.keys), c.cluster_id))
    return {"clusters": kept, "unparsed": unparsed}
