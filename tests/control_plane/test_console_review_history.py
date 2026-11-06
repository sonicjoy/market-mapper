"""Recent proposal history for the trader console."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.console_review_history import list_review_history
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ProposalRecord,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import EntityRow, InMemoryStore


def _svc() -> ProposalService:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="epl",
                entity_type="team",
                canonical_key="CHE",
                canonical_name="Chelsea",
                aliases=[],
            ),
        ],
    )
    return ProposalService(store=store)


def _alias_payload(code: str) -> EntityAliasPayload:
    return EntityAliasPayload(
        league="epl",
        canonical_key=code,
        entity_type="team",
        canonical_name=f"Team {code}",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value=code)],
    )


def _propose_alias(svc: ProposalService, *, subject: str, code: str) -> str:
    actor = Actor(subject=subject, role=ActorRole.PROPOSER)
    proposal = svc.propose(
        ProposeRequest(
            request_id=f"req_{code}",
            expected_rule_set_id="S0",
            artifact_type="entity_alias",
            summary=f"pin {code}",
            payload=_alias_payload(code),
        ),
        actor,
    )
    svc.validate(proposal.proposal_id, actor)
    return proposal.proposal_id


def test_recent_history_pending_first_then_time_desc() -> None:
    svc = _svc()
    older = _propose_alias(svc, subject="alice@wsd.com", code="OLD")
    newer = _propose_alias(svc, subject="alice@wsd.com", code="NEW")
    approver = Actor(subject="bob@wsd.com", role=ActorRole.APPROVER)
    svc.approve(older, approver)

    rows = list_review_history(svc.store, limit=10)
    assert [row["ref"] for row in rows[:2]] == [newer, older]
    assert rows[0]["status"] == "waiting_for_checker"
    assert rows[1]["status"] == "activated"
    assert rows[1]["reviewer"] == "bob@wsd.com"
    assert "T" in rows[0]["at"]


def test_recent_history_reviewer_from_reject() -> None:
    svc = _svc()
    ref = _propose_alias(svc, subject="alice@wsd.com", code="REJ")
    checker = Actor(subject="carol@wsd.com", role=ActorRole.APPROVER)
    svc.reject(ref, checker, comment="no")
    rows = list_review_history(svc.store, limit=5)
    assert rows[0]["ref"] == ref
    assert rows[0]["status"] == "rejected"
    assert rows[0]["reviewer"] == "carol@wsd.com"


def test_recent_history_brief_from_change_groups() -> None:
    svc = _svc()
    actor = Actor(subject="alice@wsd.com", role=ActorRole.PROPOSER)
    proposal = svc.propose(
        ProposeRequest(
            request_id="req_batch",
            expected_rule_set_id="S0",
            artifact_type="batch_changes",
            summary="Batch",
            payload=BatchChangesPayload(
                entity_aliases=[
                    EntityAliasPayload(
                        league="epl",
                        canonical_key="CHE",
                        entity_type="team",
                        canonical_name="Chelsea",
                        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="CHE")],
                    )
                ],
            ),
        ),
        actor,
    )
    svc.validate(proposal.proposal_id, actor)
    rows = list_review_history(svc.store, limit=5)
    assert "alias" in rows[0]["brief"].lower()


def test_history_caps_at_ten_pending_first() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    for i in range(12):
        store.put_proposal(
            ProposalRecord(
                proposal_id=f"prop_{i:02d}",
                request_id=f"req_{i:02d}",
                status="validated" if i == 11 else "activated",
                expected_rule_set_id="S0",
                artifact_type="entity_alias",
                summary=f"pin {i}",
                evidence_refs=[],
                work_item_id=None,
                payload=_alias_payload(f"C{i}"),
                proposer_subject="alice@wsd.com",
                last_occurred_at=f"2026-09-07T00:{i:02d}:00+00:00",
            )
        )
    rows = list_review_history(store, limit=10)
    assert [row["ref"] for row in rows] == ["prop_11"] + [f"prop_{i:02d}" for i in range(10, 1, -1)]


def test_review_recent_http() -> None:
    svc = _svc()
    pending = _propose_alias(svc, subject="alice@wsd.com", code="NEW")
    closed = _propose_alias(svc, subject="alice@wsd.com", code="OLD")
    svc.approve(closed, Actor(subject="bob@wsd.com", role=ActorRole.APPROVER))
    app.dependency_overrides[service] = lambda: svc
    app.dependency_overrides[get_settings] = lambda: Settings(gcp_project="marketmaking-test")
    client = TestClient(app)
    rows = client.get(
        "/review/recent",
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:bob@wsd.com"},
    ).json()
    assert rows[0]["ref"] == pending
    assert rows[0]["status"] == "waiting_for_checker"
    assert rows[1]["ref"] == closed
    assert rows[1]["reviewer"] == "bob@wsd.com"
    assert rows[1]["status"] == "activated"
