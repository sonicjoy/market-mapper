"""Once-per-league Optic fixture cache."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from mappers.control_plane import gap_optic_cache as mod
from mappers.control_plane.gap_fix_poly import load_poly_side_inputs
from mappers.control_plane.gap_optic_cache import (
    cached_optic_fixtures,
    clear_optic_cache,
    load_optic_fixtures_from_bq,
    tip_optic_keys,
    warm_optic_cache,
)
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.store import InMemoryStore
from mappers.shared import FIXTURE_HORIZON_HOURS
from tests.control_plane.test_gap_fix import _store
from tests.control_plane.test_gap_fix_poly_official import _poly_official_league


def test_injected_fetch_fn_is_not_cached() -> None:
    clear_optic_cache()
    calls: list[str] = []

    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        _ = horizon_hours
        calls.append(optic_id)
        return [{"id": "fx-1"}]

    assert cached_optic_fixtures("liga", horizon_hours=96.0, fetch_fn=fetch)
    assert cached_optic_fixtures("liga", horizon_hours=96.0, fetch_fn=fetch)
    assert calls == ["liga", "liga"]
    assert mod._CACHE == {}


def test_live_fetch_cached_once(monkeypatch: Any) -> None:
    clear_optic_cache()
    calls: list[str] = []

    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        _ = horizon_hours
        calls.append(optic_id)
        return [{"id": "fx-live"}]

    monkeypatch.setattr(mod, "fetch_optic_fixtures", fetch)
    a = cached_optic_fixtures("ncaaf", horizon_hours=168.0)
    b = cached_optic_fixtures("ncaaf", horizon_hours=168.0)
    assert a == b == [{"id": "fx-live"}]
    assert calls == ["ncaaf"]


def test_narrower_horizon_reuses_wider_cache(monkeypatch: Any) -> None:
    clear_optic_cache()
    calls: list[float] = []

    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        calls.append(float(horizon_hours))
        return [{
            "id": "fx-close",
            "start_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "league": {"id": optic_id},
        }]

    monkeypatch.setattr(mod, "fetch_optic_fixtures", fetch)
    cached_optic_fixtures("ncaaf", horizon_hours=168.0)
    sliced = cached_optic_fixtures("ncaaf", horizon_hours=72.0)
    assert calls == [168.0]
    assert sliced[0]["id"] == "fx-close"


def test_bq_load_fills_cache_http_shape() -> None:
    clear_optic_cache()
    start = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
    row = SimpleNamespace(
        fixture_id="fx-1",
        game_id="g-1",
        start_date=start,
        optic_league_id="ncaaf",
        home_competitors=[{"id": "H1", "name": "Home", "abbreviation": "HOM"}],
        away_competitors=[{"id": "A1", "name": "Away", "abbreviation": "AWY"}],
    )
    n = load_optic_fixtures_from_bq(
        [("ncaaf", 96.0)],
        query_fn=lambda _sql, _ids, _fwd: [row],
        now=start,
    )
    assert n == 1
    games = cached_optic_fixtures("ncaaf", horizon_hours=96.0)
    assert games[0]["id"] == "fx-1"
    assert games[0]["league"] == {"id": "ncaaf"}
    assert games[0]["home_competitors"][0]["name"] == "Home"


def test_load_poly_side_inputs_uses_optic_window_not_harvest_cache(
    monkeypatch: Any,
) -> None:
    """Poly matcher needs ±10d all-league rows; harvest cache is tip/horizon only."""
    clear_optic_cache()
    start = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
    row = SimpleNamespace(
        fixture_id="fx-1",
        game_id="g-1",
        start_date=start,
        optic_league_id="ncaaf",
        home_competitors=[{"id": "H1", "name": "Home", "abbreviation": "HOM"}],
        away_competitors=[{"id": "A1", "name": "Away", "abbreviation": "AWY"}],
    )
    load_optic_fixtures_from_bq(
        [("ncaaf", 96.0)],
        query_fn=lambda _sql, _ids, _fwd: [row],
        now=start,
    )
    window = [{"optic_league_id": "ncaaf", "fixture_id": "from-window", "sport": "football"}]
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly.fetch_optic_window",
        lambda **_k: window,
    )
    _events, _official, optic_rows = load_poly_side_inputs(["ncaaf"], list, list, None)
    assert optic_rows == window


def test_load_poly_side_wired_filters_optic_ids(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake(*, optic_ids: list[str] | None = None, **_k: object) -> list[object]:
        captured["optic_ids"] = optic_ids
        return []

    monkeypatch.setattr("mappers.control_plane.gap_fix_poly.fetch_optic_window", fake)
    store = _store([], [_poly_official_league("la_liga", "spain_-_la_liga", "spa")])
    load_poly_side_inputs(["spa"], list, list, None, store=store)
    assert captured["optic_ids"] == ["spain_-_la_liga"]


def test_load_poly_side_unwired_full_optic_window(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake(*, optic_ids: list[str] | None = None, **_k: object) -> list[object]:
        captured["optic_ids"] = optic_ids
        return []

    monkeypatch.setattr("mappers.control_plane.gap_fix_poly.fetch_optic_window", fake)
    store = _store([], [_poly_official_league("la_liga", "spain_-_la_liga", "spa")])
    load_poly_side_inputs(["zzz"], list, list, None, store=store)
    assert captured["optic_ids"] is None


def test_bq_miss_falls_back_to_http(monkeypatch: Any) -> None:
    clear_optic_cache()
    calls: list[str] = []

    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        _ = horizon_hours
        calls.append(optic_id)
        return [{"id": "http-1"}]

    monkeypatch.setattr(mod, "fetch_optic_fixtures", fetch)
    store = _one_league_store("ncaaf")
    warm_optic_cache(store, query_fn=lambda *_a: [])
    assert calls == ["ncaaf"]
    assert cached_optic_fixtures("ncaaf", horizon_hours=FIXTURE_HORIZON_HOURS) == [{"id": "http-1"}]


def test_warm_skips_when_fetch_fn_injected() -> None:
    clear_optic_cache()
    store = _one_league_store("ncaaf")
    warm_optic_cache(store, fetch_fn=lambda *_a, **_k: [{"id": "stub"}])
    assert mod._CACHE == {}


def test_tip_optic_keys_includes_extras() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[_league("epl", "epl", extra=["epl2"])],
        activate=True,
    )
    keys = dict(tip_optic_keys(store))
    assert keys["epl"] == FIXTURE_HORIZON_HOURS
    assert keys["epl2"] == FIXTURE_HORIZON_HOURS


def _one_league_store(optic: str) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0", entities=[], leagues=[_league("lg", optic)], activate=True)
    return store


def _league(slug: str, optic: str, extra: list[str] | None = None) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport="soccer",
        optic_league_id=optic,
        extra_optic_league_ids=extra or [],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[],
    )
