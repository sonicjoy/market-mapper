"""Chat Optic name bind — same names_fit unique-bind as gap-propose, no harvest."""

from __future__ import annotations

from pathlib import Path

from mappers.control_plane.chat_optic_name import (
    ALREADY,
    AMBIGUOUS,
    NO_LEAGUE,
    NONE,
    UNIQUE,
    bind_optic_name,
)
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore

_GAME = {
    "id": "fx-rune",
    "start_date": "2026-09-12T10:00:00Z",
    "league": {"id": "atp"},
    "home_competitors": [
        {"id": "oid-rune", "name": "Holger Rune", "abbreviation": "RUN"},
    ],
    "away_competitors": [
        {"id": "oid-alc", "name": "Carlos Alcaraz", "abbreviation": "ALC"},
    ],
}


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
        ],
        activate=True,
    )
    return store


def test_bind_requires_league() -> None:
    assert bind_optic_name(_store(), name="Holger Rune", league="").status == NO_LEAGUE


def test_bind_unique_optic_competitor() -> None:
    bind = bind_optic_name(
        _store(), name="Holger Rune", league="atp",
        fixtures_fn=lambda *_a, **_k: [_GAME],
    )
    assert bind.status == UNIQUE
    assert bind.pin is not None
    alias = bind.pin["aliases"][0]
    assert alias["sportsbook"] == "optic"
    assert alias["alias_value"] == "oid-rune"
    assert "optic:competitor:" in " ".join(bind.pin["evidence_refs"])


def test_bind_ambiguous_does_not_pin() -> None:
    twin = {
        **_GAME,
        "away_competitors": [
            {"id": "oid-rune-2", "name": "Holger Rune", "abbreviation": "HR2"},
        ],
    }
    bind = bind_optic_name(
        _store(), name="Holger Rune", league="atp",
        fixtures_fn=lambda *_a, **_k: [twin],
    )
    assert bind.status == AMBIGUOUS
    assert bind.pin is None


def test_bind_miss_and_already_on_tip() -> None:
    miss = bind_optic_name(
        _store(), name="Raphinha", league="atp",
        fixtures_fn=lambda *_a, **_k: [_GAME],
    )
    assert miss.status == NONE
    store = _store()
    store.seed_rule_set(
        rule_set_id="S1",
        entities=[
            EntityRow(
                league="atp",
                entity_type="team",
                canonical_key="RUNE",
                canonical_name="Holger Rune",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "oid-rune",
                    }
                ],
            )
        ],
        leagues=store.leagues_for("S0"),
        activate=True,
    )
    already = bind_optic_name(
        store, name="Holger Rune", league="atp",
        fixtures_fn=lambda *_a, **_k: [_GAME],
    )
    assert already.status == ALREADY
    assert already.canonical_key == "RUNE"


def test_bind_never_calls_harvest_gap_pins() -> None:
    src = Path("mappers/control_plane/chat_optic_name.py").read_text(encoding="utf-8")
    assert "harvest_gap_pins" not in src
