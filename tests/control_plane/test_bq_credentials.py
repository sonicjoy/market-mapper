"""Expired/unmintable BigQuery credentials surface as 503, not a bare 500."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.auth import exceptions as google_auth_exceptions

from mappers.control_plane.app import app, service
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore


class _ExpiredCredentialsStore(InMemoryStore):
    """Store whose tip read fails the way expired ADC fails in production."""

    @property
    def current_rule_set_id(self) -> str | None:
        raise google_auth_exceptions.RefreshError(
            "Reauthentication is needed. Please run `gcloud auth application-default login`",
        )


def _client() -> TestClient:
    store = _ExpiredCredentialsStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    return TestClient(app)


def test_console_rules_reports_credentials_failure_as_503():
    client = _client()
    resp = client.get("/console/rules", params={"q": "EPL", "kind": "leagues"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["reason_code"] == "bq_credentials"
    assert "application-default login" in detail["message"]
