"""Harvest Optic abbrs as Poly USA / PX codes on longer canonicals (never Kalshi)."""

from __future__ import annotations

from typing import Any

import pytest

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_optic_abbr_codes import harvest_optic_abbr_codes
from mappers.control_plane.rows import LeagueRow
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK
from tests.control_plane.gap_harvest_clock import freeze_gap_harvest_clock
from tests.control_plane.gap_store_helpers import _league, _store, _team


@pytest.fixture(autouse=True)
def _gap_harvest_close_day(monkeypatch: Any) -> None:
    freeze_gap_harvest_clock(monkeypatch)


_BBR_OID = "ADECC2B714ED0001"
_POR_OID = "POR1111POR1111PO"


def _champ_store(
    *,
    bbr_on_other: bool = False,
    bbr_on_owner: bool = False,
    extra_teams: list[Any] | None = None,
) -> Any:
    blackburn = _team("england_championship", "BRF8", "Blackburn Rovers")
    blackburn.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _BBR_OID},
    )
    if bbr_on_owner:
        blackburn.aliases.append(
            {"sportsbook": POLY_USA_BOOK, "alias_kind": "code", "alias_value": "BBR"},
        )
    portsmouth = _team("england_championship", "POR", "Portsmouth")
    portsmouth.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _POR_OID},
    )
    extra = []
    if bbr_on_other:
        other = _team("england_championship", "OTH", "Other Town")
        other.aliases.append(
            {"sportsbook": POLY_USA_BOOK, "alias_kind": "code", "alias_value": "BBR"},
        )
        extra.append(other)
    lg = _league("england_championship", "england_-_championship")
    lg.exchanges.append({
        "sportsbook": POLY_USA_BOOK,
        "enabled": True,
        "parser_profile": "poly_usa_generic_v1",
        "source_league_id": "eflch",
        "settings": {},
    })
    return _store([blackburn, portsmouth, *extra, *(extra_teams or [])], [lg])


def _fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "elc-fx-1",
            "start_date": "2026-09-19T14:00:00Z",
            "league": {"id": "england_-_championship"},
            "home_competitors": [
                {"id": _POR_OID, "name": "Portsmouth", "abbreviation": "POR"},
            ],
            "away_competitors": [
                {
                    "id": _BBR_OID,
                    "name": "Blackburn Rovers",
                    "abbreviation": "BBR",
                },
            ],
        },
    ]


def test_harvest_optic_abbr_code_with_empty_inventory() -> None:
    result = harvest_gap_pins(
        _champ_store(),
        inventory_fn=list,
        fixtures_fn=_fixtures,
        px_events_fn=lambda _tid: [],
    )
    pins = [
        pin for pin in result["pins"]
        if pin["canonical_key"] == "BRF8"
        and any(a.get("alias_value") == "BBR" for a in pin["aliases"])
    ]
    assert len(pins) == 1
    books = {a["sportsbook"] for a in pins[0]["aliases"]}
    assert books == {POLY_USA_BOOK}
    assert "optic:abbr:BBR" in pins[0]["evidence_refs"]


def test_harvest_skips_optic_abbr_already_on_owner() -> None:
    result = harvest_gap_pins(
        _champ_store(bbr_on_owner=True),
        inventory_fn=list,
        fixtures_fn=_fixtures,
        px_events_fn=lambda _tid: [],
    )
    usa_bbr = [
        a["alias_value"]
        for pin in result["pins"]
        for a in pin["aliases"]
        if a.get("sportsbook") == POLY_USA_BOOK and a.get("alias_value") == "BBR"
    ]
    assert usa_bbr == []


def test_harvest_abbr_skips_far_fixtures() -> None:
    far = {
        "id": "elc-fx-far",
        "start_date": "2026-10-30T14:00:00Z",
        "league": {"id": "england_-_championship"},
        "home_competitors": [
            {"id": "MIL1111MIL1111MI", "name": "Millwall", "abbreviation": "MIL"},
        ],
        "away_competitors": [
            {"id": _POR_OID, "name": "Portsmouth", "abbreviation": "POR"},
        ],
    }
    millwall = _team("england_championship", "MFI2", "Millwall")
    millwall.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "MIL1111MIL1111MI"},
    )
    store = _champ_store(extra_teams=[millwall])

    def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [*_fixtures(), far]

    result = harvest_gap_pins(
        store,
        inventory_fn=list,
        fixtures_fn=fixtures,
        px_events_fn=lambda _tid: [],
    )
    abbrs = {
        a["alias_value"]
        for pin in result["pins"]
        for a in pin["aliases"]
        if a.get("alias_kind") == "code"
    }
    assert "BBR" in abbrs
    assert "MIL" not in abbrs


def test_harvest_abbr_skips_person_leagues() -> None:
    player = _team("atp", "RIND2", "Arthur Rinderknech")
    player.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OIDATP1"},
    )
    lg = _league("atp", "atp", sport="tennis")
    store = _store([player], [lg])
    fixtures = [{
        "id": "atp-fx-1",
        "start_date": "2026-09-19T12:00:00Z",
        "league": {"id": "atp"},
        "home_competitors": [
            {"id": "OIDATP1", "name": "Arthur Rinderknech", "abbreviation": "RIN"},
        ],
        "away_competitors": [
            {"id": "OTHER", "name": "Other Player", "abbreviation": "OTH"},
        ],
    }]
    pins: list[dict[str, Any]] = []
    harvest_optic_abbr_codes(
        store, pins, [], set(),
        fixtures_fn=lambda *_a, **_k: fixtures,
    )
    assert pins == []


def test_harvest_abbr_coalesces_entities_once() -> None:
    store = _champ_store()
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_optic_abbr_codes(
        store, [], [], set(), fixtures_fn=_fixtures,
    )
    assert calls["n"] == 1


def test_harvest_abbr_drafts_when_optic_id_locked_despite_stale_name() -> None:
    blackburn = _team("england_championship", "BRF8", "Blackburn")
    blackburn.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _BBR_OID},
    )
    portsmouth = _team("england_championship", "POR", "Portsmouth")
    portsmouth.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _POR_OID},
    )
    lg = _league("england_championship", "england_-_championship")
    lg.exchanges.append({
        "sportsbook": POLY_USA_BOOK,
        "enabled": True,
        "parser_profile": "poly_usa_generic_v1",
        "source_league_id": "eflch",
        "settings": {},
    })
    store = _store([blackburn, portsmouth], [lg])
    result = harvest_gap_pins(
        store,
        inventory_fn=list,
        fixtures_fn=_fixtures,
        px_events_fn=lambda _tid: [],
    )
    pins = [
        pin for pin in result["pins"]
        if pin["canonical_key"] == "BRF8"
        and any(a.get("alias_value") == "BBR" for a in pin["aliases"])
    ]
    assert len(pins) == 1
    assert pins[0]["canonical_name"] == "Blackburn Rovers"
    assert not any(row.get("reason") == "name_mismatch" for row in result["skipped"])


def test_harvest_never_drafts_kalshi_codes() -> None:
    che_oid = "CHEOIDCHEOIDCHEO"
    lyon_oid = "LYOOIDLYOOIDLYOO"
    chelsea = _team("uefa_womens_champions_league", "CHEF1", "Chelsea W")
    chelsea.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": che_oid},
    )
    lyon = _team("uefa_womens_champions_league", "LYO", "Lyon W")
    lyon.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": lyon_oid},
    )
    lg = LeagueRow(
        league="uefa_womens_champions_league",
        sport="soccer",
        optic_league_id="uefa_-_womens_champions_league",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "kalshi",
                "enabled": True,
                "parser_profile": "kalshi_generic_v1",
                "source_league_id": None,
                "settings": {},
            },
            {
                "sportsbook": POLY_USA_BOOK,
                "enabled": True,
                "parser_profile": "poly_usa_generic_v1",
                "source_league_id": "uwcl",
                "settings": {},
            },
        ],
    )
    store = _store([chelsea, lyon], [lg])
    fixtures = [{
        "id": "uwcl-fx-1",
        "start_date": "2026-09-19T14:00:00Z",
        "league": {"id": "uefa_-_womens_champions_league"},
        "home_competitors": [
            {"id": che_oid, "name": "Chelsea W", "abbreviation": "CHE"},
        ],
        "away_competitors": [
            {"id": lyon_oid, "name": "Lyon W", "abbreviation": "LYO"},
        ],
    }]
    result = harvest_gap_pins(
        store,
        inventory_fn=list,
        fixtures_fn=lambda *_a, **_k: fixtures,
        px_events_fn=lambda _tid: [],
    )
    kalshi = [
        a["alias_value"]
        for pin in result["pins"]
        for a in pin["aliases"]
        if a.get("sportsbook") == "kalshi"
    ]
    assert kalshi == []
    poly = [
        a["alias_value"]
        for pin in result["pins"]
        for a in pin["aliases"]
        if a.get("sportsbook") == POLY_USA_BOOK and a.get("alias_value") == "CHE"
    ]
    assert poly == ["CHE"]


def test_harvest_skips_optic_abbr_collision() -> None:
    result = harvest_gap_pins(
        _champ_store(bbr_on_other=True),
        inventory_fn=list,
        fixtures_fn=_fixtures,
        px_events_fn=lambda _tid: [],
    )
    bbr = [
        a["alias_value"]
        for pin in result["pins"]
        for a in pin["aliases"]
        if a.get("alias_value") == "BBR"
    ]
    assert bbr == []
    assert any(row.get("reason") == "collision" for row in result["skipped"])
