"""M3c Mapper Chat HTTP surface (enabled/disabled)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore


def _client(*, chat_enabled: bool) -> TestClient:
    session_bag().clear()
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="england_-_premier_league",
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
    control = ProposalService(store, live=NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
        chat_enabled=chat_enabled,
        chat_provider="fake",
    )
    return TestClient(app)


def _iap(email: str) -> dict[str, str]:
    return {"X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}"}


def test_meta_exposes_chat_enabled():
    client = _client(chat_enabled=True)
    meta = client.get("/meta", headers=_iap("alice@wsd.com")).json()
    assert meta["chat_enabled"] is True


def test_chat_clarify_when_enabled():
    client = _client(chat_enabled=True)
    resp = client.post(
        "/chat",
        json={"message": "pin something", "conversation_id": "conv_test"},
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_available"] is True
    assert body["conversation_id"] == "conv_test"
    assert body["reply_markdown"]


def test_chat_disabled_returns_unavailable():
    client = _client(chat_enabled=False)
    resp = client.post(
        "/chat",
        json={"message": "hello"},
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_available"] is False
    assert "disabled" in body["reply_markdown"].lower()
