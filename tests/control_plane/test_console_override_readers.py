"""Catalog refuses active overrides for venues that never read opticodds_mapping (mmmapper#19)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from BigQuery.override_lane import LANE_ENV, LANE_POLYUSA_ENV
from mappers.control_plane import console_override_ops
from mappers.control_plane.app import app, service
from mappers.control_plane.console_override_readers import (
    override_unread_reason,
    override_unread_sportsbooks,
)
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.models import Actor, ActorRole, ValidationFailedError
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore

_BODY = {
    "game_id": "g1",
    "market_id": "moneyline",
    "selection": "Team A",
    "source_market_id": "NX.F.OPT.NFL-00001-260927-M.O.1.1.20261130",
    "reason": "operator fix",
}


def _control() -> ProposalService:
    return ProposalService(InMemoryStore(environment="test", allow_activate=True), live=NullLiveLookup())


def _actor() -> Actor:
    return Actor(subject="alice@wsd.com", role=ActorRole.ADMIN)


@pytest.mark.parametrize("book", ["crypto.com", "CRYPTO.COM", "Polymarket (USA)", "polymarket (usa)"])
def test_unread_venues_have_a_reason(book: str) -> None:
    assert override_unread_reason(book)


@pytest.mark.parametrize("book", ["Kalshi", "Polymarket", "Prophet X", "SX Bet", "Novig", ""])
def test_read_venues_are_not_blocked(book: str) -> None:
    assert override_unread_reason(book) is None


def test_meta_payload_uses_canonical_names() -> None:
    assert set(override_unread_sportsbooks()) == {"crypto.com", "Polymarket (USA)"}


def test_active_crypto_override_is_refused_before_any_bigquery_call() -> None:
    with (
        patch.object(console_override_ops.bigquery, "Client", side_effect=AssertionError("no BQ")),
        pytest.raises(ValidationFailedError) as err,
    ):
        _control().console_catalog_override({**_BODY, "sportsbook": "crypto.com"}, _actor())
    assert err.value.reason_code == "override_not_read"
    assert "market_mapping" in str(err.value)


def test_deactivating_a_crypto_override_is_still_allowed() -> None:
    started = MagicMock(return_value={"job_id": "j1"})
    with (
        patch.object(console_override_ops.bigquery, "Client", MagicMock()),
        patch.object(console_override_ops, "_resolved_override_body", side_effect=lambda body, **_: body),
        patch.object(console_override_ops, "_start_catalog_override_job", started),
    ):
        out = _control().console_catalog_override({**_BODY, "sportsbook": "crypto.com", "active": False}, _actor())
    assert out == {"job_id": "j1"}
    assert started.call_args.kwargs["active"] is False


def test_meta_lists_unread_sportsbooks() -> None:
    control = _control()
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(gcp_project="marketmaking-test")
    try:
        meta = (
            TestClient(app)
            .get("/meta", headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"})
            .json()
        )
    finally:
        app.dependency_overrides.clear()
    assert set(meta["override_unread_sportsbooks"]) == {"crypto.com", "Polymarket (USA)"}


def test_lane_unblocks_crypto_but_not_polymarket_usa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LANE_ENV, "1")
    monkeypatch.delenv(LANE_POLYUSA_ENV, raising=False)
    assert override_unread_reason("crypto.com") is None
    assert override_unread_reason("Polymarket (USA)")
    assert set(override_unread_sportsbooks()) == {"Polymarket (USA)"}
    monkeypatch.setenv(LANE_POLYUSA_ENV, "1")
    assert override_unread_sportsbooks() == {}
