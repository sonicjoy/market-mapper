"""Combat match-side entity_type retag (team -> fighter)."""

from __future__ import annotations

from typing import cast

from mappers.control_plane.artifact_apply import build_candidate_slices
from mappers.control_plane.change_view import snapshot_change_groups
from mappers.control_plane.combat_entity_retag import (
    apply_combat_entity_retag,
    dry_run_combat_retag,
)
from mappers.control_plane.cow_diff import diff_entities
from mappers.control_plane.dry_run_league import apply_league_payload
from mappers.control_plane.entity_types import match_entity_type_for_pin, match_entity_type_for_row
from mappers.control_plane.gap_fix_keys import entity_type_for
from mappers.control_plane.models import (
    CombatEntityRetagPayload,
    ExchangePin,
    MappingLeaguePayload,
    ProposalRecord,
    ValidationFailedError,
)
from mappers.control_plane.review_cards import build_review_view
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import ProposalStore
from mappers.seed.sot import SotSnapshot, poly_team_name_aliases, tip_entity_type


def _ent(
    league: str,
    key: str,
    *,
    entity_type: str = "team",
    aliases: list | None = None,
    enabled: bool = True,
) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type=entity_type,
        canonical_key=key,
        canonical_name=key,
        aliases=list(aliases or []),
        enabled=enabled,
    )


def _optic(entity_type: str = "") -> list[dict]:
    settings = {"entity_type": entity_type} if entity_type else {}
    return [{
        "sportsbook": "optic",
        "enabled": True,
        "parser_profile": "optic_standard_v1",
        "settings": settings,
    }]


def _league(
    slug: str,
    *,
    entity_type: str = "team",
    optic: bool = True,
) -> LeagueRow:
    settings = {"entity_type": entity_type} if entity_type else {}
    return LeagueRow(
        league=slug,
        sport="mma" if slug == "ufc" else "boxing",
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=_optic(entity_type) if optic else [],
        settings=settings,
    )


class _Store:
    current_rule_set_id = "S0"

    def __init__(self, entities: list[EntityRow], leagues: list[LeagueRow]) -> None:
        self._entities = entities
        self._leagues = leagues

    def entities_for(self, _rid: str) -> list[EntityRow]:
        return self._entities

    def leagues_for(self, _rid: str) -> list[LeagueRow]:
        return self._leagues


def test_retag_merges_team_and_fighter_shell() -> None:
    parent = [
        _ent(
            "ufc",
            "DCO8",
            entity_type="team",
            aliases=[{"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "DCO8"}],
        ),
        _ent("ufc", "DCO8", entity_type="fighter"),
    ]
    child, child_lg = apply_combat_entity_retag(parent, [_league("ufc")])
    by_type = {e.entity_type for e in child if e.league == "ufc" and e.canonical_key == "DCO8"}
    assert by_type == {"fighter"}
    merged = next(e for e in child if e.canonical_key == "DCO8")
    assert merged.aliases[0]["alias_value"] == "DCO8"
    assert child_lg[0].settings["entity_type"] == "fighter"


def test_retag_keeps_disabled_alias_disabled() -> None:
    parent = [
        _ent(
            "ufc",
            "GAR",
            aliases=[{
                "sportsbook": "kalshi", "alias_kind": "code",
                "alias_value": "GAR", "enabled": False,
            }],
        ),
        _ent(
            "ufc",
            "GAR",
            entity_type="fighter",
            aliases=[{
                "sportsbook": "kalshi", "alias_kind": "code", "alias_value": "GAR",
            }],
        ),
    ]
    child, _ = apply_combat_entity_retag(parent, [_league("ufc")])
    merged = next(e for e in child if e.canonical_key == "GAR")
    assert merged.aliases[0]["enabled"] is False


def test_retag_disabled_team_stays_disabled() -> None:
    parent = [_ent("ufc", "X", enabled=False)]
    child, _ = apply_combat_entity_retag(parent, [_league("ufc")])
    assert next(e for e in child if e.canonical_key == "X").enabled is False


def test_retag_merges_boxing_kalshi_team_with_fighter_optic() -> None:
    parent = [
        _ent(
            "boxing_matches",
            "SAVAGE",
            aliases=[{
                "sportsbook": "kalshi", "alias_kind": "code", "alias_value": "SAVAGE",
            }],
        ),
        _ent(
            "boxing_matches",
            "SAVAGE",
            entity_type="fighter",
            aliases=[{"sportsbook": "optic", "alias_kind": "id", "alias_value": "oid1"}],
        ),
    ]
    child, child_lg = apply_combat_entity_retag(parent, [_league("boxing_matches")])
    merged = next(e for e in child if e.canonical_key == "SAVAGE")
    assert merged.entity_type == "fighter"
    assert {a["sportsbook"] for a in merged.aliases} == {"kalshi", "optic"}
    assert child_lg[0].settings["entity_type"] == "fighter"


def test_retag_preserves_player_rows() -> None:
    parent = [_ent("ufc", "PROP", entity_type="player")]
    child, _ = apply_combat_entity_retag(parent, [_league("ufc")])
    assert next(e for e in child if e.canonical_key == "PROP").entity_type == "player"


def test_retag_tombstones_team_rows_via_cow_diff() -> None:
    parent = [_ent("ufc", "GAR", entity_type="team")]
    child, _ = apply_combat_entity_retag(parent, [_league("ufc")])
    deltas = diff_entities(parent, child)
    tombstones = [d for d in deltas if d.tombstone]
    upserts = [d for d in deltas if not d.tombstone]
    assert any(d.entity_type == "team" and d.canonical_key == "GAR" for d in tombstones)
    assert any(d.entity_type == "fighter" and d.canonical_key == "GAR" for d in upserts)


def test_dry_run_summary_counts_adds() -> None:
    parent = [_ent("ufc", "GAR", entity_type="team")]
    dry = dry_run_combat_retag(parent, [_league("ufc")], requested=["ufc", "boxing_matches"])
    assert dry["ok"]
    assert dry["entity_counts"]["added_count"] == 1
    assert "add 1 fighter" in dry["summary"]


def test_dry_run_refuses_non_combat_slug() -> None:
    dry = dry_run_combat_retag([], [_league("ufc")], requested=["epl"])
    assert dry["ok"] is False
    assert any("non-combat" in item for item in dry["blockers"])


def test_dry_run_refuses_missing_optic() -> None:
    dry = dry_run_combat_retag(
        [_ent("ufc", "GAR")], [_league("ufc", optic=False)], requested=["ufc"],
    )
    assert dry["ok"] is False
    assert any("optic exchange" in item for item in dry["blockers"])


def test_dry_run_already_live() -> None:
    live = [_ent("ufc", "GAR", entity_type="fighter")]
    leagues = [_league("ufc", entity_type="fighter")]
    child, child_lg = apply_combat_entity_retag(live, leagues)
    dry = dry_run_combat_retag(child, child_lg, requested=["ufc", "boxing_matches"])
    assert dry["ok"] is False
    assert any("already live" in item for item in dry["blockers"])


def test_tip_entity_type_boxing_empty_settings_stays_team() -> None:
    snap = SotSnapshot(
        rule_set_id="S0",
        entities=[],
        market_rules=[],
        leagues=[_league("boxing_matches", entity_type="")],
    )
    assert tip_entity_type(snap, "boxing_matches") == "team"
    assert match_entity_type_for_row(snap.leagues[0]) == "team"


def test_tip_entity_type_boxing_settings_fighter() -> None:
    row = _league("boxing_matches", entity_type="fighter")
    assert match_entity_type_for_row(row) == "fighter"


def test_entity_type_for_prefers_alias_bearing_row() -> None:
    store = _Store(
        [
            _ent("ufc", "DCO8", entity_type="fighter"),
            _ent(
                "ufc",
                "DCO8",
                entity_type="team",
                aliases=[{"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "DCO8"}],
            ),
        ],
        [_league("ufc")],
    )
    assert entity_type_for(store, "ufc", "DCO8") == "team"


def test_match_entity_type_for_pin_respects_league_settings() -> None:
    store = _Store([], [_league("ufc", entity_type="team")])
    assert match_entity_type_for_pin(store, "ufc") == "team"
    assert match_entity_type_for_pin(store, "ufc", "NEW1") == "team"


def test_poly_overlays_without_type_scan_fighter_bucket() -> None:
    ents = [
        _ent(
            "ufc",
            "GAR",
            entity_type="fighter",
            aliases=[{
                "sportsbook": "polymarket",
                "alias_kind": "name",
                "alias_value": "Justin Gaethje wins",
            }],
        ),
    ]
    ents[0].canonical_name = "Justin Gaethje"
    overlay = poly_team_name_aliases(ents, league="ufc")
    assert overlay


def test_candidate_refuses_non_combat_slug() -> None:
    store = _Store([_ent("ufc", "GAR")], [_league("ufc")])
    proposal = ProposalRecord(
        proposal_id="p1",
        request_id="r1",
        status="proposed",
        expected_rule_set_id="S0",
        artifact_type="combat_entity_retag",
        summary="retag",
        evidence_refs=[],
        work_item_id=None,
        payload=CombatEntityRetagPayload(leagues=["epl"]),
        proposer_subject="test",
    )
    try:
        build_candidate_slices(cast(ProposalStore, store), "S0", proposal)
    except ValidationFailedError as exc:
        assert exc.reason_code == "dry_run_failed"
        return
    raise AssertionError("expected ValidationFailedError")


def test_review_headline_names_tombstone_not_alias_delete() -> None:
    parent = [_ent("ufc", "GAR", entity_type="team")]
    leagues = [_league("ufc")]
    child, child_lg = apply_combat_entity_retag(parent, leagues)
    groups = snapshot_change_groups(parent, child, leagues, child_lg, [], [])
    proposal = ProposalRecord(
        proposal_id="p1",
        request_id="r1",
        status="validated",
        expected_rule_set_id="S0",
        artifact_type="combat_entity_retag",
        summary="retag",
        evidence_refs=[],
        work_item_id=None,
        payload=CombatEntityRetagPayload(leagues=["ufc"]),
        proposer_subject="test",
    )
    view = build_review_view(
        proposal, status="validated", changes=None, change_groups=groups,
    )
    headline = str(view["headline"]).lower()
    assert "fighter" in headline
    assert "tombstone" in headline
    assert "remove" not in headline


def test_league_update_keeps_fighter_entity_type() -> None:
    prior = _league("ufc", entity_type="fighter")
    payload = MappingLeaguePayload(
        league="ufc",
        sport="mma",
        optic_league_id="ufc",
        entity_type="team",
        exchanges=[
            ExchangePin(
                sportsbook="optic",
                parser_profile="optic_standard_v1",
            ),
        ],
    )
    out = apply_league_payload([prior], payload)
    assert out[0].settings["entity_type"] == "fighter"
