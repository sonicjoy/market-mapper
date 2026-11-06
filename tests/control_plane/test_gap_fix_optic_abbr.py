"""Harvest Optic pins when a fixture's two sides share an abbreviation."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_optic_abbr import harvest_duplicate_optic_abbrs
from tests.control_plane.gap_store_helpers import _league, _store, _team

_NANTES = "F55591A73993AEC0"
_NANCY = "2CFB9C9E1EE9DE97"


def _l2_store() -> Any:
    return _store(
        [_team("france_ligue_2", "EAG", "En Avant Guingamp")],
        [_league("france_ligue_2", "france_-_ligue_2")],
    )


def _nantes_nancy_fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "21428-79873-2026-09-07",
            "start_date": "2026-09-07T18:45:00Z",
            "home_competitors": [
                {"id": _NANTES, "name": "FC Nantes", "abbreviation": "NAN"},
            ],
            "away_competitors": [
                {
                    "id": _NANCY,
                    "name": "AS Nancy-Lorraine",
                    "abbreviation": "NAN",
                },
            ],
        },
    ]


def test_harvest_duplicate_abbr_with_empty_inventory() -> None:
    """Sweeper must run even when RFQ inventory is empty (mapper died first)."""
    result = harvest_gap_pins(
        _l2_store(),
        inventory_fn=list,
        fixtures_fn=_nantes_nancy_fixtures,
    )
    by_oid = {
        alias["alias_value"]: pin
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert by_oid[_NANCY]["canonical_key"] == "NAN"
    assert by_oid[_NANCY]["canonical_name"] == "AS Nancy-Lorraine"
    assert by_oid[_NANTES]["canonical_key"] != "NAN"
    assert by_oid[_NANTES]["aliases"][0]["alias_kind"] == "external_id"
    assert by_oid[_NANTES]["aliases"][0]["sportsbook"] == "optic"


def test_harvest_fetches_at_mapper_horizon() -> None:
    """Tip 96h must not hide Nantes vs Nancy (kickoff is 7 days out)."""
    seen: dict[str, float] = {}

    def fetch(_oid: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        seen["h"] = float(horizon_hours)
        return _nantes_nancy_fixtures()

    harvest_gap_pins(_l2_store(), inventory_fn=list, fixtures_fn=fetch)
    assert seen["h"] >= 168.0


def test_harvest_skips_when_shared_abbr_is_a_different_club() -> None:
    store = _store(
        [_team("france_ligue_2", "NAN", "Not Nancy")],
        [_league("france_ligue_2", "france_-_ligue_2")],
    )
    result = harvest_gap_pins(
        store, inventory_fn=list, fixtures_fn=_nantes_nancy_fixtures,
    )
    by_oid = {
        alias["alias_value"]: pin
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert _NANCY not in by_oid
    assert any(row.get("reason") == "name_mismatch" for row in result["skipped"])
    assert _NANTES in by_oid
    assert by_oid[_NANTES]["canonical_key"] != "NAN"


def test_harvest_duplicate_abbr_coalesces_entities_once() -> None:
    store = _l2_store()
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_duplicate_optic_abbrs(
        store, [], [], set(), fixtures_fn=_nantes_nancy_fixtures,
    )
    assert calls["n"] == 1


def test_harvest_ignores_non_soccer_leagues() -> None:
    store = _store(
        [_team("nba", "BOS", "Boston Celtics")],
        [_league("nba", "nba", sport="basketball")],
    )
    result = harvest_gap_pins(
        store, inventory_fn=list, fixtures_fn=_nantes_nancy_fixtures,
    )
    alias_pins = [p for p in result["pins"] if "aliases" in p]
    assert alias_pins == []
