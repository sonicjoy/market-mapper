"""Process-local TTL memo for console BigQuery reads.

Console pages re-fetch on every filter change, tab switch and refresh; the
underlying tables move on the pipeline's 15-minute tick. Memoising the raw
result for a few minutes turns repeated page loads into one scan.

Each entry keeps its own TTL: the stale sweep on a write drops only entries past
THEIR ttl. (It used to sweep with the caller's ttl, so any 5-minute read evicted
every longer-lived entry - Venue gaps' 15-minute catalogue behaved as 5 minutes.)
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable

DEFAULT_TTL_SECONDS = 300.0

_cache: dict[tuple[str, Hashable], tuple[float, float, object]] = {}
_lock = threading.Lock()


def ttl_cached[T](namespace: str, key: Hashable, fetch: Callable[[], T], *, ttl: float = DEFAULT_TTL_SECONDS) -> T:
    """``fetch()`` memoised per (namespace, key) for ``ttl`` seconds; exceptions are never cached."""
    slot = (namespace, key)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(slot)
        if hit is not None and now - hit[0] < ttl:
            return hit[2]  # type: ignore[return-value]
    value = fetch()
    with _lock:
        _cache[slot] = (now, ttl, value)
        for stale in [k for k, (at, life, _) in _cache.items() if now - at >= life]:
            _cache.pop(stale, None)
    return value


def clear_ttl_cache(namespace: str | None = None) -> None:
    """Drop memoised results for one namespace (Refresh button), or all (tests)."""
    with _lock:
        for slot in [k for k in _cache if namespace is None or k[0] == namespace]:
            _cache.pop(slot, None)
