"""Optic-id harvest merge and dry-run safety."""

from __future__ import annotations

from mappers.control_plane.batch_apply import dry_run_batch
from mappers.control_plane.gap_fix_optic_merge import merge_pins_by_optic_id, seed_optic_drafts
from mappers.control_plane.models import BatchChangesPayload
from mappers.control_plane.pin_flow import alias_from_pin
from mappers.control_plane.store import InMemoryStore

_OID = "190074FBA984264F"


def _stariy_pins() -> list[dict]:
    base = {
        "kind": "entity_alias",
        "league": "dota_2",
        "canonical_name": "Stariy Bog Club",
        "entity_type": "team",
        "reassign": False,
        "evidence_refs": ["optic:competitor:190074FBA984264F:Stariy Bog Club"],
    }
    return [
        {
            **base,
            "canonical_key": "SBC7",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _OID},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "SBC7"},
            ],
        },
        {
            **base,
            "canonical_key": "SBC8",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": _OID},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "SBC8"},
            ],
        },
    ]


def test_merge_pins_folds_book_codes_onto_one_canonical() -> None:
    merged = merge_pins_by_optic_id(_stariy_pins())
    assert len(merged) == 1
    pin = merged[0]
    assert pin["canonical_key"] == "SBC7"
    codes = {
        alias["alias_value"]
        for alias in pin["aliases"]
        if alias.get("sportsbook") == "polymarket_usa"
    }
    assert codes == {"SBC7", "SBC8"}


def test_merge_keeps_every_harvest_key() -> None:
    pins = _stariy_pins()
    pins[0]["harvest_book"] = "polymarket"
    pins[0]["harvest_key"] = "slug-a"
    pins[1]["harvest_book"] = "polymarket"
    pins[1]["harvest_key"] = "slug-b"
    merged = merge_pins_by_optic_id(pins)
    assert merged[0]["harvest_keys"] == ["slug-a", "slug-b"]


def test_seed_optic_drafts_keeps_first_canonical() -> None:
    drafted: dict[tuple[str, str], str] = {}
    seed_optic_drafts(drafted, _stariy_pins())
    assert drafted[("dota_2", _OID)] == "SBC7"


def test_merged_stariy_pins_pass_dry_run() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0", entities=[], leagues=[], activate=True)
    merged = merge_pins_by_optic_id(_stariy_pins())
    payload = BatchChangesPayload(
        entity_aliases=[alias_from_pin(pin) for pin in merged],
    )
    dry = dry_run_batch(store, "S0", payload)
    assert dry["ok"] is True
    assert not dry["blockers"]
