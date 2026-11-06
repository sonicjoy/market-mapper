"""Publish goalscorer mappings to mapping-override-us.

The Pub/Sub → BQ subscription lands each message in opticodds_us.mapping_override;
prices_state_merge_us (every 15 min) then creates or updates the
opticodds_mapping / prices_dedup_state row and stamps mapping_source from the
message, so no follow-up UPDATE is needed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from goalscorer import codes
from goalscorer.config import (
    MAPPING_SOURCE,
    MARKET_ID,
    OVERRIDE_SOURCE,
    OVERRIDE_TOPIC,
    PLAYER_GOALS_MARKET_ID,
    SPORTSBOOK,
)

logger = logging.getLogger(__name__)

_PUBLISH_TIMEOUT_SEC = 60


def override_message(
    game_id: str, selection: str, ticker: str, *, active: bool = True, market_id: str = MARKET_ID
) -> dict:
    """mapping_override.proto payload enabling (or turning off) one goalscorer ticker (yes side).

    `market_id` is anytime_goal_scorer or first_goal_scorer; both share this shape.
    """
    return {
        "game_id": game_id,
        "market_id": market_id,
        "sportsbook": SPORTSBOOK,
        "selection": selection,
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
        "source_ids": json.dumps({"market_id": ticker, "selection_id": "yes"}),
        "active": active,
        "mapping_source": MAPPING_SOURCE,
    }


def player_goals_message(game_id: str, selection: str, ticker: str, points: float, *, active: bool = True) -> dict:
    """Payload mapping one 2+ / 3+ ticker (yes side) onto player_goals over `points`.

    Same shape as Optic's own player_goals rows (Kalshi NHL included): line "over",
    points and selection_points both the line (1.5 / 2.5), and Optic's per-player
    grouping key. The Kalshi mapper writes selection_points 0 on these rows; Optic doesn't.
    """
    return {
        "game_id": game_id,
        "market_id": PLAYER_GOALS_MARKET_ID,
        "sportsbook": SPORTSBOOK,
        "selection": selection,
        "selection_line": "over",
        "points": points,
        "selection_points": points,
        "grouping_key": codes.player_goals_key(selection, points),
        "source_ids": json.dumps({"market_id": ticker, "selection_id": "yes"}),
        "active": active,
        "mapping_source": MAPPING_SOURCE,
    }


class OverridePublisher:
    """Batch publisher for override messages; dry-run logs instead of publishing."""

    def __init__(self, project: str, *, dry_run: bool = False) -> None:
        self.project = project
        self.dry_run = dry_run
        self._client = None

    def publish(self, messages: Sequence[dict], source: str = OVERRIDE_SOURCE) -> int:
        """Publish all messages with this `source` attribute and wait for every ack. Returns the number published."""
        if not messages:
            return 0
        if self.dry_run:
            for msg in messages:
                logger.info("dry-run override %s", msg)
            return 0
        if self._client is None:
            from google.cloud import pubsub_v1

            self._client = pubsub_v1.PublisherClient()
        topic = self._client.topic_path(self.project, OVERRIDE_TOPIC)
        futures = [self._client.publish(topic, json.dumps(m).encode("utf-8"), source=source) for m in messages]
        for future in futures:
            future.result(timeout=_PUBLISH_TIMEOUT_SEC)
        logger.info("published %d goalscorer overrides to %s", len(futures), topic)
        return len(futures)
