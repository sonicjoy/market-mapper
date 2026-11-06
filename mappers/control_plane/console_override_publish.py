"""Publish mapping_override messages from the mapping console (Release 068 G5)."""

from __future__ import annotations

import json
import logging
import os

from google.cloud import pubsub_v1

from mappers.control_plane.console_sportsbook import canonical_sportsbook
from synthetic.writers import OVERRIDE_TOPIC, build_override_message

logger = logging.getLogger(__name__)

CONSOLE_OVERRIDE_SOURCE = "mapping-console"
_CONSOLE_OVERRIDE_SOURCE = CONSOLE_OVERRIDE_SOURCE


def _publisher() -> pubsub_v1.PublisherClient:
    return pubsub_v1.PublisherClient()


def _topic_path(project: str) -> str:
    return _publisher().topic_path(project, OVERRIDE_TOPIC)


def console_override_attributes(operator: str, reason: str) -> dict[str, str]:
    """Pub/Sub attributes stored on mapping_override rows."""
    attrs = {
        "source": _CONSOLE_OVERRIDE_SOURCE,
        "operator": operator.strip() or "unknown",
    }
    reason = reason.strip()
    if reason:
        attrs["reason"] = reason[:500]
    return attrs


def build_console_override_message(
    *,
    game_id: str,
    market_id: str,
    sportsbook: str,
    selection: str,
    source_market_id: str,
    source_selection_id: str,
    selection_line: str = "",
    points: float = 0.0,
    selection_points: float = 0.0,
    grouping_key: str = "default",
    active: bool = True,
    mapping_source: str = "",
) -> dict:
    """Build a mapping_override Pub/Sub payload from console form fields."""
    row = {
        "game_id": game_id.strip(),
        "market_id": market_id.strip(),
        "sportsbook": canonical_sportsbook(sportsbook),
        "selection": selection.strip(),
        "selection_line": selection_line or None,
        "points": points,
        "selection_points": selection_points,
        "grouping_key": grouping_key or "default",
        "source_ids": {
            "market_id": source_market_id.strip(),
            "selection_id": source_selection_id.strip(),
        },
    }
    if not row["game_id"] or not row["market_id"] or not row["selection"]:
        raise ValueError("game_id, market_id, and selection are required")
    if not source_market_id.strip():
        raise ValueError("source market_id is required for RFQ key")
    return build_override_message(
        row,
        active=active,
        mapping_source=mapping_source.strip() or None,
    )


def publish_console_override(
    project: str,
    message: dict,
    *,
    operator: str,
    reason: str,
    dry_run: bool = False,
) -> str:
    """Publish one override message; return Pub/Sub message id."""
    if dry_run or os.getenv("MAPPING_CONSOLE_OVERRIDE_DRY_RUN", "").strip() in {"1", "true", "yes"}:
        logger.info("dry-run console override publish project=%s message=%s", project, message)
        return "dry-run"
    publisher = _publisher()
    future = publisher.publish(
        _topic_path(project),
        json.dumps(message).encode("utf-8"),
        **console_override_attributes(operator, reason),
    )
    message_id = future.result(timeout=30)
    logger.info(
        "console override published project=%s message_id=%s active=%s",
        project,
        message_id,
        message.get("active"),
    )
    return message_id
