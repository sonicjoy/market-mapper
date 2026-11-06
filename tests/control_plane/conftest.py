"""Keep control-plane unit tests offline from the Optic HTTP API."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_optic_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate-abbr harvest live-fetches when fixtures_fn is omitted."""
    monkeypatch.setattr(
        "mappers.control_plane.gap_optic_cache.fetch_optic_fixtures",
        lambda *_a, **_k: [],
    )


@pytest.fixture(autouse=True)
def _no_live_optic_bq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Harvest warms from opticodds_fixtures when fixtures_fn is omitted."""
    monkeypatch.setattr(
        "mappers.control_plane.gap_optic_cache._query_fixtures",
        lambda *_a, **_k: [],
    )


@pytest.fixture(autouse=True)
def _no_live_crypto_catalogue_bq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Harvest batches crypto_security_def when catalogue_fn is omitted."""
    monkeypatch.setattr(
        "mappers.control_plane.gap_crypto_catalogue._query",
        lambda *_a, **_k: [],
    )


@pytest.fixture(autouse=True)
def _pipeline_gap_suggest_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Harvest tests must not call Gemini; AI tests set the flag explicitly."""
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "0")


@pytest.fixture(autouse=True)
def us_league_events(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Offline gateway league walk for US gap events: {inner -> events}."""
    events: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly_bq.league_events",
        lambda inner: events.get(inner, []),
    )
    return events


@pytest.fixture(autouse=True)
def _no_harvest_ttl_bq(monkeypatch: pytest.MonkeyPatch) -> None:
    """CronJob TTL is BQ-backed; unit tests stay in-process."""
    from mappers.control_plane.gap_harvest_ttl import clear_ttl_mem

    clear_ttl_mem()
    monkeypatch.setattr(
        "mappers.control_plane.gap_harvest_ttl._bq_load",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "mappers.control_plane.gap_harvest_ttl._bq_save",
        lambda *_a, **_k: None,
    )
