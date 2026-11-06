"""Prod activate flag and one-shot CLI."""

from __future__ import annotations

from BigQuery.activate_mapping_rule_set import activate_named_rule_set, main
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    EntityAliasPayload,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore


def _proposer() -> Actor:
    return Actor(subject="trader.alice", role=ActorRole.PROPOSER)


def _approver() -> Actor:
    return Actor(subject="trader.bob", role=ActorRole.APPROVER)


def test_settings_allow_activate_test_always():
    assert Settings(gcp_project="marketmaking-test").allow_activate is True
    assert (
        Settings(
            gcp_project="marketmaking-test",
            allow_activate_override=False,
        ).allow_activate
        is True
    )


def test_settings_allow_activate_prod_flag(monkeypatch):
    assert Settings(gcp_project="rs-marketmaking").allow_activate is False
    assert (
        Settings(
            gcp_project="rs-marketmaking",
            allow_activate_override=True,
        ).allow_activate
        is True
    )
    monkeypatch.setenv("GCP_PROJECT", "rs-marketmaking")
    monkeypatch.setenv("MAPPING_CP_ALLOW_ACTIVATE", "1")
    get_settings.cache_clear()
    try:
        assert get_settings().allow_activate is True
    finally:
        get_settings.cache_clear()


def test_prod_approve_activates_when_allowed():
    store = InMemoryStore(environment="prod", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0_prod", entities=[], activate=False)
    svc = ProposalService(store)
    prop = svc.propose(
        ProposeRequest(
            request_id="req_prod_on",
            expected_rule_set_id="S0_prod",
            summary="prod on",
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
    assert out.status == "activated"
    assert out.activated_rule_set_id is not None


def test_cli_refuses_without_confirm(monkeypatch, capsys):
    monkeypatch.setenv("GCP_PROJECT", "rs-marketmaking")
    assert main(["--rule-set-id", "S0_x"]) == 2
    assert "i-mean-it" in capsys.readouterr().err


def test_cli_activate_named_rule_set():
    store = InMemoryStore(environment="prod", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0_prod", entities=[], activate=False)
    out = activate_named_rule_set(store, "S0_prod", actor_subject="cli:test")
    assert out["already_active"] is False
    assert out["rule_set_id"] == "S0_prod"
    assert store.activated_rule_set_id == "S0_prod"
    again = activate_named_rule_set(store, "S0_prod", actor_subject="cli:test")
    assert again["already_active"] is True
