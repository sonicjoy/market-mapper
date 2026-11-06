"""bq_ttl_cache: each entry expires on its own TTL, not the caller's."""

from __future__ import annotations

import pytest

from mappers.control_plane import bq_ttl_cache


@pytest.fixture(autouse=True)
def _clean() -> None:
    bq_ttl_cache.clear_ttl_cache()


def _clock(monkeypatch: pytest.MonkeyPatch, start: float = 1000.0) -> list[float]:
    now = [start]
    monkeypatch.setattr(bq_ttl_cache.time, "monotonic", lambda: now[0])
    return now


def test_short_ttl_read_does_not_evict_a_longer_lived_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _clock(monkeypatch)
    calls: list[str] = []
    bq_ttl_cache.ttl_cached("vg", "catalog", lambda: calls.append("catalog") or 1, ttl=900)
    now[0] += 400  # past the 5-minute TTL, inside the 15-minute one
    bq_ttl_cache.ttl_cached("vg", "demand", lambda: calls.append("demand") or 2, ttl=300)
    assert bq_ttl_cache.ttl_cached("vg", "catalog", lambda: calls.append("catalog") or 1, ttl=900) == 1
    assert calls == ["catalog", "demand"]


def test_entry_expires_on_its_own_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _clock(monkeypatch)
    calls: list[int] = []
    bq_ttl_cache.ttl_cached("ns", "k", lambda: calls.append(1) or 1, ttl=60)
    now[0] += 61
    bq_ttl_cache.ttl_cached("ns", "k", lambda: calls.append(1) or 1, ttl=60)
    assert len(calls) == 2


def test_sweep_still_drops_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _clock(monkeypatch)
    bq_ttl_cache.ttl_cached("ns", "old", lambda: 1, ttl=60)
    now[0] += 120
    bq_ttl_cache.ttl_cached("ns", "new", lambda: 2, ttl=60)
    assert ("ns", "old") not in bq_ttl_cache._cache
