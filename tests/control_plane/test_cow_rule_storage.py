"""COW rule storage: delta writes, coalesce, current, as-of, validity history."""

from __future__ import annotations

from mappers.control_plane.cow_diff import entity_key_str
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    EntityAliasPayload,
    ProposeRequest,
)
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import EntityRow, InMemoryStore, RuleSetReceipt


def _seed_large_baseline() -> InMemoryStore:
    """Dense base with many entities so delta size is obvious."""
    store = InMemoryStore(environment="test", allow_activate=True, cow=True)
    entities = [
        EntityRow(
            league="international_club_friendlies",
            entity_type="team",
            canonical_key=f"T{i:03d}",
            canonical_name=f"Team {i}",
            aliases=[
                {
                    "sportsbook": "px",
                    "alias_kind": "code",
                    "alias_value": f"T{i:03d}",
                    "enabled": True,
                }
            ],
        )
        for i in range(50)
    ]
    store.seed_rule_set(rule_set_id="S0_cow_base", entities=entities, activate=True)
    return store


def _pin_request() -> ProposeRequest:
    return ProposeRequest(
        request_id="req_cow_pin_001",
        expected_rule_set_id="S0_cow_base",
        summary="Pin LFC → LIV",
        evidence_refs=["gap:test"],
        payload=EntityAliasPayload(
            league="international_club_friendlies",
            canonical_key="LIV",
            entity_type="team",
            canonical_name="Liverpool",
            aliases=[
                AliasPin(sportsbook="px", alias_kind="code", alias_value="LFC"),
            ],
        ),
    )


def test_cow_propose_stores_only_delta_rows():
    store = _seed_large_baseline()
    svc = ProposalService(store)
    prop = svc.propose(_pin_request(), Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.validate(prop.proposal_id, Actor(subject="alice", role=ActorRole.PROPOSER))
    refreshed = store.get_proposal(prop.proposal_id)
    assert refreshed is not None
    cid = refreshed.candidate_rule_set_id
    assert cid
    deltas = store.stored_entity_deltas(cid)
    assert len(deltas) == 1
    assert deltas[0].canonical_key == "LIV"
    assert not deltas[0].tombstone
    logical = store.entities_for(cid)
    assert len(logical) == 51
    assert any(e.canonical_key == "LIV" for e in logical)
    assert any(e.canonical_key == "T000" for e in logical)


def test_cow_reconstruct_matches_full_snapshot_semantics():
    store = _seed_large_baseline()
    parent = store.entities_for("S0_cow_base")
    svc = ProposalService(store)
    prop = svc.propose(_pin_request(), Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.validate(prop.proposal_id, Actor(subject="alice", role=ActorRole.PROPOSER))
    cid = store.get_proposal(prop.proposal_id).candidate_rule_set_id  # type: ignore[union-attr]
    assert cid
    child = store.entities_for(cid)
    parent_keys = {(e.league, e.entity_type, e.canonical_key) for e in parent}
    child_keys = {(e.league, e.entity_type, e.canonical_key) for e in child}
    assert parent_keys < child_keys
    assert ("international_club_friendlies", "team", "LIV") in child_keys


def test_cow_activate_materializes_current_and_validity_history():
    store = _seed_large_baseline()
    svc = ProposalService(store)
    prop = svc.propose(_pin_request(), Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.validate(prop.proposal_id, Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.approve(
        prop.proposal_id,
        Actor(subject="bob", role=ActorRole.APPROVER),
    )
    assert len(store.current_entities) == 51
    assert any(e.canonical_key == "LIV" for e in store.current_entities)
    key = entity_key_str(
        EntityRow(
            league="international_club_friendlies",
            entity_type="team",
            canonical_key="LIV",
            canonical_name="Liverpool",
            aliases=[],
        )
    )
    windows = store.rule_history(table_kind="entity", natural_key=key)
    assert windows
    assert windows[0].effective_from
    assert windows[0].effective_to is None
    assert windows[0].enabled is True


def test_cow_as_of_uses_activation_timeline():
    store = _seed_large_baseline()
    svc = ProposalService(store)
    prop = svc.propose(_pin_request(), Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.validate(prop.proposal_id, Actor(subject="alice", role=ActorRole.PROPOSER))
    before = "2099-01-01T00:00:00+00:00"
    # No activation yet after seed activate at seed time — seed activate did not
    # append audit; tip is still S0 via _current_rule_set_id.
    tip = store.rule_set_as_of(before)
    assert tip == "S0_cow_base"
    svc.approve(prop.proposal_id, Actor(subject="bob", role=ActorRole.APPROVER))
    activated = [a for a in store.audits if a.get("event_type") == "rule_set_activated"]
    assert activated
    ts = str(activated[0]["occurred_at"])
    assert store.rule_set_as_of(ts) == store.current_rule_set_id


def test_console_rule_history_api_shape():
    store = _seed_large_baseline()
    svc = ProposalService(store)
    prop = svc.propose(_pin_request(), Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.validate(prop.proposal_id, Actor(subject="alice", role=ActorRole.PROPOSER))
    svc.approve(prop.proposal_id, Actor(subject="bob", role=ActorRole.APPROVER))
    body = svc.rule_history(
        kind="entity",
        league="international_club_friendlies",
        entity_type="team",
        canonical_key="LIV",
    )
    assert body["natural_key"].endswith("|LIV")
    assert body["windows"]
    assert "effective_from" in body["windows"][0]


def _league_row(name: str) -> LeagueRow:
    return LeagueRow(
        league=name,
        sport="soccer",
        optic_league_id=name,
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[],
    )


def test_reads_coalesce_delta_layers_even_when_cow_writes_off():
    store = InMemoryStore(environment="test", cow=False)
    store.seed_rule_set(
        rule_set_id="S0_root",
        entities=[],
        leagues=[_league_row("epl"), _league_row("nba")],
    )
    store.rule_sets["P_tip"] = RuleSetReceipt(
        rule_set_id="P_tip",
        parent_rule_set_id="S0_root",
        snapshot_sha256="x",
        proposal_ids=[],
        created_via="ui",
        environment="test",
    )
    store.leagues["P_tip"] = [_league_row("italy_serie_a")]
    names = {row.league for row in store.leagues_for("P_tip")}
    assert names == {"epl", "nba", "italy_serie_a"}
