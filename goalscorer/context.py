"""Wires settings, BigQuery, Pub/Sub and Slack together for one process."""

from __future__ import annotations

from dataclasses import dataclass

from google.cloud import bigquery

from goalscorer.config import Settings
from goalscorer.leagues import LeagueRegistry
from goalscorer.overrides import OverridePublisher
from goalscorer.slack import SlackNotifier
from goalscorer.store import GoalscorerStore


@dataclass
class Context:
    """Everything a command needs; tests build one from fakes."""

    settings: Settings
    store: GoalscorerStore
    leagues: LeagueRegistry
    publisher: OverridePublisher
    slack: SlackNotifier

    @classmethod
    def from_env(cls) -> Context:
        """Production context from environment settings."""
        settings = Settings.from_env()
        client = bigquery.Client(project=settings.project)
        return cls(
            settings=settings,
            store=GoalscorerStore(client, settings.project),
            leagues=LeagueRegistry(client, settings.project, dry_run=settings.dry_run),
            publisher=OverridePublisher(settings.project, dry_run=settings.dry_run),
            slack=SlackNotifier(settings),
        )
