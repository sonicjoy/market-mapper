"""M3a MVP: entity_alias propose → validate → approve → test activate.

Realistic fixtures from 2026-08-10 prod Kalshi gap alert.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.auth import (
    UNKNOWN_OPERATOR,
    operator_email,
    resolve_role,
)
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    ConflictError,
    EntityAliasPayload,
    ForbiddenError,
    ProposeRequest,
    ValidationFailedError,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import EntityRow, InMemoryStore


def _seed_friendlies_baseline() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_test_baseline",
        entities=[
            EntityRow(
                league="international_club_friendlies",
                entity_type="team",
                canonical_key="BOU",
                canonical_name="Bournemouth",
                aliases=[
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "BOU",
                        "enabled": True,
                    }
                ],
            ),
            EntityRow(
                league="itf_women",
                entity_type="player",
                canonical_key="BOR",
                canonical_name="Victoria Borodulina",
                aliases=[
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "BOR",
                        "enabled": True,
                    }
                ],
            ),
        ],
        activate=False,
    )
    return store


def _proposer() -> Actor:
    return Actor(subject="trader.alice", role=ActorRole.PROPOSER)


def _approver() -> Actor:
    return Actor(subject="trader.bob", role=ActorRole.APPROVER)


def _alias_req(request_id: str, key: str, alias: str) -> ProposeRequest:
    """Friendlies kalshi code pin against the seeded tip."""
    return ProposeRequest(
        request_id=request_id,
        expected_rule_set_id="S0_test_baseline",
        summary=request_id,
        payload=EntityAliasPayload(
            league="international_club_friendlies",
            canonical_key=key,
            aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value=alias)],
        ),
    )


def _client(store: InMemoryStore) -> TestClient:
    control = ProposalService(store)
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    return TestClient(app)


def test_happy_path_lfc_to_liv_friendlies():
    """KXCLUBFGAME-26AUG16LFCCOM — pin kalshi LFC → canonical LIV."""
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    req = ProposeRequest(
        request_id="req_lfc_liv_001",
        expected_rule_set_id="S0_test_baseline",
        summary="Pin LFC → LIV for club friendlies (Liverpool vs Como)",
        evidence_refs=["gap:KXCLUBFGAME-26AUG16LFCCOM", "kalshi:title:Liverpool vs Como"],
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
    prop = svc.propose(req, _proposer())
    assert prop.status == "proposed"
    validated = svc.validate(prop.proposal_id, _proposer())
    assert validated.status == "validated"
    assert validated.dry_run["ok"] is True
    assert validated.candidate_rule_set_id

    approved = svc.approve(prop.proposal_id, _approver())
    assert approved.status == "activated"
    assert approved.activated_rule_set_id == validated.candidate_rule_set_id

    rules = svc.list_rules()
    assert rules["rule_set_id"] == approved.activated_rule_set_id
    liv = next(e for e in rules["entities"] if e["canonical_key"] == "LIV")
    assert any(a["alias_value"] == "LFC" for a in liv["aliases"])

    types = [a["event_type"] for a in store.audits]
    assert types == [
        "rule_proposed",
        "rule_validated",
        "rule_approved",
        "rule_set_activated",
    ]


def test_m05_mainz_digit_code_alias():
    """KXCLUBFGAME-26AUG15M05BOU — Mainz 05 digit code after regex fix."""
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_m05_001",
            expected_rule_set_id="S0_test_baseline",
            summary="Stub M05 Mainz for club friendlies",
            evidence_refs=["gap:KXCLUBFGAME-26AUG15M05BOU", "kalshi:title:Mainz vs Bournemouth"],
            payload=EntityAliasPayload(
                league="international_club_friendlies",
                canonical_key="M05",
                canonical_name="Mainz 05",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="M05"),
                ],
            ),
        ),
        _proposer(),
    )
    svc.validate(prop.proposal_id, _proposer())
    out = svc.approve(prop.proposal_id, _approver())
    assert out.status == "activated"


def test_bor_collision_borrasca_uses_bor2_multimap():
    """GUEBOR: Borrasca must not steal Victoria Borodulina's BOR canonical."""
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_bor2_001",
            expected_rule_set_id="S0_test_baseline",
            summary="Pin BOR → BOR2 (Borrasca); keep BOR on Borodulina",
            evidence_refs=["gap:KXITFWMATCH-26AUG10GUEBOR"],
            payload=EntityAliasPayload(
                league="itf_women",
                canonical_key="BOR2",
                entity_type="player",
                canonical_name="Borrasca",
                aliases=[
                    AliasPin(
                        sportsbook="px",
                        alias_kind="code",
                        alias_value="BOR",
                        disambiguation_name="Borrasca",
                    ),
                ],
            ),
        ),
        _proposer(),
    )
    validated = svc.validate(prop.proposal_id, _proposer())
    assert validated.dry_run["ok"] is True
    assert validated.dry_run["alias_checks"][0]["multimap"] is True
    assert validated.dry_run["alias_checks"][0]["disambiguated"] is True
    claimants = validated.dry_run["alias_checks"][0]["claimants"]
    assert "BOR" in claimants and "BOR2" in claimants
    svc.approve(prop.proposal_id, _approver())


def test_ambiguous_alias_without_disambiguation_fails_validation():
    """A collision cannot activate without disambiguation evidence."""
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_bor_ambiguous",
            expected_rule_set_id="S0_test_baseline",
            summary="Unsafe BOR collision",
            payload=EntityAliasPayload(
                league="itf_women",
                canonical_key="BOR2",
                entity_type="player",
                canonical_name="Borrasca",
                aliases=[
                    AliasPin(
                        sportsbook="px",
                        alias_kind="code",
                        alias_value="BOR",
                    ),
                ],
            ),
        ),
        _proposer(),
    )
    with pytest.raises(ValidationFailedError, match="thin dry-run failed"):
        svc.validate(prop.proposal_id, _proposer())


def test_stale_expected_rule_set_id_returns_conflict():
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    # Activate a first proposal so current moves.
    prop = svc.propose(
        ProposeRequest(
            request_id="req_first",
            expected_rule_set_id="S0_test_baseline",
            summary="first",
            payload=EntityAliasPayload(
                league="international_club_friendlies",
                canonical_key="COM",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="COM"),
                ],
            ),
        ),
        _proposer(),
    )
    svc.validate(prop.proposal_id, _proposer())
    svc.approve(prop.proposal_id, _approver())

    with pytest.raises(ConflictError) as exc:
        svc.propose(
            ProposeRequest(
                request_id="req_stale",
                expected_rule_set_id="S0_test_baseline",
                summary="stale",
                payload=EntityAliasPayload(
                    league="international_club_friendlies",
                    canonical_key="SCH",
                    aliases=[
                        AliasPin(sportsbook="px", alias_kind="code", alias_value="SCH"),
                    ],
                ),
            ),
            _proposer(),
        )
    assert exc.value.reason_code == "stale_rule_set"


def test_approve_rebases_stale_sibling_onto_new_tip():
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    first = svc.propose(_alias_req("req_first_com", "COM", "COM"), _proposer())
    second = svc.propose(_alias_req("req_second_sch", "SCH", "SCH"), _proposer())
    svc.validate(first.proposal_id, _proposer())
    svc.validate(second.proposal_id, _proposer())
    activated = svc.approve(first.proposal_id, _approver())

    with pytest.raises(ConflictError) as exc:
        svc.validate(second.proposal_id, _proposer())
    assert exc.value.reason_code == "stale_rule_set"

    out = svc.approve(second.proposal_id, _approver())
    assert out.status == "activated"
    assert out.activated_rule_set_id != activated.activated_rule_set_id
    rebased = svc.get_proposal(second.proposal_id)
    assert rebased.expected_rule_set_id == activated.activated_rule_set_id
    keys = {row["canonical_key"] for row in svc.list_rules()["entities"]}
    assert {"COM", "SCH"} <= keys
    types = [row["event_type"] for row in store.audits if row["proposal_id"] == second.proposal_id]
    assert types == [
        "rule_proposed",
        "rule_validated",
        "rule_validated",
        "rule_approved",
        "rule_set_activated",
    ]


def test_approve_rebase_dry_run_failure_keeps_old_expected():
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    first = svc.propose(_alias_req("req_com_owner", "COM", "COM"), _proposer())
    steal = svc.propose(_alias_req("req_com_steal", "SCH", "COM"), _proposer())
    svc.validate(first.proposal_id, _proposer())
    svc.validate(steal.proposal_id, _proposer())
    svc.approve(first.proposal_id, _approver())
    with pytest.raises(ValidationFailedError) as exc:
        svc.approve(steal.proposal_id, _approver())
    assert exc.value.reason_code == "dry_run_failed"
    assert svc.get_proposal(steal.proposal_id).expected_rule_set_id == "S0_test_baseline"


def test_maker_checker_blocks_self_approve():
    store = _seed_friendlies_baseline()
    svc = ProposalService(store, require_maker_checker=True)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_self",
            expected_rule_set_id="S0_test_baseline",
            summary="self",
            payload=EntityAliasPayload(
                league="lol",
                canonical_key="LGG",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="LGU"),
                ],
            ),
        ),
        _proposer(),
    )
    svc.validate(prop.proposal_id, _proposer())
    with pytest.raises(ForbiddenError) as exc:
        svc.approve(prop.proposal_id, _proposer())
    assert exc.value.reason_code == "maker_checker"


def test_default_allows_self_approve():
    """Default require_maker_checker=False — solo operator can approve own pin."""
    store = _seed_friendlies_baseline()
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_solo",
            expected_rule_set_id="S0_test_baseline",
            summary="solo",
            payload=EntityAliasPayload(
                league="lol",
                canonical_key="UWI",
                canonical_name="Uwinks",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="UWI"),
                ],
            ),
        ),
        _proposer(),
    )
    svc.validate(prop.proposal_id, _proposer())
    approved = svc.approve(prop.proposal_id, _proposer())
    assert approved.status == "activated"


def test_prod_activate_disabled():
    store = InMemoryStore(environment="prod", allow_activate=False)
    store.seed_rule_set(rule_set_id="S0_prod", entities=[], activate=False)
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_prod",
            expected_rule_set_id="S0_prod",
            summary="prod",
            payload=EntityAliasPayload(
                league="ufc",
                entity_type="fighter",
                canonical_key="WEL",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="WEL"),
                ],
            ),
        ),
        _proposer(),
    )
    svc.validate(prop.proposal_id, _proposer())
    out = svc.approve(prop.proposal_id, _approver())
    assert out.status == "approved"
    assert out.activated_rule_set_id is None


def test_http_happy_path_and_stale_409():
    """Executable API exposes the locked M3a lifecycle and conflict status.

    Identity comes from the IAP header; the approver role is granted by the
    server-side allow-list (bob@wsd.com), never a client-supplied role header.
    """
    client = _client(_seed_friendlies_baseline())
    proposer_headers = {
        "X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com",
    }
    approver_headers = {
        "X-Goog-Authenticated-User-Email": "accounts.google.com:bob@wsd.com",
    }
    body = {
        "request_id": "req_http_lfc",
        "expected_rule_set_id": "S0_test_baseline",
        "artifact_type": "entity_alias",
        "summary": "LFC to LIV",
        "payload": {
            "league": "international_club_friendlies",
            "canonical_key": "LIV",
            "canonical_name": "Liverpool",
            "aliases": [
                {
                    "sportsbook": "px",
                    "alias_kind": "code",
                    "alias_value": "LFC",
                }
            ],
        },
    }
    proposed = client.post("/proposals", headers=proposer_headers, json=body)
    assert proposed.status_code == 200
    proposal_id = proposed.json()["proposal_id"]
    assert client.post(f"/proposals/{proposal_id}/validate", headers=proposer_headers).status_code == 200
    approved = client.post(f"/proposals/{proposal_id}/approve", headers=approver_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "activated"

    body["request_id"] = "req_http_stale"
    stale = client.post("/proposals", headers=proposer_headers, json=body)
    assert stale.status_code == 409


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def test_operator_email_strips_iap_namespace_prefix():
    """IAP identity namespace prefix is stripped; absent header → unknown."""
    assert operator_email(_request({})) == UNKNOWN_OPERATOR
    email = operator_email(_request({"X-Goog-Authenticated-User-Email": "accounts.google.com:carol@wsd.com"}))
    assert email == "carol@wsd.com"


def test_resolve_role_from_allow_lists_not_headers():
    """Role comes from IAP identity; admin allow-list; default → approver."""
    settings = Settings(
        gcp_project="marketmaking-test",
        admin_emails=frozenset({"root@wsd.com"}),
    )
    assert resolve_role(UNKNOWN_OPERATOR, settings) == ActorRole.VIEWER
    assert resolve_role("alice@wsd.com", settings) == ActorRole.APPROVER
    assert resolve_role("bob@wsd.com", settings) == ActorRole.APPROVER
    assert resolve_role("root@wsd.com", settings) == ActorRole.ADMIN
