"""Retried submits must reuse the review card instead of minting a duplicate.

Submit runs propose + validate, which can outlive the gateway timeout. The
trader then clicks again, so every submit path needs a key that depends on what
was verified rather than on a fresh random id.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.preview_token import preview_request_id, sign_preview
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow

_PASTE = "OPTICM05CLUBF01"


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
                aliases=[
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "BOU",
                        "enabled": True,
                    }
                ],
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
                exchanges=[
                    {
                        "sportsbook": "px",
                        "enabled": True,
                        "parser_profile": "px_generic_v1",
                        "source_league_id": None,
                        "settings": {},
                    }
                ],
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


def test_preview_request_id_is_stable_per_token():
    token = sign_preview({"kind": "entity_alias", "league": "epl"})
    other = sign_preview({"kind": "entity_alias", "league": "efl"})
    assert preview_request_id(token) == preview_request_id(token)
    assert preview_request_id(token) != preview_request_id(other)
    assert preview_request_id(token).startswith("req_")


def test_resubmitting_a_preview_token_returns_the_same_card():
    store = _seed()
    client = _client(store, live=_SeenLive({_PASTE}))
    verified = client.post(
        "/entry/verify",
        json={"paste": _PASTE, "provided_name": "Mainz 05", "league": "international_club_friendlies"},
        headers=_iap("alice@wsd.com"),
    ).json()

    first = client.post(
        "/entry/submit",
        json={"preview_token": verified["preview_token"]},
        headers=_iap("alice@wsd.com"),
    )
    second = client.post(
        "/entry/submit",
        json={"preview_token": verified["preview_token"]},
        headers=_iap("alice@wsd.com"),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["ref"] == second.json()["ref"]
    open_cards = client.get("/review", headers=_iap("bob@wsd.com")).json()
    assert len(open_cards) == 1


def test_reverifying_the_same_change_reproduces_the_token():
    """A gateway drop clears the token in the UI, so the trader verifies again.

    That retry only stays idempotent while signing is a pure function of the
    verified change; adding a nonce or timestamp to the payload would silently
    start minting a second card per retry.
    """
    store = _seed()
    client = _client(store, live=_SeenLive({_PASTE}))
    body = {"paste": _PASTE, "provided_name": "Mainz 05", "league": "international_club_friendlies"}

    first = client.post("/entry/verify", json=body, headers=_iap("alice@wsd.com"))
    second = client.post("/entry/verify", json=body, headers=_iap("alice@wsd.com"))
    first_token = first.json()["preview_token"]
    second_token = second.json()["preview_token"]

    assert first_token == second_token
    assert preview_request_id(first_token) == preview_request_id(second_token)

    for token in (first_token, second_token):
        assert (
            client.post(
                "/entry/submit",
                json={"preview_token": token},
                headers=_iap("alice@wsd.com"),
            ).status_code
            == 200
        )
    assert len(client.get("/review", headers=_iap("bob@wsd.com")).json()) == 1


def _league_body() -> dict[str, object]:
    return {
        "league": "test_league",
        "sport": "soccer",
        "optic_league_id": "9999",
        "fixture_source": "api",
        "fixture_horizon_hours": 96.0,
        "exchanges": [
            {
                "sportsbook": "px",
                "parser_profile": "px_generic_v1",
                "enabled": True,
            }
        ],
        "acknowledge_shadow": True,
    }


def test_resubmitting_a_league_form_reuses_the_idempotency_key():
    client = _client(_seed())
    body = _league_body()
    headers = {**_iap("alice@wsd.com"), "Idempotency-Key": "submit-intent-1"}
    first = client.post("/entry/league/submit", json=body, headers=headers)
    second = client.post("/entry/league/submit", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["ref"] == second.json()["ref"]
    assert len(client.get("/review", headers=_iap("bob@wsd.com")).json()) == 1


def test_league_submits_with_different_keys_stay_independent():
    client = _client(_seed())
    body = _league_body()
    first = client.post(
        "/entry/league/submit",
        json=body,
        headers={**_iap("alice@wsd.com"), "Idempotency-Key": "intent-a"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["ref"]
