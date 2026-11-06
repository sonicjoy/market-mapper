"""DKEX empty-RFQ gap harvest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fetch.dkex import normalize
from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_dkex_harvest import harvest_dkex_catalog_gaps
from mappers.control_plane.rows import EntityRow, LeagueRow

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_markets_2026-09-28.json"


def _den_win_row() -> dict:
    """Real staging row: DEN Broncos moneyline, typed and normalized."""
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return normalize(
        next(r for r in raw if r["ticker"] == "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024"), "api",
    )


class _Store:
    current_rule_set_id = "S_test"

    def leagues_for(self, _rid: str) -> list[LeagueRow]:
        return [
            LeagueRow(
                league="nfl",
                sport="football",
                optic_league_id="nfl",
                extra_optic_league_ids=[],
                fixture_source="optic",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                settings={},
                exchanges=[{
                    "sportsbook": "optic",
                    "enabled": True,
                    "parser_profile": "optic_standard_v1",
                }],
            ),
        ]

    def market_rules_for(self, _rid: str) -> list:
        return []

    def entities_for(self, _rid: str) -> list:
        return []


def test_harvest_drafts_dkex_enable_with_empty_inventory() -> None:
    result = harvest_gap_pins(_Store(), inventory_fn=list)
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert any(
        ex.get("sportsbook") == "dkex" and ex.get("enabled")
        for pin in leagues
        for ex in pin.get("exchanges") or []
    )


def test_harvest_drafts_no_dkex_market_rules() -> None:
    """DKEX market types are code vocab; the harvest never pins tip rules."""
    pins: list = []
    harvest_dkex_catalog_gaps(_Store(), pins, [], set())
    assert pins
    assert not [p for p in pins if p.get("kind") == "mapping_market_rules"]


def test_harvest_re_enables_dkex_when_pin_disabled() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
            },
            {
                "sportsbook": "dkex",
                "enabled": False,
                "parser_profile": "dkex_generic_v1",
                "source_league_id": "NFL",
                "settings": {"league": "NFL"},
            },
        ],
    )

    class _DisabledStore:
        current_rule_set_id = "S_test"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return [row]

        def market_rules_for(self, _rid: str) -> list:
            return []

        def entities_for(self, _rid: str) -> list:
            return []

    pins: list = []
    seen: set = set()
    harvest_dkex_catalog_gaps(_DisabledStore(), pins, [], seen)
    leagues = [p for p in pins if p.get("kind") == "mapping_league"]
    assert leagues
    dkex = next(
        ex for pin in leagues for ex in pin.get("exchanges") or []
        if ex.get("sportsbook") == "dkex"
    )
    assert dkex.get("enabled") is True


def test_harvest_alias_unique_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    catalogue = tmp_path / "dkex_markets.jsonl"
    catalogue.write_text(
        json.dumps(_den_win_row()) + "\n",
        encoding="utf-8",
    )
    entities = [
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="KC",
            canonical_name="Kansas City Chiefs",
            aliases=[],
            enabled=True,
        ),
    ]

    class _AliasStore:
        current_rule_set_id = "S_test"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return _Store().leagues_for("S_test")

        def market_rules_for(self, _rid: str) -> list:
            return []

        def entities_for(self, _rid: str) -> list[EntityRow]:
            return entities

    pins: list = []
    seen: set = set()
    skipped: list = []
    harvest_dkex_catalog_gaps(_AliasStore(), pins, skipped, seen)
    aliases = [p for p in pins if p.get("kind") == "entity_alias"]
    assert len(aliases) == 1
    assert aliases[0]["canonical_key"] == "DEN"
    assert any(
        a.get("alias_kind") == "name" and a.get("alias_value") == "DEN Broncos"
        for a in aliases[0].get("aliases") or []
    )


def test_harvest_alias_ambiguous_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    catalogue = tmp_path / "dkex_markets.jsonl"
    catalogue.write_text(
        json.dumps(_den_win_row()) + "\n",
        encoding="utf-8",
    )
    entities = [
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN2",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
    ]

    class _AmbiguousStore:
        current_rule_set_id = "S_test"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return _Store().leagues_for("S_test")

        def market_rules_for(self, _rid: str) -> list:
            return []

        def entities_for(self, _rid: str) -> list[EntityRow]:
            return entities

    pins: list = []
    seen: set = set()
    skipped: list = []
    harvest_dkex_catalog_gaps(_AmbiguousStore(), pins, skipped, seen)
    assert not [p for p in pins if p.get("kind") == "entity_alias"]
    assert any(s.get("reason", "").startswith("ambiguous:") for s in skipped)


def test_harvest_ignores_untyped_report_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CSV report row has only the symbol; nothing is drafted from it."""
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    (tmp_path / "dkex_markets.jsonl").write_text(
        json.dumps(normalize(
            {"ticker": "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024", "status": "Open"},
            "reports",
        )) + "\n",
        encoding="utf-8",
    )
    entities = [
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
    ]

    class _AliasStore:
        current_rule_set_id = "S_test"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return _Store().leagues_for("S_test")

        def market_rules_for(self, _rid: str) -> list:
            return []

        def entities_for(self, _rid: str) -> list[EntityRow]:
            return entities

    pins: list = []
    harvest_dkex_catalog_gaps(_AliasStore(), pins, [], set())
    assert not [p for p in pins if p.get("kind") == "entity_alias"]


def test_existing_name_alias_is_not_redrafted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    (tmp_path / "dkex_markets.jsonl").write_text(
        json.dumps(_den_win_row()) + "\n", encoding="utf-8",
    )
    entities = [
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN",
            canonical_name="Denver Broncos",
            aliases=[{"sportsbook": "dkex", "alias_kind": "name", "alias_value": "DEN Broncos"}],
            enabled=True,
        ),
    ]

    class _AliasStore:
        current_rule_set_id = "S_test"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return _Store().leagues_for("S_test")

        def market_rules_for(self, _rid: str) -> list:
            return []

        def entities_for(self, _rid: str) -> list[EntityRow]:
            return entities

    pins: list = []
    harvest_dkex_catalog_gaps(_AliasStore(), pins, [], set())
    assert not [p for p in pins if p.get("kind") == "entity_alias"]
