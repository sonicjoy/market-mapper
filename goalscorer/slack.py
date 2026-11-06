"""Slack Web API wrapper for #goalscorer-alerts (disabled = log only)."""

from __future__ import annotations

import logging
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from goalscorer.config import Settings

logger = logging.getLogger(__name__)


def web_client(token: str) -> WebClient:
    """WebClient that waits out 429s instead of failing."""
    client = WebClient(token=token, timeout=30)
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    return client


class SlackNotifier:
    """Posts to the configured channel; every call is a no-op log when Slack is off."""

    def __init__(self, settings: Settings, client: WebClient | None = None) -> None:
        self.channel = settings.slack_channel_id
        self.enabled = settings.slack_enabled and not settings.dry_run
        self.client = client or (web_client(settings.slack_bot_token) if self.enabled else None)

    def post(self, text: str, blocks: list[dict] | None = None, thread_ts: str | None = None) -> str | None:
        """Post a message; returns its ts, or None when disabled or Slack refused it."""
        if not self.enabled or self.client is None:
            logger.info("slack (disabled): %s", text)
            return None
        try:
            resp = self.client.chat_postMessage(channel=self.channel, text=text, blocks=blocks, thread_ts=thread_ts)
        except SlackApiError as exc:
            logger.error("slack post failed: %s", exc.response.get("error"))
            return None
        return resp.get("ts")

    def upload(self, path: Path, title: str, comment: str) -> bool:
        """Upload a file to the channel with an initial comment."""
        if not self.enabled or self.client is None:
            logger.info("slack (disabled): would upload %s — %s", path, comment)
            return False
        try:
            self.client.files_upload_v2(
                channel=self.channel, file=str(path), filename=path.name, title=title, initial_comment=comment
            )
        except SlackApiError as exc:
            logger.error("slack upload failed: %s", exc.response.get("error"))
            return False
        return True
