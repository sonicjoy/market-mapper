"""Secret Manager access via ADC + REST (console pod has no gcloud CLI)."""

from __future__ import annotations

import base64

import google.auth
import requests
from google.auth.transport.requests import Request as GoogleAuthRequest

_GSM_BASE = "https://secretmanager.googleapis.com/v1"


def access_secret(name: str, project: str, *, timeout: float = 15.0) -> str:
    """Read a Secret Manager latest version; raise on auth/HTTP failure."""
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    response = requests.get(
        f"{_GSM_BASE}/projects/{project}/secrets/{name}/versions/latest:access",
        headers={"authorization": f"Bearer {credentials.token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return base64.b64decode(response.json()["payload"]["data"]).decode().strip()
