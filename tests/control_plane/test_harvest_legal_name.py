"""Harvest drafts club legal-name suffixes for human Review."""

from __future__ import annotations

from typing import Any

from mappers.canonical_codes import fallback_code
from mappers.control_plane.gap_fix_draft import collect_crypto_probe_pins
from mappers.control_plane.gap_fix_keys import used_keys
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore


def _optic(oid: str) -> dict[str, str]:
    return {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": oid}


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="france_ligue_1",
                entity_type="team",
                canonical_key="NIC",
                canonical_name="OGC Nice Côte d'Azur",
                aliases=[_optic("oid-nic")],
            ),
            EntityRow(
                league="france_ligue_1",
                entity_type="team",
                canonical_key="REN",
                canonical_name="Stade Rennais FC",
                aliases=[_optic("oid-ren")],
            ),
        ],
        leagues=[
            LeagueRow(
                league="france_ligue_1",
                sport="soccer",
                optic_league_id="france_-_ligue_1",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    return store


def _row(cid: str, label: str, optic_name: str, oid: str) -> dict[str, Any]:
    return {
        "symbol": "NX.F.OPT.FRL1-1",
        "kind": "unknown_alias",
        "league": "france_ligue_1",
        "crypto_ids": [cid],
        "home_name": label,
        "away_name": "",
        "optic": {
            "home": optic_name,
            "home_id": oid,
            "away": "Le Mans",
            "away_id": "oid-lem",
        },
        "tip": [],
        "evidence_refs": ["gap:NX.F.OPT.FRL1-1"],
    }


def test_harvest_drafts_nice_and_rennes_legal_suffixes() -> None:
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    store = _store()
    collect_crypto_probe_pins(
        store,
        _row("90000901", "OGC Nice", "OGC Nice Côte d'Azur", "oid-nic"),
        pins, skipped, seen,
    )
    collect_crypto_probe_pins(
        store,
        _row("90000905", "Stade Rennais FC 1901", "Stade Rennais FC", "oid-ren"),
        pins, skipped, seen,
    )
    by_cid = {
        a["alias_value"]: p["canonical_key"]
        for p in pins
        for a in p["aliases"]
        if a.get("sportsbook") == "crypto.com"
    }
    assert by_cid["90000901"] == "NIC"
    assert by_cid["90000905"] == "REN"
    assert skipped == []
    for pin in pins:
        books = [a.get("sportsbook") for a in pin["aliases"]]
        assert books == ["crypto.com"]


def test_crypto_harvest_pins_optic_id_on_new_canonical() -> None:
    """Empty-abbr Optic sides must ship optic_id with crypto_id (DSA9 class)."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="wta",
                entity_type="team",
                canonical_key="POT",
                canonical_name="Anastasia Potapova",
                aliases=[
                    _optic("75A742ED02F4"),
                    {
                        "sportsbook": "crypto.com",
                        "alias_kind": "external_id",
                        "alias_value": "751197",
                    },
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="wta",
                sport="tennis",
                optic_league_id="wta",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    collect_crypto_probe_pins(
        store,
        {
            "symbol": "NX.F.OPT.TENNIS-0041",
            "kind": "unknown_alias",
            "league": "wta",
            "crypto_ids": ["751197", "1057110"],
            "home_name": "Anastasia Potapova",
            "away_name": "Darja Semenistaja",
            "optic": {
                "home": "Anastasia Potapova",
                "home_id": "75A742ED02F4",
                "away": "Darja Semenistaja",
                "away_id": "F96F1B154D3D",
            },
            "tip": [
                {"crypto_id": "751197", "owners": ["POT"]},
                {"crypto_id": "1057110", "owners": []},
            ],
            "evidence_refs": ["gap:NX.F.OPT.TENNIS-0041"],
        },
        pins,
        skipped,
        seen,
    )
    assert skipped == []
    assert len(pins) == 1
    pin = pins[0]
    aliases = {
        (a.get("sportsbook"), a.get("alias_kind"), a.get("alias_value"))
        for a in pin["aliases"]
    }
    assert ("optic", "external_id", "F96F1B154D3D") in aliases
    assert ("crypto.com", "external_id", "1057110") in aliases
    assert pin["canonical_key"] == fallback_code(
        "Darja Semenistaja", used_keys(store, "wta"), "F96F1B154D3D",
    )
    assert pin["canonical_name"] == "Darja Semenistaja"
