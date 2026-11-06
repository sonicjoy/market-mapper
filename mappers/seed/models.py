"""IR dataclasses for mapping-rule seed snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketRuleIR:
    rule_id: str
    rule_group_id: str | None
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
    market_family: str | None = None
    notes: str | None = None
    settlement_note: str | None = None
    line_offset: float | None = None
    yes_side: str | None = None
    side_swap: bool | None = None
    official_description: str | None = None
    citation_url: str | None = None


@dataclass
class AliasIR:
    alias_id: str
    sportsbook: str
    alias_kind: str
    alias_value: str
    enabled: bool = True
    confidence: str = "id_verified"
    normalization_profile: str | None = None


@dataclass
class EntityIR:
    league: str
    entity_type: str
    canonical_key: str
    canonical_name: str | None
    enabled: bool
    aliases: list[AliasIR] = field(default_factory=list)


@dataclass
class ExchangeIR:
    sportsbook: str
    enabled: bool
    parser_profile: str
    settings_schema_version: int
    source_league_id: str | None
    settings: dict[str, Any]
    market_rule_group_ids: list[str] = field(default_factory=list)


@dataclass
class LeagueIR:
    """One mapping_leagues row in a seed snapshot."""

    league: str
    sport: str
    optic_league_id: str
    extra_optic_league_ids: list[str]
    fixture_source: str
    fixture_horizon_hours: float
    enabled: bool
    output_order: list[str]
    exchanges: list[ExchangeIR]
    notes: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class SnapshotIR:
    rule_set_id: str
    snapshot_sha256: str
    engine_contract_version: str
    created_via: str
    created_at: str
    created_by: str
    canonical_markets: list[dict[str, Any]]
    leagues: list[LeagueIR]
    market_rules: list[MarketRuleIR]
    entities: list[EntityIR]
    missing_profiles: list[str] = field(default_factory=list)
