"""Shared rule-row dataclasses for control-plane stores and COW helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityRow:
    """One entity + aliases under a rule_set_id (or COW delta)."""

    league: str
    entity_type: str
    canonical_key: str
    canonical_name: str | None
    aliases: list[dict[str, Any]]
    enabled: bool = True
    notes: str | None = None
    tombstone: bool = False


@dataclass
class LeagueRow:
    """One mapping_leagues row under a rule_set_id (or COW delta)."""

    league: str
    sport: str
    optic_league_id: str
    extra_optic_league_ids: list[str]
    fixture_source: str
    fixture_horizon_hours: float
    enabled: bool
    output_order: list[str]
    exchanges: list[dict[str, Any]]
    notes: str | None = None
    tombstone: bool = False
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketRuleRow:
    """One mapping_market_rules row under a rule_set_id (or COW delta)."""

    rule_id: str
    league: str | None
    sportsbook: str
    rule_kind: str
    source_key_type: str
    source_key: str
    action: str
    canonical_market_type: str | None
    priority: int
    enabled: bool
    confidence: str
    match_operator: str = "exact"
    notes: str | None = None
    tombstone: bool = False
    line_offset: float | None = None
    yes_side: str | None = None
    side_swap: bool | None = None
    official_description: str | None = None
    citation_url: str | None = None
    rule_group_id: str | None = None
    market_family: str | None = None
    settlement_note: str | None = None
