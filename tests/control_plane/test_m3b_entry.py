"""M3b manual entry: paste verify → submit → review (no rule-set ids)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow

_LEAGUE = "international_club_friendlies"
_OPTIC_ID = "B29E0BFC1622"


class _SeenLive(NullLiveLookup):
    """Live lookup that marks specific pastes as seen."""

    def __init__(self, seen: set[str]) -> None:
        self._seen = seen

    def seen(self, paste: str, *, sportsbook: str | None) -> bool:
        return paste.strip().upper() in {s.upper() for s in self._seen}


def _seed() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_test_baseline",
        entities=[
            EntityRow(
                league="international_club_friendlies",
                entity_type="team",
                canonical_key="BOU",
                canonical_name="Bournemouth",
                aliases=[],
            ),
        ],
        leagues=[
            LeagueRow(
                league="international_club_friendlies",
                sport="soccer",
                optic_league_id="club_friendly_games",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
        ],
        activate=False,
    )
    return store


def _client(store: InMemoryStore, *, live: NullLiveLookup | None = None) -> TestClient:
    control = ProposalService(store, live=live or NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    return TestClient(app)


def _iap(email: str) -> dict[str, str]:
    return {"X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}"}


def test_entry_verify_blocks_bad_format():
    client = _client(_seed())
    resp = client.post(
        "/entry/verify",
        json={"paste": "not-a-ticker!!!"},
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["preview_token"] is None
    assert body["blockers"]


def test_entry_verify_optic_id_needs_name_and_live_ack():
    """Optic id with league — format ok, live miss warns, name required."""
    store = _seed()
    client = _client(store)
    paste = _OPTIC_ID
    resp = client.post(
        "/entry/verify",
        json={"paste": paste, "league": _LEAGUE},
        headers=_iap("alice@wsd.com"),
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["needs_name"] is True or any("Who is this" in b for b in body["blockers"])
    assert body["warnings"]

    resp2 = client.post(
        "/entry/verify",
        json={
            "paste": paste,
            "league": _LEAGUE,
            "provided_name": "KÍ Klaksvík",
            "acknowledge_live_warning": True,
            "note": "gap alert",
        },
        headers=_iap("alice@wsd.com"),
    )
    body2 = resp2.json()
    assert body2["ok"] is True
    assert body2["preview_token"]
    assert _OPTIC_ID in body2["preview"]["summary"]
    assert "KÍ Klaksvík" in body2["preview"]["summary"]
    assert "rule_set" not in resp2.text.lower() or "rule_set_id" not in resp2.text


def test_entry_submit_and_review_approve_hides_ids():
    store = _seed()
    live = _SeenLive({_OPTIC_ID})
    client = _client(store, live=live)
    verified = client.post(
        "/entry/verify",
        json={"paste": _OPTIC_ID, "league": _LEAGUE, "provided_name": "KÍ Klaksvík"},
        headers=_iap("alice@wsd.com"),
    ).json()
    assert verified["ok"] is True

    submitted = client.post(
        "/entry/submit",
        json={"preview_token": verified["preview_token"]},
        headers=_iap("alice@wsd.com"),
    )
    assert submitted.status_code == 200
    card = submitted.json()
    assert card["status"] == "waiting_for_checker"
    assert card["ref"]
    assert "rule_set_id" not in card
    assert "proposal_id" not in card
    assert card["code"] == _OPTIC_ID

    meta = client.get("/meta", headers=_iap("bob@wsd.com")).json()
    assert meta["env"] == "test"
    assert meta["operator"] == "bob@wsd.com"
    assert meta["role"] == "approver"

    listed = client.get("/review", headers=_iap("bob@wsd.com")).json()
    assert listed
    assert listed[0]["changes"] is None
    detail = client.get(f"/review/{card['ref']}", headers=_iap("bob@wsd.com")).json()
    assert detail["changes"] == {"added_count": 1, "removed_count": 0, "modified_count": 0}
    assert card["changes"] == detail["changes"]

    approved = client.post(
        f"/review/{card['ref']}/approve",
        headers=_iap("bob@wsd.com"),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "activated"

    rules = client.get("/console/rules", params={"q": _OPTIC_ID}).json()
    assert rules["count"] >= 1
    assert "rule_set_id" not in rules
    assert any(
        pin.get("code") == _OPTIC_ID for row in rules["entities"] for pin in (row.get("aliases") or [])
    )


def test_review_reject_and_request_changes():
    store = _seed()
    live = _SeenLive({_OPTIC_ID})
    client = _client(store, live=live)
    token = client.post(
        "/entry/verify",
        json={"paste": _OPTIC_ID, "league": _LEAGUE, "provided_name": "KÍ Klaksvík"},
        headers=_iap("alice@wsd.com"),
    ).json()["preview_token"]
    ref = client.post(
        "/entry/submit",
        json={"preview_token": token},
        headers=_iap("alice@wsd.com"),
    ).json()["ref"]

    rejected = client.post(
        f"/review/{ref}/reject",
        json={"comment": "wrong team"},
        headers=_iap("bob@wsd.com"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    listed = client.get("/review", headers=_iap("bob@wsd.com")).json()
    assert all(card["ref"] != ref for card in listed)
    detail = client.get(f"/review/{ref}", headers=_iap("bob@wsd.com")).json()
    assert detail["status"] == "rejected"


def test_healthz_ok():
    store = _seed()
    client = _client(store)
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/healthz").json() == {"ok": True}


def test_entry_verify_optic_id_needs_league():
    client = _client(_seed())
    body = client.post(
        "/entry/verify",
        json={"paste": "B29E0BFC1622", "provided_name": "KÍ Klaksvík"},
        headers=_iap("alice@wsd.com"),
    ).json()
    assert body["ok"] is False
    assert body["needs_league"] is True


def test_entry_verify_optic_id_with_league():
    client = _client(_seed())
    body = client.post(
        "/entry/verify",
        json={
            "paste": "B29E0BFC1622",
            "provided_name": "KÍ Klaksvík",
            "league": "international_club_friendlies",
            "acknowledge_live_warning": True,
        },
        headers=_iap("alice@wsd.com"),
    ).json()
    assert body["ok"] is True
    assert "Optic" in body["preview"]["summary"]
    assert "B29E0BFC1622" in body["preview"]["summary"]


def test_inbox_http_removed():
    client = _client(_seed())
    headers = _iap("alice@wsd.com")
    assert client.get("/inbox", headers=headers).status_code == 404
    assert client.post("/inbox/ingest", json={"fingerprint": "x", "source": "form"}, headers=headers).status_code == 404

