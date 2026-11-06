"""Publish rank_complete to oom-catalog-changed (Release 068 G4b)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from google.cloud import bigquery, pubsub_v1

from BigQuery.alerts import bool_env
from BigQuery.client import ro_query

logger = logging.getLogger(__name__)

DEFAULT_TOPIC = "oom-catalog-changed"
RANK_VERSION = 1


def oom_catalog_publish_enabled() -> bool:
    """Default on; cache service needs rank_complete after fold+rank COMMIT."""
    return bool_env("MAPPING_PIPELINE_OOM_CATALOG_PUBLISH", default=True)


def _topic_path(project: str) -> str:
    topic = os.getenv("OOM_CATALOG_CHANGED_TOPIC", DEFAULT_TOPIC).strip() or DEFAULT_TOPIC
    return pubsub_v1.PublisherClient().topic_path(project, topic)


def _latest_rank_run_at(client: bigquery.Client, project: str) -> str | None:
    row = next(
        iter(
            ro_query(
                client,
                f"""
                select max(rank_run_at) as rank_run_at
                from `{project}.opticodds_us.opticodds_mapping`
                where rank_run_at is not null
                """,  # nosec B608
            )
        )
    )
    value = getattr(row, "rank_run_at", None)
    return value.isoformat() if value is not None else None


def build_rank_complete_message(
    client: bigquery.Client,
    project: str,
    *,
    rank_version: int = RANK_VERSION,
) -> dict[str, Any]:
    """Payload consumed by mapping-cache-service."""
    return {
        "event_type": "rank_complete",
        "project_id": project,
        "rank_version": rank_version,
        "rank_run_at": _latest_rank_run_at(client, project),
    }


def publish_rank_complete(
    client: bigquery.Client,
    project: str,
    *,
    rank_version: int = RANK_VERSION,
) -> str:
    """Publish rank_complete; returns Pub/Sub message id."""
    if not oom_catalog_publish_enabled():
        logger.info("oom catalog publish disabled (MAPPING_PIPELINE_OOM_CATALOG_PUBLISH)")
        return ""
    payload = build_rank_complete_message(client, project, rank_version=rank_version)
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    publisher = pubsub_v1.PublisherClient()
    future = publisher.publish(_topic_path(project), data)
    message_id = future.result(timeout=30)
    logger.info(
        "published rank_complete project=%s rank_run_at=%s message_id=%s",
        project,
        payload.get("rank_run_at"),
        message_id,
    )
    return message_id
