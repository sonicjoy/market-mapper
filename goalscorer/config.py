"""Goalscorer mapper constants, built-in leagues, and env settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

MARKET_ID = "anytime_goal_scorer"
MARKET_NAME = "Anytime Goal Scorer"
# Kalshi's 2+ / 3+ goal markets map onto Optic player_goals over 1.5 / 2.5:
# goal line on the ticker (…-ARSBSAKA7-2) → Optic points.
PLAYER_GOALS_MARKET_ID = "player_goals"
PLAYER_GOALS_MARKET_NAME = "Player Goals"
MULTI_GOAL_LINES = {"2": 1.5, "3": 2.5}
# Kalshi's first goalscorer markets (KXUCLFIRSTGOAL-…-BARLYAMAL10: the player's
# code without a line) map onto Optic first_goal_scorer, shaped like anytime.
FIRST_GOAL_MARKET_ID = "first_goal_scorer"
FIRST_GOAL_MARKET_NAME = "First Goal Scorer"
# Optic market name per anytime-shaped market (selection only, points 0, grouping_key default).
MARKET_NAMES = {MARKET_ID: MARKET_NAME, FIRST_GOAL_MARKET_ID: FIRST_GOAL_MARKET_NAME}
SPORTSBOOK = "Kalshi"
# Provenance on opticodds_mapping rows this job creates. Existing history rows
# carry HENRY and the player-code lookup reads them, so keep the value stable.
MAPPING_SOURCE = "HENRY"
# Pub/Sub `source` attribute on mapping_override messages. Pre-game only ever
# replaces its own (OVERRIDE_SOURCE) guesses; listing-check corrections and
# review-card decisions carry their own source so pre-game leaves them alone.
OVERRIDE_SOURCE = "goalscorer-mapper"
LISTING_SOURCE = "goalscorer-listing"
REVIEW_SOURCE = "goalscorer-review"
OVERRIDE_TOPIC = "mapping-override-us"
LEAGUES_TABLE = "markets_us.goalscorer_leagues"
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class League:
    """One Optic league this job maps, and its Kalshi goalscorer series."""

    league_id: str
    goal_prefix: str
    display_name: str
    sport: str = "soccer"


# Always mapped unless deactivated in LEAGUES_TABLE. Leagues added from Slack
# live in that table only.
DEFAULT_LEAGUES = (
    League("spain_-_la_liga", "KXLALIGAGOAL", "Spain - La Liga"),
    League("england_-_premier_league", "KXEPLGOAL", "England - Premier League"),
    League("uefa_-_champions_league", "KXUCLGOAL", "UEFA - Champions League"),
)


def _bool_env(name: str, default: bool) -> bool:
    """Truthy env flag with a default."""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    """Integer env value with a default."""
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _csv_env(name: str) -> frozenset[str]:
    """Comma-separated env value as a set."""
    return frozenset(p.strip() for p in os.getenv(name, "").split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read once from the environment."""

    project: str
    slack_channel_id: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    # Slack user ids allowed to resolve review cards and run channel commands.
    # Empty = anyone in the channel.
    approver_ids: frozenset[str] = frozenset()
    lookback_days: int = 60
    days_ahead: int = 1
    dry_run: bool = False
    enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from GCP_PROJECT, SLACK_* and GOALSCORER_* variables."""
        project = os.getenv("GCP_PROJECT", "").strip() or os.getenv("PROJECT_ID", "").strip()
        if not project:
            raise RuntimeError("GCP_PROJECT must be set")
        return cls(
            project=project,
            slack_channel_id=os.getenv("GOALSCORER_SLACK_CHANNEL_ID", "").strip(),
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", "").strip(),
            slack_app_token=os.getenv("SLACK_APP_TOKEN", "").strip(),
            approver_ids=_csv_env("GOALSCORER_SLACK_APPROVER_IDS"),
            lookback_days=_int_env("GOALSCORER_LOOKBACK_DAYS", 60),
            days_ahead=_int_env("GOALSCORER_PREGAME_DAYS_AHEAD", 1),
            dry_run=_bool_env("GOALSCORER_DRY_RUN", False),
            enabled=_bool_env("GOALSCORER_MAPPER_ENABLED", True),
        )

    @property
    def slack_enabled(self) -> bool:
        """True when both a bot token and a channel are configured."""
        return bool(self.slack_bot_token and self.slack_channel_id)
