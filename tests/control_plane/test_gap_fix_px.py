"""Harvest PX abbreviation pins when Optic fixture names uniquely match."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_px import harvest_px_code_misses
from tests.control_plane.gap_store_helpers import _league, _store, _team

_HULL_OID = "8CCE04981270F895"
_AVL_OID = "AVL1111AVL1111AV"
_PX_TID = "84"


def _epl_store(*, hul_on_hca7: bool = False, hul_on_other: bool = False) -> Any:
    hull = _team("epl", "HCA7", "Hull City AFC")
    hull.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _HULL_OID},
    )
    if hul_on_hca7:
        hull.aliases.append(
            {"sportsbook": "px", "alias_kind": "code", "alias_value": "HUL"},
        )
    villa = _team("epl", "AVL", "Aston Villa FC")
    villa.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _AVL_OID},
    )
    extra = []
    if hul_on_other:
        other = _team("epl", "OTH", "Other Town")
        other.aliases.append(
            {"sportsbook": "px", "alias_kind": "code", "alias_value": "HUL"},
        )
        extra.append(other)
    lg = _league("epl", "england_-_premier_league")
    lg.exchanges.append({
        "sportsbook": "px",
        "enabled": True,
        "parser_profile": "px_generic_v1",
        "source_league_id": None,
        "settings": {"tournament_id": int(_PX_TID)},
    })
    return _store([hull, villa, *extra], [lg])


def _villa_hull_fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "epl-fx-1",
            "start_date": "2026-09-05T16:30:00Z",
            "league": {"id": "england_-_premier_league"},
            "home_competitors": [
                {
                    "id": _HULL_OID,
                    "name": "Hull City AFC",
                    "abbreviation": "HCA7",
                },
            ],
            "away_competitors": [
                {
                    "id": _AVL_OID,
                    "name": "Aston Villa FC",
                    "abbreviation": "AVL",
                },
            ],
        },
    ]


def _px_events(_tid: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": 90114098,
            "scheduled": "2026-09-05T16:30:00Z",
            "competitors": [
                {
                    "id": 1,
                    "abbreviation": "HUL",
                    "name": "Hull City AFC",
                    "side": "home",
                },
                {
                    "id": 2,
                    "abbreviation": "AVL",
                    "name": "Aston Villa FC",
                    "side": "away",
                },
            ],
        },
    ]


def test_harvest_px_hul_with_empty_inventory() -> None:
    """Sweeper must draft PX 3-letter vs Optic 4-char when RFQ is empty."""
    result = harvest_gap_pins(
        _epl_store(),
        inventory_fn=list,
        fixtures_fn=_villa_hull_fixtures,
        px_events_fn=_px_events,
    )
    by_code = {
        alias["alias_value"]: pin
        for pin in result["pins"]
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "px"
    }
    assert by_code["HUL"]["canonical_key"] == "HCA7"
    assert by_code["HUL"]["canonical_name"] == "Hull City AFC"
    assert "px:abbr:HUL" in by_code["HUL"]["evidence_refs"]
    assert "px:event:90114098" in by_code["HUL"]["evidence_refs"]
    assert any(
        ref.startswith("optic:competitor:") and "Hull City" in ref
        for ref in by_code["HUL"]["evidence_refs"]
    )


def test_harvest_px_drafts_when_optic_id_locked_despite_stale_name() -> None:
    hull = _team("epl", "HCA7", "Hull Tigers")
    hull.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _HULL_OID},
    )
    villa = _team("epl", "AVL", "Aston Villa FC")
    villa.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _AVL_OID},
    )
    lg = _league("epl", "england_-_premier_league")
    lg.exchanges.append({
        "sportsbook": "px",
        "enabled": True,
        "parser_profile": "px_generic_v1",
        "source_league_id": None,
        "settings": {"tournament_id": int(_PX_TID)},
    })
    store = _store([hull, villa], [lg])
    result = harvest_gap_pins(
        store,
        inventory_fn=list,
        fixtures_fn=_villa_hull_fixtures,
        px_events_fn=_px_events,
    )
    by_code = {
        alias["alias_value"]: pin
        for pin in result["pins"]
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "px"
    }
    assert by_code["HUL"]["canonical_key"] == "HCA7"
    assert by_code["HUL"]["canonical_name"] == "Hull City AFC"
    assert not any(row.get("reason") == "name_mismatch" for row in result["skipped"])


def test_harvest_skips_px_code_already_on_owner() -> None:
    result = harvest_gap_pins(
        _epl_store(hul_on_hca7=True),
        inventory_fn=list,
        fixtures_fn=_villa_hull_fixtures,
        px_events_fn=_px_events,
    )
    px_codes = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "px"
    }
    assert "HUL" not in px_codes


def test_harvest_skips_px_collision() -> None:
    result = harvest_gap_pins(
        _epl_store(hul_on_other=True),
        inventory_fn=list,
        fixtures_fn=_villa_hull_fixtures,
        px_events_fn=_px_events,
    )
    px_codes = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "px"
    }
    assert "HUL" not in px_codes
    assert any(row.get("reason") == "collision" for row in result["skipped"])


def test_harvest_ignores_leagues_without_px() -> None:
    store = _store(
        [_team("nba", "BOS", "Boston Celtics")],
        [_league("nba", "nba", sport="basketball")],
    )
    result = harvest_gap_pins(
        store, inventory_fn=list, fixtures_fn=_villa_hull_fixtures,
        px_events_fn=_px_events,
    )
    px_codes = {
        alias["alias_value"]
        for pin in result["pins"]
        if "aliases" in pin
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "px"
    }
    assert "HUL" not in px_codes


def test_harvest_px_coalesces_entities_once() -> None:
    store = _epl_store()
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_px_code_misses(
        store, [], [], set(),
        px_events_fn=_px_events, fixtures_fn=_villa_hull_fixtures,
    )
    assert calls["n"] == 1
