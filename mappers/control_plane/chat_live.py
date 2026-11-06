"""TTL-cached LiveLookup wrapper for Mapper Chat / entry soft probes."""

from __future__ import annotations

import time
from typing import Any

from mappers.control_plane.entry import LiveLookup, NullLiveLookup


class CachedLiveLookup:
    """Cache LiveLookup.seen results for probe_cache_ttl_sec."""

    def __init__(self, inner: LiveLookup | None = None, *, ttl_sec: float = 900.0) -> None:
        self._inner = inner or NullLiveLookup()
        self._ttl = max(1.0, ttl_sec)
        self._cache: dict[tuple[str, str | None], tuple[float, bool]] = {}

    def seen(self, paste: str, *, sportsbook: str | None) -> bool:
        """Return cached or fresh soft live evidence."""
        key = (paste.strip(), sportsbook)
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        value = self._inner.seen(paste, sportsbook=sportsbook)
        self._cache[key] = (now, value)
        if len(self._cache) > 2000:
            self._purge(now)
        return value

    def _purge(self, now: float) -> None:
        dead = [k for k, (ts, _) in self._cache.items() if now - ts >= self._ttl]
        for k in dead:
            del self._cache[k]


class HeuristicLiveLookup:
    """Soft live seen: no venue probe is wired for crypto / Optic pastes, so miss."""

    def seen(self, paste: str, *, sportsbook: str | None) -> bool:
        _ = (paste, sportsbook)
        return False


def build_chat_live_lookup(settings: Any) -> LiveLookup:
    """Production chat live lookup: heuristic inner + TTL cache."""
    ttl = float(getattr(settings, "probe_cache_ttl_sec", 900) or 900)
    return CachedLiveLookup(HeuristicLiveLookup(), ttl_sec=ttl)
