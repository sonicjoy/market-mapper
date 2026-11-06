"""HMAC preview tokens for entry verify → submit."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

_PREVIEW_SECRET = os.environ.get(
    "MAPPING_CP_PREVIEW_SECRET",
    "m3b-dev-preview-secret",  # nosec B105 — override in deploy via env
)


def sign_preview(payload: dict[str, Any]) -> str:
    """Return opaque preview token (payload.hmac)."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hmac.new(_PREVIEW_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{digest}"


def preview_request_id(token: str) -> str:
    """Deterministic idempotency key for one verified preview.

    Submit runs propose + validate, which can outlive the gateway timeout. The
    trader then retries, so the key must depend only on what was verified —
    a fresh random id would mint a second review card for the same change.
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"req_{digest[:24]}"


def unsign_preview(token: str) -> dict[str, Any]:
    """Verify and decode a preview token."""
    if "." not in token:
        raise ValueError("invalid preview token")
    body, digest = token.rsplit(".", 1)
    expected = hmac.new(_PREVIEW_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise ValueError("invalid preview token")
    return json.loads(body)
