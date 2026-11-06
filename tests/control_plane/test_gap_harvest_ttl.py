"""24h harvest TTL (in-process; BQ stubbed by conftest)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from mappers.control_plane.gap_harvest_ttl import (
    DEAD_BUCKETS,
    OPTIC_SKIPPED,
    POLY_US_EVENTS,
    TTL_SEC,
    clear_ttl_mem,
    load_dead_buckets,
    load_optic_skips,
    load_str_list,
    load_ttl,
    optic_skip_blocks,
    remember_optic_skips,
    save_dead_buckets,
    save_str_list,
    save_ttl,
)


def test_str_list_round_trip() -> None:
    save_str_list("tmp_list", {"aaa", "bbb"})
    assert set(load_str_list("tmp_list")) == {"aaa", "bbb"}


def test_dead_buckets_union_by_book() -> None:
    save_dead_buckets("kalshi", {"kalshi:KXITF"})
    save_dead_buckets("kalshi", {"kalshi:KXNFL"})
    save_dead_buckets("crypto", {"crypto:FIFA"})
    assert load_dead_buckets("kalshi") == {"kalshi:KXITF", "kalshi:KXNFL"}
    assert load_dead_buckets("crypto") == {"crypto:FIFA"}


def test_dead_bucket_does_not_refresh_expiry(monkeypatch: object) -> None:
    t0 = time.time()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "mappers.control_plane.gap_harvest_ttl.time.time",
        lambda: t0,
    )
    save_dead_buckets("kalshi", {"kalshi:KXITF"})
    first = load_ttl(DEAD_BUCKETS)["kalshi"]["kalshi:KXITF"]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "mappers.control_plane.gap_harvest_ttl.time.time",
        lambda: t0 + 60,
    )
    save_dead_buckets("kalshi", {"kalshi:KXITF"})
    assert load_ttl(DEAD_BUCKETS)["kalshi"]["kalshi:KXITF"] == first


def test_optic_skip_reopens_six_hours_before_kickoff() -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    far = "2026-12-01T14:00:00Z"
    remember_optic_skips({"oid-1": far}, now)
    skips = load_optic_skips()
    assert optic_skip_blocks("oid-1", far, skips, now)
    near = (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert not optic_skip_blocks("oid-1", near, skips, now)
    remember_optic_skips({"oid-1": near}, now)
    assert "oid-1" not in load_optic_skips()
    assert OPTIC_SKIPPED


def test_poly_events_blob() -> None:
    save_ttl(POLY_US_EVENTS, {"prefixes": ["mlb"], "events": [{"inner": "mlb"}]})
    blob = load_ttl(POLY_US_EVENTS)
    assert blob["prefixes"] == ["mlb"]


def test_expired_mem_is_gone(monkeypatch: object) -> None:
    save_ttl("tmp", {"ok": True})
    assert load_ttl("tmp") == {"ok": True}
    now = time.time()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "mappers.control_plane.gap_harvest_ttl.time.time",
        lambda: now + TTL_SEC + 1,
    )
    assert load_ttl("tmp") is None
    clear_ttl_mem()


def test_clear_drops_dead_buckets() -> None:
    save_dead_buckets("kalshi", {"kalshi:KXITF"})
    clear_ttl_mem()
    assert load_dead_buckets("kalshi") == set()
    assert DEAD_BUCKETS
