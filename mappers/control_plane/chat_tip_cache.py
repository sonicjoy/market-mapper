"""Process-local cache for tip league slugs (keyed by rule_set_id)."""

from __future__ import annotations

import threading
import time
from typing import Any

_TTL_SEC = 300.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, set[str]]] = {}


def tip_league_slugs(store: Any) -> set[str]:
    """COW-read league slugs once per tip id."""
    rid = getattr(store, "current_rule_set_id", None) or ""
    if not rid:
        return set()
    now = time.time()
    with _lock:
        hit = _cache.get(rid)
        if hit and now - hit[0] < _TTL_SEC:
            return set(hit[1])
    slugs = {row.league for row in store.leagues_for(rid)}
    with _lock:
        _cache[rid] = (now, slugs)
    return slugs


def cached_tip_league_slugs() -> set[str]:
    """Slugs already read from a tip this process, for callers with no store."""
    now = time.time()
    with _lock:
        return {
            slug
            for stamped, slugs in _cache.values()
            if now - stamped < _TTL_SEC
            for slug in slugs
        }


def clear_tip_league_cache() -> None:
    """Test helper — drop cached slugs when the tip row set changes under one id."""
    with _lock:
        _cache.clear()
