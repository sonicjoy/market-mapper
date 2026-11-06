"""Structured Mapper Chat activity events (Cloud Logging via stdlib JSON)."""

from __future__ import annotations

import json
import logging
from typing import Any

_LOG = logging.getLogger("mapping.control_plane.chat")
_TRUNC = 400


def _trunc(text: str, limit: int = _TRUNC) -> str:
    s = (text or "").strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


def log_chat_step(**fields: Any) -> None:
    """Emit one skill step record (join on conversation_id)."""
    payload = {"event_type": "mapping_chat_step", **fields}
    _LOG.info("%s", json.dumps(payload, default=str, separators=(",", ":")))


def log_chat_turn(**fields: Any) -> None:
    """Emit one chat turn activity record for debug/eval."""
    if "message" in fields:
        fields["message"] = _trunc(str(fields["message"]))
    if "reply" in fields:
        fields["reply"] = _trunc(str(fields["reply"]))
    payload = {"event_type": "mapping_chat_turn", **fields}
    _LOG.info("%s", json.dumps(payload, default=str, separators=(",", ":")))
