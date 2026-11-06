"""Unit tests for gsm_secret.access_secret (ADC/REST, no gcloud)."""

from __future__ import annotations

import base64

import pytest

from mappers.control_plane import gsm_secret


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_access_secret_decodes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "tok"
    raw = "super-secret-key"

    class _Creds:
        def __init__(self) -> None:
            self.token = token

        def refresh(self, _request: object) -> None:
            self.token = token

    monkeypatch.setattr(
        gsm_secret.google.auth,
        "default",
        lambda scopes=None: (_Creds(), "proj"),
    )
    monkeypatch.setattr(
        gsm_secret.requests,
        "get",
        lambda url, headers=None, timeout=None: _Resp(
            {"payload": {"data": base64.b64encode(raw.encode()).decode()}}
        ),
    )
    assert gsm_secret.access_secret("my-secret", "marketmaking-test") == raw
