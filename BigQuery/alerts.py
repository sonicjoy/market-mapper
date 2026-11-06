"""Shared Pub/Sub application-alerts publisher for post-pipeline checks.

Set ALERT_SLACK_CHANNEL to route these alerts to their own Slack channel (e.g.
"#marketmaking-mapping-alerts") instead of the relay default, #marketmaking-alerts-rfqs,
which is shared with every other publisher on the topic. Unset = unchanged. The
relay honours it only once its bot token is configured AND the bot is a member
of that channel, so set it in step with the mm-infrastructure side.

The VM cron wrappers post their failure alerts through this module too
(``python -m BigQuery.alerts --severity critical < text``, via
infra/slack_webhook.sh ``send_cron_alert``) so they land in the same channel.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Literal

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)

COMPONENT = "mmmapper"
Severity = Literal["info", "warning", "critical"]

def bool_env(name: str, *, default: bool) -> bool:
    """Parse a truthy/falsey environment variable."""
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def resolve_project_id() -> str | None:
    """Return GCP project id from PROJECT_ID or GCP_PROJECT."""
    project = os.getenv("PROJECT_ID", "").strip() or os.getenv("GCP_PROJECT", "").strip()
    return project or None


def format_critical_alert(text: str) -> str:
    """Slack-visible urgency when the relay only routes warning/info severities."""
    lead = "[CRITICAL] "
    return text if text.startswith(lead) else f"{lead}{text}"


class AlertPublisher:
    """Best-effort Pub/Sub publisher matching bf-market-listener alert contract."""

    def __init__(
        self,
        *,
        enabled: bool,
        project_id: str | None,
        topic_id: str,
        publish_timeout_sec: float = 5.0,
        component: str = COMPONENT,
        channel: str = "",
    ) -> None:
        """Configure publisher; connects to Pub/Sub only when enabled."""
        self._enabled = enabled and bool(project_id)
        self._project_id = project_id
        self._topic_id = topic_id
        self._publish_timeout_sec = publish_timeout_sec
        self._component = component
        self._channel = channel.strip()
        self._client = None
        self._topic_path: str | None = None

        if self._enabled and project_id is not None:
            self._client = pubsub_v1.PublisherClient()
            self._topic_path = self._client.topic_path(project_id, topic_id)
            logger.info(
                "alert publisher enabled: projects/%s/topics/%s",
                project_id,
                topic_id,
            )
        else:
            logger.info(
                "alert publisher disabled (ALERT_PUBSUB_ENABLED=false or no project id)"
            )

    @staticmethod
    def _timestamp_z() -> str:
        """Return current UTC time as an ISO-8601 string with Z suffix."""
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def routable(self) -> bool:
        """True when publishing is on AND a channel is named.

        The cron wrappers only take this path when both hold: without a
        channel the relay would post to its shared default, which is a worse
        place than the webhook the wrappers fall back to.
        """
        return self._enabled and bool(self._channel)

    def build_payload(self, severity: Severity, text: str) -> dict[str, str]:
        """Build the application-alerts JSON payload."""
        payload = {
            "component": self._component,
            "severity": severity,
            "text": text,
            "timestamp": self._timestamp_z(),
        }
        # Optional: ask the relay for a specific Slack channel. Omitted when
        # unset so the relay keeps using its default webhook channel -- see
        # mm-infrastructure docs/alerting-slack-wiring.md "Per-channel delivery".
        if self._channel:
            payload["channel"] = self._channel
        return payload

    def publish(self, severity: Severity, text: str) -> str | None:
        """Publish an alert. Returns message id on success, None if disabled or failed."""
        if not self._enabled or self._client is None or self._topic_path is None:
            logger.debug("alert not published (disabled): %s %s", severity, text)
            return None

        payload = self.build_payload(severity, text)
        data = json.dumps(payload).encode("utf-8")
        try:
            future = self._client.publish(self._topic_path, data)
            message_id = future.result(timeout=self._publish_timeout_sec)
            logger.info(
                "published alert severity=%s message_id=%s text=%s",
                severity,
                message_id,
                text,
            )
            return str(message_id)
        except Exception:
            logger.exception("failed to publish alert severity=%s", severity)
            return None

    def close(self) -> None:
        """Stop the Pub/Sub publisher client."""
        client = self._client
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.exception("error stopping pubsub publisher client")
            self._client = None


def build_publisher() -> AlertPublisher:
    """Construct an AlertPublisher from environment variables."""
    return _publisher_from_env(default_enabled=False)


def build_gap_propose_publisher() -> AlertPublisher:
    """Gap-propose CronJob publisher; ALERT_PUBSUB_ENABLED defaults on."""
    return _publisher_from_env(default_enabled=True)


def _publisher_from_env(*, default_enabled: bool) -> AlertPublisher:
    enabled = bool_env("ALERT_PUBSUB_ENABLED", default=default_enabled)
    topic = os.getenv("ALERT_PUBSUB_TOPIC", "application-alerts").strip()
    timeout = float(os.getenv("ALERT_PUBLISH_TIMEOUT_SEC", "5").strip() or "5")
    channel = os.getenv("ALERT_SLACK_CHANNEL", "").strip()
    return AlertPublisher(
        enabled=enabled,
        project_id=resolve_project_id(),
        topic_id=topic,
        publish_timeout_sec=timeout,
        channel=channel,
    )


# Exit codes for the cron-wrapper CLI: 0 published, 1 publish failed,
# 2 not routable (disabled or no ALERT_SLACK_CHANNEL) -- the wrapper falls
# back to its incoming webhook on any non-zero.
EXIT_NOT_ROUTABLE = 2


def main(argv: list[str] | None = None) -> int:
    """Publish stdin as one alert; used by infra/slack_webhook.sh."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--severity", choices=["info", "warning", "critical"], required=True)
    args = parser.parse_args(argv)
    text = sys.stdin.read().strip()
    if not text:
        return 1
    publisher = build_publisher()
    try:
        if not publisher.routable:
            return EXIT_NOT_ROUTABLE
        return 0 if publisher.publish(args.severity, text) else 1
    finally:
        publisher.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
