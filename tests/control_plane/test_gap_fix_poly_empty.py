"""Harvest Poly US codes for close fixtures when RFQ inventory is empty."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_poly import harvest_poly_side
from mappers.control_plane.gap_fix_poly_empty import (
    CLOSE_HOURS,
    _event_is_close,
    _fixtures_by_inner,
    harvest_missing_poly_usa_codes,
)
from mappers.control_plane.gap_harvest_ttl import POLY_US_EVENTS, load_ttl
from mappers.control_plane.rows import EntityRow
from tests.control_plane.gap_store_helpers import _store
from tests.control_plane.test_gap_fix import _optic_row, _poly_us_league, _us_event

_GAN = "oid-gandra"
_DIA = "oid-diaz"
_SIN = "oid-sinner"
_ALC = "oid-alcaraz"
_NOW = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)
_CLOSE = "2026-09-19T23:00:00Z"
_CLOSE_DAY = "2026-09-19"
_FAR = "2026-09-25T00:00:00Z"
_FAR_DAY = "2026-09-25"


def _fighter(key: str, name: str, oid: str, *, usa: str | None = None) -> EntityRow:
    aliases = [{"sportsbook": "optic", "alias_kind": "external_id", "alias_value": oid}]
    if usa:
        aliases.append(
            {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": usa},
        )
    return EntityRow(
        league="ufc",
        entity_type="fighter",
        canonical_key=key,
        canonical_name=name,
        aliases=aliases,
    )


def _ufc_store(*, usa_gandra: str | None = None) -> Any:
    return _store(
        [
            _fighter("RGY9", "Ryan Gandra", _GAN, usa=usa_gandra),
            _fighter("ODZ", "Ozzy Diaz", _DIA),
        ],
        [_poly_us_league("ufc", "ufc", "ufc", sport="mma")],
    )


def _close_fx(
    optic_id: str,
    home_abbr: str,
    home_name: str,
    home_id: str,
    away_abbr: str,
    away_name: str,
    away_id: str,
    *,
    start: str = _CLOSE,
    day: str = _CLOSE_DAY,
    sport: str = "mma",
) -> dict[str, Any]:
    row = _optic_row(
        optic_id, home_abbr, home_name, home_id, away_abbr, away_name, away_id, day,
    )
    row["start_date"] = start
    row["sport"] = sport
    return row


def _gandra_event(*, day: str = _CLOSE_DAY) -> dict[str, Any]:
    return _us_event(
        "ufc", "ryagan", "ozzdia", day,
        title="Ryan Gandra vs. Ozzy Diaz",
        team_names={"ryagan": "Ryan Gandra", "ozzdia": "Ozzy Diaz"},
    )


def _gandra_fx(*, start: str = _CLOSE, day: str = _CLOSE_DAY) -> dict[str, Any]:
    return _close_fx(
        "ufc", "RGY9", "Ryan Gandra", _GAN, "ODZ", "Ozzy Diaz", _DIA,
        start=start, day=day,
    )


def _usa_values(pins: list[dict[str, Any]]) -> set[str]:
    return {
        str(alias["alias_value"])
        for pin in pins
        for alias in pin.get("aliases") or []
        if alias.get("sportsbook") == "polymarket_usa"
    }


def test_close_window_is_twenty_four_hours() -> None:
    assert CLOSE_HOURS == 24


def test_poly_usa_close_logs_start_loaded_done(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly_empty.cgroup_memory_ratio",
        lambda: 0.88,
    )
    with caplog.at_level(logging.INFO):
        harvest_missing_poly_usa_codes(
            _ufc_store(),
            [],
            [],
            set(),
            us_events_fn=lambda: [_gandra_event()],
            optic_rows_fn=lambda: [_gandra_fx()],
            now=_NOW,
        )
    text = caplog.text
    assert "phase=start" in text
    assert "phase=loaded" in text
    assert "phase=done" in text
    assert "mem_pct=88" in text
    assert "events=1" in text
    assert "close=1" in text


def test_close_ufc_pins_when_rfq_inventory_empty() -> None:
    """Horizon-blocked UFC still drafts Poly US codes when RFQ inventory is 0."""
    kick = datetime.now(tz=UTC) + timedelta(hours=8)
    day = kick.date().isoformat()
    start = kick.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = harvest_gap_pins(
        _ufc_store(),
        inventory_fn=list,
        fixtures_fn=lambda *_a, **_k: [],
        us_events_fn=lambda: [_gandra_event(day=day)],
        official_events_fn=list,
        optic_rows_fn=lambda: [_gandra_fx(start=start, day=day)],
    )
    assert _usa_values(result["pins"]) == {"ryagan", "ozzdia"}
    entities = [pin for pin in result["pins"] if pin.get("kind") == "entity_alias"]
    assert {pin["entity_type"] for pin in entities} == {"fighter"}
    ignores = [
        rule
        for pin in result["pins"]
        if pin.get("kind") == "mapping_market_rules"
        for rule in pin.get("rules") or []
        if rule.get("source_key") == "rof-before-r"
    ]
    assert len(ignores) == 1
    assert ignores[0]["action"] == "ignore"


def test_far_fixture_is_not_close() -> None:
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        us_events_fn=lambda: [_gandra_event(day=_FAR_DAY)],
        optic_rows_fn=lambda: [_gandra_fx(start=_FAR, day=_FAR_DAY)],
        now=_NOW,
    )
    assert pins == []


def test_already_pinned_usa_code_is_skipped() -> None:
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(usa_gandra="ryagan"),
        pins,
        [],
        set(),
        us_events_fn=lambda: [_gandra_event()],
        optic_rows_fn=lambda: [_gandra_fx()],
        now=_NOW,
    )
    assert _usa_values(pins) == {"ozzdia"}


def test_close_itf_pins_when_rfq_inventory_empty() -> None:
    store = _store(
        [
            EntityRow(
                league="itf_men",
                entity_type="team",
                canonical_key="SIN",
                canonical_name="Jannik Sinner",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": _SIN,
                    },
                ],
            ),
            EntityRow(
                league="itf_men",
                entity_type="team",
                canonical_key="ALC",
                canonical_name="Carlos Alcaraz",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": _ALC,
                    },
                ],
            ),
        ],
        [_poly_us_league("itf_men", "itf_men", "itfme", sport="tennis")],
    )
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        store,
        pins,
        [],
        set(),
        us_events_fn=lambda: [_us_event(
            "itfme", "jsinxx", "calcar", _CLOSE_DAY,
            title="Jannik Sinner vs. Carlos Alcaraz",
            team_names={"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
        )],
        optic_rows_fn=lambda: [_close_fx(
            "itf_men", "SIN", "Jannik Sinner", _SIN,
            "ALC", "Carlos Alcaraz", _ALC, sport="tennis",
        )],
        now=_NOW,
    )
    assert _usa_values(pins) == {"jsinxx", "calcar"}


def test_combat_close_pins_before_tennis() -> None:
    """UFC close sides must draft even when ITF is also close and listed first."""
    store = _store(
        [
            _fighter("RGY9", "Ryan Gandra", _GAN),
            _fighter("ODZ", "Ozzy Diaz", _DIA),
            EntityRow(
                league="itf_men",
                entity_type="team",
                canonical_key="SIN",
                canonical_name="Jannik Sinner",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": _SIN,
                    },
                ],
            ),
        ],
        [
            _poly_us_league("itf_men", "itf_men", "itfme", sport="tennis"),
            _poly_us_league("ufc", "ufc", "ufc", sport="mma"),
        ],
    )
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        store,
        pins,
        [],
        set(),
        us_events_fn=lambda: [
            _us_event(
                "itfme", "jsinxx", "calcar", _CLOSE_DAY,
                title="Jannik Sinner vs. Carlos Alcaraz",
                team_names={"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
            ),
            _gandra_event(),
        ],
        optic_rows_fn=lambda: [
            _close_fx(
                "itf_men", "SIN", "Jannik Sinner", _SIN,
                "ALC", "Carlos Alcaraz", _ALC, sport="tennis",
            ),
            _gandra_fx(),
        ],
        now=_NOW,
    )
    leagues = [pin["league"] for pin in pins]
    assert "ufc" in leagues
    assert leagues[0] == "ufc"


def test_close_harvest_does_not_persist_us_events_ttl() -> None:
    """Close sweep must not poison the RFQ walk's poly_us_events TTL cache."""
    store = _ufc_store()
    events = [_gandra_event()]
    rows = [_gandra_fx()]
    harvest_poly_side(
        store, ["ufc"], events, rows, official_events=[], persist_ttl=False,
    )
    assert load_ttl(POLY_US_EVENTS) is None
    harvest_poly_side(store, ["ufc"], events, rows, official_events=[], persist_ttl=True)
    blob = load_ttl(POLY_US_EVENTS)
    assert isinstance(blob, dict)
    assert blob.get("events")


def test_optic_kickoff_outside_close_window_is_skipped() -> None:
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        us_events_fn=lambda: [_gandra_event(day=_FAR_DAY)],
        optic_rows_fn=lambda: [_gandra_fx(start=_FAR, day=_FAR_DAY)],
        now=_NOW,
    )
    assert pins == []


def test_fixtures_by_inner_separates_leagues() -> None:
    store = _store(
        [],
        [
            _poly_us_league("ufc", "ufc", "ufc", sport="mma"),
            _poly_us_league("nfl", "nfl", "nfl", sport="football"),
        ],
    )
    nfl_fx = _close_fx(
        "nfl", "SEA", "Seattle", "oid-sea", "KC", "Kansas City", "oid-kc",
        sport="football",
    )
    by = _fixtures_by_inner(store, ["ufc", "nfl"], [_gandra_fx(), nfl_fx])
    assert [row["home_abbr"] for row in by["ufc"]] == ["RGY9"]
    assert [row["home_abbr"] for row in by["nfl"]] == ["SEA"]


def test_fixtures_by_inner_reads_nested_league_id() -> None:
    fx = _gandra_fx()
    nested = {key: value for key, value in fx.items() if key != "optic_league_id"}
    nested["league"] = {"id": "ufc"}
    by = _fixtures_by_inner(_ufc_store(), ["ufc"], [nested])
    assert len(by["ufc"]) == 1
    assert by["ufc"][0]["optic_league_id"] == "ufc"


def test_close_match_scoped_to_event_inner() -> None:
    """NFL kickoff must not close a far UFC ticker when the UFC inner bucket is empty."""
    nfl_only = _close_fx(
        "nfl", "SEA", "Seattle", "oid-sea", "KC", "Kansas City", "oid-kc",
        sport="football",
    )
    assert not _event_is_close(_gandra_event(day=_FAR_DAY), [nfl_only], _NOW)


def test_close_harvest_pins_with_nested_league_id_fixture() -> None:
    fx = _gandra_fx()
    nested = {key: value for key, value in fx.items() if key != "optic_league_id"}
    nested["league"] = {"id": "ufc"}
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        us_events_fn=lambda: [_gandra_event()],
        optic_rows_fn=lambda: [nested],
        now=_NOW,
    )
    assert _usa_values(pins) == {"ryagan", "ozzdia"}


def test_close_harvest_uses_fixtures_fn_for_optic_rows() -> None:
    """Injected fixtures_fn supplies Optic rows when optic_rows_fn is omitted."""
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        us_events_fn=lambda: [_gandra_event()],
        fixtures_fn=lambda *_a, **_k: [_gandra_fx()],
        now=_NOW,
    )
    assert _usa_values(pins) == {"ryagan", "ozzdia"}


def test_close_ufc_pins_from_bq_close_events(
    monkeypatch: Any, us_league_events: dict[str, list[dict[str, Any]]],
) -> None:
    """Close harvest: RFQ symbols → typed gateway event → drafts via Optic names."""
    from mappers.control_plane.gap_fix_poly_bq import fetch_close_us_events

    sym = "aec-ufc-ryagan-ozzdia-2026-09-19"
    us_league_events["ufc"] = [{
        "id": "e1", "startTime": "2026-09-19T23:00:00Z",
        "teams": [
            {"id": "1", "abbreviation": "ryagan", "name": "Ryan Gandra"},
            {"id": "2", "abbreviation": "ozzdia", "name": "Ozzy Diaz"},
        ],
        "markets": [{"id": "m1", "slug": sym}],
    }]

    def close_events(_prefixes: list[str]) -> list[dict[str, Any]]:
        return fetch_close_us_events(["ufc"], query_fn=lambda _sql: [{"symbol": sym}])

    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly_empty.fetch_close_us_events",
        close_events,
    )
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        optic_rows_fn=lambda: [_gandra_fx()],
        now=_NOW,
    )
    assert _usa_values(pins) == {"ryagan", "ozzdia"}


def test_far_event_date_dropped_close_ufc_still_pins() -> None:
    """A far NFL event drops before the Optic join; close UFC still drafts."""
    store = _store(
        [
            _fighter("RGY9", "Ryan Gandra", _GAN),
            _fighter("ODZ", "Ozzy Diaz", _DIA),
        ],
        [
            _poly_us_league("ufc", "ufc", "ufc", sport="mma"),
            _poly_us_league("nfl", "nfl", "nfl", sport="football"),
        ],
    )
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        store,
        pins,
        [],
        set(),
        us_events_fn=lambda: [
            _us_event("nfl", "sea", "kc", _FAR_DAY),
            _us_event("ufc", "ryagan", "ozzdia", _CLOSE_DAY),
        ],
        optic_rows_fn=lambda: [_gandra_fx()],
        now=_NOW,
    )
    assert _usa_values(pins) == {"ryagan", "ozzdia"}


def test_skips_live_bq_when_only_fixtures_fn(monkeypatch: Any) -> None:
    def boom(*_a: object, **_k: object) -> list[object]:
        raise RuntimeError("bq should not run")

    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly_empty.fetch_close_us_events", boom,
    )
    pins: list[dict[str, Any]] = []
    harvest_missing_poly_usa_codes(
        _ufc_store(),
        pins,
        [],
        set(),
        fixtures_fn=lambda *_a, **_k: [],
        now=_NOW,
    )
    assert pins == []
