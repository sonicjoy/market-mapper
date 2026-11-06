"""Tests for oom-catalog-changed publish (G4b)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from BigQuery.oom_catalog_bus import (
    build_rank_complete_message,
    oom_catalog_publish_enabled,
    publish_rank_complete,
)


def test_publish_disabled_returns_empty() -> None:
    client = MagicMock()
    with patch.dict("os.environ", {"MAPPING_PIPELINE_OOM_CATALOG_PUBLISH": "0"}, clear=True):
        assert oom_catalog_publish_enabled() is False
        assert publish_rank_complete(client, "marketmaking-test") == ""


def test_build_rank_complete_message() -> None:
    client = MagicMock()
    row = MagicMock()
    row.rank_run_at = None
    with patch("BigQuery.oom_catalog_bus.ro_query", return_value=iter([row])):
        msg = build_rank_complete_message(client, "marketmaking-test")
    assert msg["event_type"] == "rank_complete"
    assert msg["project_id"] == "marketmaking-test"


def test_publish_rank_complete_publishes_json() -> None:
    client = MagicMock()
    row = MagicMock()
    row.rank_run_at = None
    with (
        patch.dict("os.environ", {"MAPPING_PIPELINE_OOM_CATALOG_PUBLISH": "1"}, clear=True),
        patch("BigQuery.oom_catalog_bus.ro_query", return_value=iter([row])),
        patch("BigQuery.oom_catalog_bus.pubsub_v1.PublisherClient") as publisher_cls,
    ):
        publisher = publisher_cls.return_value
        publisher.topic_path.return_value = "projects/p/topics/oom-catalog-changed"
        future = MagicMock()
        future.result.return_value = "mid-1"
        publisher.publish.return_value = future
        mid = publish_rank_complete(client, "marketmaking-test")
    assert mid == "mid-1"
    payload = json.loads(publisher.publish.call_args.args[1].decode())
    assert payload["event_type"] == "rank_complete"
