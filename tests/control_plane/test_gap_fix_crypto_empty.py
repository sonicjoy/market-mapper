"""Harvest crypto_id pins for close fixtures when RFQ inventory is empty."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_crypto_empty import harvest_missing_crypto_ids
from mappers.control_plane.gap_inventory import MAX_EVENTS
from mappers.control_plane.rows import EntityRow, LeagueRow
from tests.control_plane.gap_store_helpers import _store, _team

_CKI = "OIDCKI00000001"
_BRT = "OIDBRT00000002"


def _ufc_store(*, crypto_id: str | None = None) -> Any:
    aliases = [
        {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _CKI},
        {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "CKI"},
    ]
    if crypto_id:
        aliases.append(
            {
                "sportsbook": "crypto.com",
                "alias_kind": "external_id",
                "alias_value": crypto_id,
            }
        )
    return _store(
        [
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="CKI",
                canonical_name="Giga Chikadze",
                aliases=aliases,
            ),
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="BRT",
                canonical_name="Joanderson Brito",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": _BRT,
                    },
                    {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "BRT"},
                ],
            ),
        ],
        [
            LeagueRow(
                league="ufc",
                sport="mma",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "UFC",
                        "settings": {"league": "UFC", "sport_grouping": "MMA"},
                    }
                ],
            )
        ],
    )


def _fight(start: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "ufc-fx-1",
            "start_date": start,
            "league": {"id": "ufc"},
            "home_competitors": [
                {"id": _CKI, "name": "Giga Chikadze", "abbreviation": "CKI"},
            ],
            "away_competitors": [
                {"id": _BRT, "name": "Joanderson Brito", "abbreviation": "BRT"},
            ],
        }
    ]


def test_pin_slots_are_one_hundred() -> None:
    assert MAX_EVENTS == 100


def _close_start() -> str:
    """Kickoff still inside CLOSE_MAX_DAYS relative to harvest's UTC today."""
    day = datetime.now(tz=UTC).date() + timedelta(days=1)
    return f"{day.isoformat()}T00:00:00Z"


def test_close_ufc_pins_when_rfq_inventory_empty() -> None:
    """Close Optic UFC still drafts crypto_id when demanding RFQ inventory is 0."""
    result = harvest_gap_pins(
        _ufc_store(),
        inventory_fn=list,
        fixtures_fn=lambda *_a, **_k: _fight(_close_start()),
        crypto_harvest_fn=lambda _meta, _days: {
            "Giga Chikadze": "140000001",
            "Joanderson Brito": "140000002",
        },
    )
    by_key = {
        pin["canonical_key"]: pin
        for pin in result["pins"]
        if any(a.get("sportsbook") == "crypto.com" for a in pin["aliases"])
    }
    assert set(by_key) == {"CKI", "BRT"}
    assert by_key["CKI"]["aliases"][0]["alias_value"] == "140000001"
    assert any(ref.startswith("crypto_id:") for ref in by_key["CKI"]["evidence_refs"])


def test_far_fixture_is_not_close() -> None:
    pins: list[dict[str, Any]] = []
    harvest_missing_crypto_ids(
        _ufc_store(),
        pins,
        [],
        set(),
        fixtures_fn=lambda *_a, **_k: _fight("2026-09-25T00:00:00Z"),
        harvest_fn=lambda _meta, _days: {"Giga Chikadze": "140000001"},
        today=date(2026, 9, 19),
    )
    assert pins == []


def test_already_pinned_crypto_id_is_skipped() -> None:
    pins: list[dict[str, Any]] = []
    harvest_missing_crypto_ids(
        _ufc_store(crypto_id="140000001"),
        pins,
        [],
        set(),
        fixtures_fn=lambda *_a, **_k: _fight("2026-09-20T00:00:00Z"),
        harvest_fn=lambda _meta, _days: {
            "Giga Chikadze": "140000001",
            "Joanderson Brito": "140000002",
        },
        today=date(2026, 9, 19),
    )
    keys = {pin["canonical_key"] for pin in pins}
    assert keys == {"BRT"}


def _crypto_ex(meta: str) -> dict[str, Any]:
    return {
        "sportsbook": "crypto.com",
        "enabled": True,
        "parser_profile": "crypto_generic_v1",
        "source_league_id": meta,
        "settings": {"league": meta, "sport_grouping": meta},
    }


def test_combat_close_pins_before_tennis() -> None:
    """UFC close sides must draft even when ATP is also close and listed first."""
    store = _store(
        [
            _team("atp", "SIN", "Jannik Sinner"),
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="CKI",
                canonical_name="Giga Chikadze",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": _CKI,
                    },
                ],
            ),
        ],
        [
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[_crypto_ex("ATP")],
            ),
            LeagueRow(
                league="ufc",
                sport="mma",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[_crypto_ex("UFC")],
            ),
        ],
    )

    def games(optic_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_id == "ufc":
            return _fight("2026-09-20T02:00:00Z")
        return [
            {
                "id": "atp-fx-1",
                "start_date": "2026-09-19T12:00:00Z",
                "league": {"id": "atp"},
                "home_competitors": [
                    {"id": "OIDSIN", "name": "Jannik Sinner", "abbreviation": ""},
                ],
                "away_competitors": [
                    {"id": "OIDALC", "name": "Carlos Alcaraz", "abbreviation": ""},
                ],
            }
        ]

    pins: list[dict[str, Any]] = []
    harvest_missing_crypto_ids(
        store,
        pins,
        [],
        set(),
        fixtures_fn=games,
        harvest_fn=lambda meta, _days: (
            {"Giga Chikadze": "140000001"} if meta == "UFC"
            else {"Jannik Sinner": "90001"}
        ),
        today=date(2026, 9, 19),
    )
    leagues = [pin["league"] for pin in pins]
    assert "ufc" in leagues
    assert leagues[0] == "ufc"


def test_close_harvest_uses_unbounded_catalogue() -> None:
    """Stale publish_time must not hide close UFC ids already in the table."""
    seen: list[int] = []

    def harvest(_meta: str, days: int) -> dict[str, str]:
        seen.append(days)
        return {"Giga Chikadze": "140000001", "Joanderson Brito": "140000002"}

    pins: list[dict[str, Any]] = []
    harvest_missing_crypto_ids(
        _ufc_store(),
        pins,
        [],
        set(),
        fixtures_fn=lambda *_a, **_k: _fight("2026-09-20T00:00:00Z"),
        harvest_fn=harvest,
        today=date(2026, 9, 19),
    )
    assert seen and all(day == 0 for day in seen)
    assert {pin["canonical_key"] for pin in pins} == {"CKI", "BRT"}


def test_harvest_crypto_missing_coalesces_entities_once() -> None:
    """Empty-RFQ crypto harvest indexes the tip once, not per league sweep."""
    store = _ufc_store()
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_missing_crypto_ids(
        store, [], [], set(),
        fixtures_fn=lambda *_a, **_k: _fight("2026-09-20T00:00:00Z"),
        harvest_fn=lambda _meta, _days: {
            "Giga Chikadze": "140000001",
            "Joanderson Brito": "140000002",
        },
        today=date(2026, 9, 19),
    )
    assert calls["n"] == 1
