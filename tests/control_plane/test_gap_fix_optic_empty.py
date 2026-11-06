"""Harvest Optic fixture sides missing from the tip (empty RFQ inventory)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_optic_empty import (
    MAX_PER_LEAGUE,
    harvest_missing_optic_competitors,
    remember_verify_optic_misses,
)
from mappers.control_plane.gap_harvest_ttl import remember_optic_skips
from mappers.control_plane.rows import EntityRow, LeagueRow
from tests.control_plane.gap_harvest_clock import freeze_gap_harvest_clock
from tests.control_plane.gap_store_helpers import _league, _store, _team

@pytest.fixture(autouse=True)
def _gap_harvest_close_day(monkeypatch: Any) -> None:
    freeze_gap_harvest_clock(monkeypatch)


_GARIN_DAVIS = "D0CCA7763E015726"
_JODAR_DAVIS = "74F8F924E9DC9F69"
_JODAR_TOUR = "58448A315FCFEEFF"


def _atp_crypto_ex() -> dict[str, Any]:
    return {
        "sportsbook": "crypto.com",
        "enabled": True,
        "parser_profile": "crypto_generic_v1",
        "source_league_id": "ATP",
        "settings": {"league": "ATP", "sport_grouping": "TENNIS"},
    }


def _atp_davis_store() -> Any:
    jodar = EntityRow(
        league="atp",
        entity_type="player",
        canonical_key="JOD",
        canonical_name="Rafael Jodar",
        aliases=[
            {
                "sportsbook": "optic",
                "alias_kind": "external_id",
                "alias_value": _JODAR_TOUR,
            },
            {
                "sportsbook": "crypto.com",
                "alias_kind": "external_id",
                "alias_value": "1460336",
            },
        ],
    )
    return _store(
        [jodar],
        [
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=["davis_cup"],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[_atp_crypto_ex()],
            ),
        ],
    )


def _davis_cup_games(optic_id: str, **_k: Any) -> list[dict[str, Any]]:
    if optic_id != "davis_cup":
        return []
    return [
        {
            "id": "dc-fx-1",
            "start_date": "2026-09-19T17:30:00Z",
            "league": {"id": "davis_cup"},
            "home_competitors": [
                {"id": _GARIN_DAVIS, "name": "Cristian Garin", "abbreviation": ""},
            ],
            "away_competitors": [
                {"id": _JODAR_DAVIS, "name": "Rafael Jodar", "abbreviation": ""},
            ],
        },
    ]


def test_davis_cup_harvests_garin_optic_and_crypto() -> None:
    """Davis Cup extras draft Garin optic+crypto; Jodar gets a second Optic id."""
    result = harvest_gap_pins(
        _atp_davis_store(),
        inventory_fn=list,
        fixtures_fn=_davis_cup_games,
        crypto_harvest_fn=lambda _meta, _days: {
            "Cristian Garin": "308357",
            "Rafael Jodar": "1460336",
        },
    )
    garin = next(
        pin for pin in result["pins"]
        if pin["canonical_name"] == "Cristian Garin"
    )
    garin_aliases = {
        (a["sportsbook"], a["alias_value"]) for a in garin["aliases"]
    }
    assert ("optic", _GARIN_DAVIS) in garin_aliases
    assert ("crypto.com", "308357") in garin_aliases
    assert any(ref.startswith("crypto_id:") for ref in garin["evidence_refs"])

    jodar = next(
        pin for pin in result["pins"]
        if any(a.get("alias_value") == _JODAR_DAVIS for a in pin["aliases"])
    )
    assert jodar["canonical_key"] == "JOD"
    assert len(jodar["aliases"]) == 1
    assert jodar["aliases"][0]["sportsbook"] == "optic"


def test_davis_cup_harvests_garin_with_catalogue_legal_name() -> None:
    """FIX legal name may extend the Optic display name."""
    result = harvest_gap_pins(
        _atp_davis_store(),
        inventory_fn=list,
        fixtures_fn=_davis_cup_games,
        crypto_harvest_fn=lambda _meta, _days: {
            "Cristian Ignacio Garin": "308357",
        },
    )
    garin = next(
        pin for pin in result["pins"]
        if any(a.get("alias_value") == _GARIN_DAVIS for a in pin["aliases"])
    )
    assert any(
        a.get("sportsbook") == "crypto.com" and a.get("alias_value") == "308357"
        for a in garin["aliases"]
    )


def test_extra_league_side_not_crowded_by_primary_backlog() -> None:
    """Close Davis Cup sides keep their own budget when primary ATP is full."""
    store = _store(
        [],
        [
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=["davis_cup"],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[_atp_crypto_ex()],
            ),
        ],
    )

    def games(optic_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_id == "davis_cup":
            return [
                {
                    "id": "dc-fx-1",
                    "start_date": "2026-09-19T17:30:00Z",
                    "league": {"id": "davis_cup"},
                    "home_competitors": [
                        {
                            "id": _GARIN_DAVIS,
                            "name": "Cristian Garin",
                            "abbreviation": "",
                        },
                    ],
                    "away_competitors": [
                        {"id": "AWAY01", "name": "Away One", "abbreviation": ""},
                    ],
                },
            ]
        rows = []
        for i in range(MAX_PER_LEAGUE + 2):
            rows.append(
                {
                    "id": f"atp-fx-{i}",
                    "start_date": f"2026-10-{10 + i:02d}T12:00:00Z",
                    "league": {"id": "atp"},
                    "home_competitors": [
                        {
                            "id": f"H{i:04d}{'X' * 12}",
                            "name": f"Primary Home {i}",
                            "abbreviation": "",
                        },
                    ],
                    "away_competitors": [
                        {
                            "id": f"A{i:04d}{'Y' * 12}",
                            "name": f"Primary Away {i}",
                            "abbreviation": "",
                        },
                    ],
                },
            )
        return rows

    result = harvest_gap_pins(
        store,
        inventory_fn=list,
        fixtures_fn=games,
        crypto_harvest_fn=lambda _meta, _days: {"Cristian Garin": "308357"},
    )
    garin = [
        pin for pin in result["pins"]
        if any(a.get("alias_value") == _GARIN_DAVIS for a in pin["aliases"])
    ]
    assert len(garin) == 1


_VLAJIC = "AAAA1111BBBB2222"
_BARTONE = "CCCC3333DDDD4444"
_STARIY_BOG = "190074FBA984264F"


def _itf_store() -> Any:
    return _store(
        [_team("itf_women", "GAU", "Coco Gauff")],
        [_league("itf_women", "itf_women", sport="tennis")],
    )


def _vlajic_bartone(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "itf-fx-1",
            "start_date": "2026-09-19T14:00:00Z",
            "league": {"id": "itf_women"},
            "home_competitors": [
                {"id": _VLAJIC, "name": "Teodora Vlajic", "abbreviation": ""},
            ],
            "away_competitors": [
                {"id": _BARTONE, "name": "Kamilla Bartone", "abbreviation": ""},
            ],
        },
    ]


def test_harvest_dedupes_same_optic_competitor_across_fixtures() -> None:
    """Stariy Bog on three fixtures must not mint SBC7/SBC8/SBC9 in one pass."""
    store = _store(
        [],
        [_league("dota_2", "dota_2", sport="esports")],
    )

    def games(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        rows = []
        for day in (19, 20, 21):
            rows.append(
                {
                    "id": f"dota-fx-{day}",
                    "start_date": f"2026-09-{day}T12:00:00Z",
                    "league": {"id": "dota_2"},
                    "home_competitors": [
                        {
                            "id": _STARIY_BOG,
                            "name": "Stariy Bog Club",
                            "abbreviation": "",
                        },
                    ],
                    "away_competitors": [
                        {"id": f"A{day:04d}{'Y' * 12}", "name": f"Away {day}", "abbreviation": ""},
                    ],
                },
            )
        return rows

    result = harvest_gap_pins(store, inventory_fn=list, fixtures_fn=games)
    stariy = [
        pin for pin in result["pins"]
        if any(a.get("alias_value") == _STARIY_BOG for a in pin["aliases"])
    ]
    assert len(stariy) == 1
    assert stariy[0]["canonical_key"] == "SBC7"


def test_harvest_missing_dedupes_without_shared_map() -> None:
    """Direct sweeper call still collapses one Optic id to one canonical."""
    store = _store(
        [],
        [_league("dota_2", "dota_2", sport="esports")],
    )

    def games(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": f"dota-fx-{day}",
                "start_date": f"2026-09-{day}T12:00:00Z",
                "league": {"id": "dota_2"},
                "home_competitors": [
                    {"id": _STARIY_BOG, "name": "Stariy Bog Club", "abbreviation": ""},
                ],
                "away_competitors": [
                    {"id": f"A{day:04d}{'Y' * 12}", "name": f"Away {day}", "abbreviation": ""},
                ],
            }
            for day in (19, 20)
        ]

    pins: list[dict[str, Any]] = []
    harvest_missing_optic_competitors(store, pins, [], set(), fixtures_fn=games)
    stariy = [
        pin for pin in pins
        if any(a.get("alias_value") == _STARIY_BOG for a in pin["aliases"])
    ]
    assert len(stariy) == 1
    assert stariy[0]["canonical_key"] == "SBC7"


def test_harvest_missing_tennis_with_empty_inventory() -> None:
    """Sweeper must draft Coverage No-tip-alias sides when RFQ is empty."""
    result = harvest_gap_pins(
        _itf_store(),
        inventory_fn=list,
        fixtures_fn=_vlajic_bartone,
    )
    by_oid = {
        alias["alias_value"]: pin
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert by_oid[_VLAJIC]["canonical_name"] == "Teodora Vlajic"
    assert by_oid[_VLAJIC]["entity_type"] == "team"
    assert by_oid[_VLAJIC]["aliases"][0]["alias_kind"] == "external_id"
    assert by_oid[_VLAJIC]["start"] == "2026-09-19T14:00:00Z"
    assert by_oid[_BARTONE]["canonical_name"] == "Kamilla Bartone"
    assert by_oid[_BARTONE]["entity_type"] == "team"
    assert "optic:name:Teodora Vlajic" in by_oid[_VLAJIC]["evidence_refs"]
    assert "optic:competitor:AAAA1111BBBB2222:Teodora Vlajic" in by_oid[_VLAJIC]["evidence_refs"]
    assert all(not ref.startswith("polymarket:") for ref in by_oid[_VLAJIC]["evidence_refs"])


def test_harvest_skips_unstamped_fixtures() -> None:
    """Injected soccer stubs omit league.id; do not pin them onto tennis."""
    def unstamped(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "fx",
                "home_competitors": [
                    {"id": _VLAJIC, "name": "Teodora Vlajic", "abbreviation": ""},
                ],
                "away_competitors": [
                    {"id": _BARTONE, "name": "Kamilla Bartone", "abbreviation": ""},
                ],
            },
        ]

    result = harvest_gap_pins(
        _itf_store(), inventory_fn=list, fixtures_fn=unstamped,
    )
    assert result["pins"] == []


def test_harvest_skips_optic_id_already_on_tip() -> None:
    pinned = _team("itf_women", "VLA", "Teodora Vlajic")
    pinned.aliases.append(
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _VLAJIC},
    )
    store = _store(
        [pinned],
        [_league("itf_women", "itf_women", sport="tennis")],
    )
    result = harvest_gap_pins(
        store, inventory_fn=list, fixtures_fn=_vlajic_bartone,
    )
    oids = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert _VLAJIC not in oids
    assert _BARTONE in oids


def test_harvest_skips_doubles() -> None:
    def doubles(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "d1",
                "start_date": "2026-09-19T14:00:00Z",
                "league": {"id": "itf_women"},
                "home_competitors": [
                    {"id": "H1", "name": "A", "abbreviation": ""},
                    {"id": "H2", "name": "B", "abbreviation": ""},
                ],
                "away_competitors": [
                    {"id": "A1", "name": "C", "abbreviation": ""},
                    {"id": "A2", "name": "D", "abbreviation": ""},
                ],
            },
        ]

    result = harvest_gap_pins(
        _itf_store(), inventory_fn=list, fixtures_fn=doubles,
    )
    assert result["pins"] == []


def test_harvest_caps_per_league() -> None:
    def many(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        games = []
        for i in range(MAX_PER_LEAGUE + 3):
            games.append(
                {
                    "id": f"fx{i}",
                    "start_date": f"2026-09-19T{10 + i:02d}:00:00Z",
                    "league": {"id": "itf_women"},
                    "home_competitors": [
                        {"id": f"H{i:04d}{'X' * 12}", "name": f"Home {i}", "abbreviation": ""},
                    ],
                    "away_competitors": [
                        {"id": f"A{i:04d}{'Y' * 12}", "name": f"Away {i}", "abbreviation": ""},
                    ],
                },
            )
        return games

    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    harvest_missing_optic_competitors(
        _itf_store(), pins, skipped, set(), fixtures_fn=many,
    )
    assert len(pins) == MAX_PER_LEAGUE
    assert any(row.get("reason") == "league_cap" for row in skipped)


def test_ufc_missing_sides_are_fighter() -> None:
    store = _store(
        [],
        [_league("ufc", "ufc", sport="mma")],
    )

    def fight(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "ufc-1",
                "start_date": "2026-09-19T00:00:00Z",
                "league": {"id": "ufc"},
                "home_competitors": [
                    {"id": "F1F1F1F1F1F1F1F1", "name": "Jane Fighter", "abbreviation": ""},
                ],
                "away_competitors": [
                    {"id": "F2F2F2F2F2F2F2F2", "name": "Alex Boxer", "abbreviation": ""},
                ],
            },
        ]

    result = harvest_gap_pins(store, inventory_fn=list, fixtures_fn=fight)
    assert result["pins"]
    assert all(pin["entity_type"] == "fighter" for pin in result["pins"])


def test_harvest_keeps_optic_abbr_on_tennis() -> None:
    def fx(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "itf-fx-1",
                "start_date": "2026-09-19T14:00:00Z",
                "league": {"id": "itf_women"},
                "home_competitors": [
                    {"id": _VLAJIC, "name": "Teodora Vlajic", "abbreviation": "VLA"},
                ],
                "away_competitors": [
                    {"id": _BARTONE, "name": "Kamilla Bartone", "abbreviation": "BAR"},
                ],
            },
        ]

    result = harvest_gap_pins(_itf_store(), inventory_fn=list, fixtures_fn=fx)
    pin = next(
        p for p in result["pins"]
        if any(a["alias_value"] == _VLAJIC for a in p["aliases"])
    )
    assert "optic:abbr:VLA" in pin["evidence_refs"]
    assert "optic:name:Teodora Vlajic" in pin["evidence_refs"]


def _freeze_now(monkeypatch: Any, now: datetime) -> None:
    freeze_gap_harvest_clock(monkeypatch, now=now)


def _fx_at(start: str) -> Any:
    def fx(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        games = _vlajic_bartone()
        games[0]["start_date"] = start
        return games
    return fx


def test_harvest_skips_cached_optic_ids(monkeypatch: Any) -> None:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    start = "2026-09-20T14:00:00Z"
    _freeze_now(monkeypatch, now)
    remember_optic_skips({_VLAJIC: start}, now)
    result = harvest_gap_pins(
        _itf_store(), inventory_fn=list, fixtures_fn=_fx_at(start),
    )
    oids = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert _VLAJIC not in oids
    assert _BARTONE in oids


def test_harvest_rechecks_optic_ids_six_hours_before_start(monkeypatch: Any) -> None:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    start = (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _freeze_now(monkeypatch, now)
    remember_optic_skips({_VLAJIC: "2026-12-01T14:00:00Z"}, now)
    result = harvest_gap_pins(
        _itf_store(), inventory_fn=list, fixtures_fn=_fx_at(start),
    )
    oids = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert _VLAJIC in oids
    assert _BARTONE in oids


def test_remember_verify_optic_misses_skips_next_harvest(monkeypatch: Any) -> None:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    start = "2026-09-20T14:00:00Z"
    _freeze_now(monkeypatch, now)
    pin = {
        "aliases": [{"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _VLAJIC}],
        "start": start,
    }
    remember_verify_optic_misses(
        [pin],
        [f"Optic competitor {_VLAJIC} not in active itf_women fixtures."],
        now=now,
    )
    result = harvest_gap_pins(
        _itf_store(), inventory_fn=list, fixtures_fn=_fx_at(start),
    )
    oids = {
        alias["alias_value"]
        for pin in result["pins"]
        for alias in pin["aliases"]
    }
    assert _VLAJIC not in oids
    assert _BARTONE in oids


def test_harvest_skips_far_optic_fixtures() -> None:
    """Full-horizon missing sides must not fill Review; close window only."""
    def far(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        games = _vlajic_bartone()
        games[0]["start_date"] = "2026-10-30T14:00:00Z"
        return games

    result = harvest_gap_pins(_itf_store(), inventory_fn=list, fixtures_fn=far)
    assert result["pins"] == []


def test_harvest_missing_coalesces_entities_once() -> None:
    """One entities_for pass — not a coalesce per league or competitor."""
    store = _itf_store()
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_missing_optic_competitors(
        store, [], [], set(), fixtures_fn=_vlajic_bartone,
    )
    assert calls["n"] == 1


def test_tennis_fix_catalogue_uses_close_days() -> None:
    """ATP FIX harvest is the close window, not the full historical catalogue."""
    seen: list[int] = []

    def harvest(_meta: str, days: int) -> dict[str, str]:
        seen.append(days)
        return {"Cristian Garin": "308357", "Rafael Jodar": "1460336"}

    harvest_gap_pins(
        _atp_davis_store(),
        inventory_fn=list,
        fixtures_fn=_davis_cup_games,
        crypto_harvest_fn=harvest,
    )
    assert seen
    assert all(day == 3 for day in seen)
