"""Sink for the estate's central alert engine (MMutils ``services/alert_engine_service``).

The engine is the trader console's alert worklist (mm-trading-dash ``/api/alerts`` proxies
``http://alert-engine-service.alert-engine``). Today it only raises alerts from its own rules
over its trade feeds; it has no route for an external producer. This sink posts to the
route added for it by MMutils#168, ``POST /v1/alerts/external``, authenticated with the
shared service token (``X-MM-Service-Token``). It stays OFF until both
``MAPPING_ALERT_ENGINE_URL`` (e.g. ``http://alert-engine-service.alert-engine``) and
``MAPPING_ALERT_ENGINE_TOKEN`` are set.

The engine drops an open alert that goes 6h without a post and turns a repeat post
inside the cooldown into a silent reinforce, so the job posts EVERY current high-risk
served mapping each run (Slack keeps its own 24h dedupe).

One engine alert per mapping: ``rule_id = MAPPING_RISK`` and ``scope_key`` = the mapping
fingerprint, so the engine's fire-lock (``alert_id_for(rule_id, scope_key)``) is the
identity and ack / resolve / snooze work per mapping in the console.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

ENGINE_URL_ENV = "MAPPING_ALERT_ENGINE_URL"
ENGINE_TOKEN_ENV = "MAPPING_ALERT_ENGINE_TOKEN"  # nosec B105 - env var NAME, the token is read at runtime
TOKEN_HEADER = "X-MM-Service-Token"  # nosec B105 - HTTP header NAME, not a credential
RULE_ID = "MAPPING_RISK"
EXTERNAL_PATH = "/v1/alerts/external"
COOLDOWN_S = 24 * 3600

PostFn = Callable[[str, dict[str, Any], dict[str, str]], int]


def _post(url: str, body: dict[str, Any], headers: dict[str, str]) -> int:
    """POST JSON, return the HTTP status (never raises for a non-2xx)."""
    return requests.post(url, json=body, timeout=10, headers=headers).status_code


def engine_payload(row: dict[str, Any], *, link: str) -> dict[str, Any]:
    """The proposed external-alert body for one high-risk served mapping."""
    reasons = [s.get("code") for s in row.get("signals") or []]
    what = f"{row.get('league') or ''} {row.get('market_id') or ''} / {row.get('selection') or ''}".strip()
    return {
        "rule_id": RULE_ID,
        "scope_type": "mapping",
        "scope_key": row["fingerprint"],
        "platform": row.get("sb") or "",
        "severity_band": "HIGH",
        "cooldown_s": COOLDOWN_S,
        "title": f"Possible mismapping on {row.get('book') or row.get('sb')}: {what}",
        "summary": "; ".join(s.get("text") or "" for s in row.get("signals") or []),
        "evidence": {
            "reasons": reasons,
            "venue_key": row.get("src_key"),
            "venue_market": row.get("src_market"),
            "venue_selection": row.get("src_selection"),
            "game_id": row.get("game_id"),
            "market_id": row.get("market_id"),
            "selection": row.get("selection"),
            "start_date": row.get("start_date"),
            "link": link,
        },
        "source": "mmmapper",
    }


class EngineAlertSink:
    """Best-effort poster of MAPPING_RISK alerts; disabled when no base URL is set."""

    def __init__(self, base_url: str, *, token: str = "", post_fn: PostFn | None = None) -> None:
        """Configure the sink; an empty ``base_url`` or ``token`` disables it."""
        self._url = f"{base_url.rstrip('/')}{EXTERNAL_PATH}" if base_url.strip() else ""
        self._headers = {TOKEN_HEADER: token.strip(), "X-MM-Operator": "mmmapper-mismap-alert"}
        self._post = post_fn or _post

    @property
    def enabled(self) -> bool:
        """True when both the base URL and the service token are configured."""
        return bool(self._url and self._headers[TOKEN_HEADER])

    def raise_alerts(self, rows: list[dict[str, Any]], *, link: str) -> int:
        """Post one alert per row; return how many the engine accepted (2xx)."""
        if not self.enabled:
            return 0
        accepted = 0
        for row in rows:
            try:
                status = self._post(self._url, engine_payload(row, link=link), self._headers)
            except requests.RequestException:
                logger.exception("alert engine unreachable; stopping this run")
                break
            if 200 <= status < 300:
                accepted += 1
            else:
                logger.warning("alert engine refused %s: HTTP %s", row.get("fingerprint"), status)
        return accepted


def build_engine_sink() -> EngineAlertSink:
    """Sink from ``MAPPING_ALERT_ENGINE_URL`` + ``MAPPING_ALERT_ENGINE_TOKEN`` (either unset = off)."""
    return EngineAlertSink(os.getenv(ENGINE_URL_ENV, ""), token=os.getenv(ENGINE_TOKEN_ENV, ""))
