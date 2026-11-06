"""Pydantic payloads and errors for control-plane proposals."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class ActorRole(StrEnum):
    """Control-plane roles from the M3a auth model."""

    VIEWER = "viewer"
    PROPOSER = "proposer"
    APPROVER = "approver"
    ADMIN = "admin"
    SERVICE = "service"


class Actor(BaseModel):
    """Authenticated caller (never trust body actor fields)."""

    subject: str
    role: ActorRole


class AliasPin(BaseModel):
    """One sportsbook alias to attach to a canonical entity."""

    sportsbook: str
    alias_kind: str
    alias_value: str
    disambiguation_id: str | None = None
    disambiguation_name: str | None = None
    # When True, drop this triple from the target entity (do not merge).
    remove: bool = False


class EntityAliasPayload(BaseModel):
    """Pin sportsbook aliases onto a canonical entity."""

    kind: Literal["entity_alias"] = "entity_alias"
    league: str
    canonical_key: str
    entity_type: Literal["team", "player", "fighter"] = "team"
    canonical_name: str | None = None
    aliases: list[AliasPin]
    # When True, strip this alias triple from other entities in the league (Rules re-pin).
    reassign: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class ExchangePin(BaseModel):
    """One enabled exchange on a league row."""

    sportsbook: str
    enabled: bool = True
    parser_profile: str
    source_league_id: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class MarketRulePin(BaseModel):
    """One taxonomy / ignore / map rule."""

    sportsbook: str
    rule_kind: str
    source_key_type: str
    source_key: str
    action: str
    canonical_market_type: str | None = None
    league: str | None = None
    priority: int = 100
    enabled: bool = True
    confidence: str = "manual"
    match_operator: str = "exact"
    notes: str | None = None
    line_offset: float | None = None
    yes_side: str | None = None
    side_swap: bool | None = None
    official_description: str | None = None
    citation_url: str | None = None


class MappingLeaguePayload(BaseModel):
    """Onboard a league row (+ optional market_rules clone/pins)."""

    kind: Literal["mapping_league"] = "mapping_league"
    league: str
    sport: str
    optic_league_id: str
    extra_optic_league_ids: list[str] | None = None
    fixture_source: str = "api"
    fixture_horizon_hours: float | None = None
    enabled: bool | None = None
    output_order: list[str] | None = None
    entity_type: Literal["team", "player", "fighter"] = "team"
    alias_enforcement: Literal["raise", "warn"] = "raise"
    runshop_enabled: bool = False
    exchanges: list[ExchangePin]
    notes: str | None = None
    clone_market_rules_from: str | None = None
    market_rules: list[MarketRulePin] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    def league_settings(self) -> dict[str, Any]:
        """League-level settings persisted on the tip row."""
        return {
            "entity_type": self.entity_type,
            "alias_enforcement": self.alias_enforcement,
            "runshop_enabled": self.runshop_enabled,
        }


class MappingMarketRulesPayload(BaseModel):
    """Add market_rules pins for an existing league."""

    kind: Literal["mapping_market_rules"] = "mapping_market_rules"
    league: str
    rules: list[MarketRulePin]
    evidence_refs: list[str] = Field(default_factory=list)
    # Already-mapped keys shown on the card. Approve reads ``rules`` only.
    context_rules: list[MarketRulePin] = Field(default_factory=list)


class BatchChangesPayload(BaseModel):
    """Compound proposal: many aliases / leagues / market-rule groups in one snapshot."""

    kind: Literal["batch_changes"] = "batch_changes"
    entity_aliases: list[EntityAliasPayload] = Field(default_factory=list)
    leagues: list[MappingLeaguePayload] = Field(default_factory=list)
    market_rules: list[MappingMarketRulesPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_empty(self) -> BatchChangesPayload:
        """Require at least one staged change."""
        if not (self.entity_aliases or self.leagues or self.market_rules):
            raise ValueError("batch_changes must include at least one item")
        return self


class CombatEntityRetagPayload(BaseModel):
    """One-shot team -> fighter retag for combat leagues (+ league settings)."""

    kind: Literal["combat_entity_retag"] = "combat_entity_retag"
    leagues: list[str] = Field(default_factory=lambda: ["boxing_matches", "ufc"])
    evidence_refs: list[str] = Field(default_factory=list)


ArtifactPayload = Annotated[
    EntityAliasPayload
    | MappingLeaguePayload
    | MappingMarketRulesPayload
    | BatchChangesPayload
    | CombatEntityRetagPayload,
    Field(discriminator="kind"),
]


class ProposeRequest(BaseModel):
    """POST /proposals body."""

    request_id: str
    expected_rule_set_id: str
    artifact_type: Literal[
        "entity_alias",
        "mapping_league",
        "mapping_market_rules",
        "batch_changes",
        "combat_entity_retag",
    ] = "entity_alias"
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    work_item_id: str | None = None
    payload: ArtifactPayload

    @model_validator(mode="before")
    @classmethod
    def _inject_payload_kind(cls, data: Any) -> Any:
        """Allow clients to omit payload.kind; copy from artifact_type."""
        if not isinstance(data, dict):
            return data
        payload = data.get("payload")
        artifact = data.get("artifact_type", "entity_alias")
        if isinstance(payload, dict) and "kind" not in payload:
            data = {**data, "payload": {**payload, "kind": artifact}}
        return data


class ProposalRecord(BaseModel):
    """Stored proposal lifecycle record."""

    proposal_id: str
    request_id: str
    status: str
    expected_rule_set_id: str
    artifact_type: str
    summary: str
    evidence_refs: list[str]
    work_item_id: str | None
    payload: ArtifactPayload
    proposer_subject: str
    candidate_rule_set_id: str | None = None
    validated_at: str | None = None
    approved_at: str | None = None
    activated_rule_set_id: str | None = None
    change_summary: dict[str, int] | None = None
    change_groups: dict[str, Any] | None = None
    review_note: str | None = None
    proposed_at: str | None = None
    last_occurred_at: str | None = None
    reviewer_subject: str | None = None


class ValidateResponse(BaseModel):
    """POST /proposals/{id}/validate response."""

    status: str
    candidate_rule_set_id: str | None = None
    snapshot_sha256: str | None = None
    integrity: dict[str, Any] = Field(default_factory=dict)
    dry_run: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None


class ApproveResponse(BaseModel):
    """POST /proposals/{id}/approve response."""

    status: str
    proposal_id: str
    activated_rule_set_id: str | None = None
    reason_code: str | None = None


class EntryVerifyRequest(BaseModel):
    """POST /entry/verify — trader paste only (no internal ids)."""

    paste: str
    provided_name: str | None = None
    note: str | None = None
    acknowledge_live_warning: bool = False
    disambiguation_label: str | None = None
    league: str | None = None


class EntrySubmitRequest(BaseModel):
    """POST /entry/submit — confirm a verified preview token."""

    preview_token: str


class StructuredAliasEntryRequest(BaseModel):
    """POST /entry/alias/verify — pin from Rules without a paste ticker."""

    league: str
    sportsbook: str
    alias_value: str
    provided_name: str
    entity_type: Literal["team", "player", "fighter"] = "team"
    alias_kind: str = "code"
    canonical_key: str | None = None
    note: str | None = None
    acknowledge_shadow: bool = False
    # When True, drop this alias triple from the target entity (Rules remove).
    remove: bool = False


class LeagueEntryRequest(BaseModel):
    """Trader league onboard form fields."""

    league: str
    sport: str
    optic_league_id: str
    fixture_source: str = "api"
    fixture_horizon_hours: float | None = None
    entity_type: Literal["team", "player", "fighter"] = "team"
    alias_enforcement: Literal["raise", "warn"] = "raise"
    runshop_enabled: bool = False
    exchanges: list[ExchangePin]
    clone_market_rules_from: str | None = None
    note: str | None = None
    acknowledge_shadow: bool = False


def _blank_float(value: Any) -> float | None:
    """None for a blank form cell; otherwise a float."""
    if value is None or value == "":
        return None
    return float(value)


def _blank_text(value: Any) -> str | None:
    """None for a blank form cell."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _blank_bool(value: Any) -> bool | None:
    """None, true, or false. Blank stays null so it is not a flip."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        return None
    return bool(value)


def _rule_pin_extras(data: dict[str, Any]) -> dict[str, Any]:
    """Line, side, and match operator from a flat Editor body."""
    extra: dict[str, Any] = {}
    operator = data.get("match_operator")
    if operator:
        extra["match_operator"] = operator
    if "notes" in data:
        extra["notes"] = data.get("notes")
    if "line_offset" in data:
        extra["line_offset"] = _blank_float(data.get("line_offset"))
    if "yes_side" in data:
        extra["yes_side"] = _blank_text(data.get("yes_side"))
    if "side_swap" in data:
        extra["side_swap"] = _blank_bool(data.get("side_swap"))
    if "official_description" in data:
        extra["official_description"] = _blank_text(data.get("official_description"))
    if "citation_url" in data:
        extra["citation_url"] = _blank_text(data.get("citation_url"))
    return extra


class MarketRuleEntryRequest(BaseModel):
    """Trader market-rule form fields (flat form or rules[])."""

    league: str
    rules: list[MarketRulePin] = Field(default_factory=list)
    # Flat trader-form fields (wrapped into rules[] when rules omitted).
    sportsbook: str | None = None
    source_key_type: str | None = None
    source_key: str | None = None
    action: str | None = None
    canonical_market_type: str | None = None
    rule_kind: str = "taxonomy"
    pending_league_slugs: list[str] = Field(default_factory=list)
    note: str | None = None
    acknowledge_shadow: bool = False

    @model_validator(mode="before")
    @classmethod
    def _flat_to_rules(cls, data: Any) -> Any:
        """Accept Mapper flat body and wrap a single MarketRulePin."""
        if not isinstance(data, dict):
            return data
        if data.get("rules"):
            return data
        sportsbook = data.get("sportsbook")
        source_key = data.get("source_key")
        if not sportsbook or not source_key:
            return data
        pin = {
            "sportsbook": sportsbook,
            "rule_kind": data.get("rule_kind") or "taxonomy",
            "source_key_type": data.get("source_key_type") or "",
            "source_key": source_key,
            "action": data.get("action") or "map",
            "canonical_market_type": data.get("canonical_market_type"),
            "league": data.get("league"),
            **_rule_pin_extras(data),
        }
        return {**data, "rules": [pin]}

    @model_validator(mode="after")
    def _require_rules(self) -> MarketRuleEntryRequest:
        """Fail closed when neither flat fields nor rules[] produced a pin."""
        if not self.rules:
            raise ValueError("at least one market rule is required")
        return self


class MarketRuleSuggestRequest(BaseModel):
    """POST /entry/market-rule/suggest — spine-based suggestions."""

    league: str
    optic_league_id: str = ""
    sport: str = ""
    sportsbooks: list[str] = Field(default_factory=list)
    template_league: str | None = None


class AliasSuggestRequest(BaseModel):
    """POST /entry/alias/suggest — Optic competitor suggestions."""

    league: str
    sport: str = ""
    optic_league_id: str
    fixture_horizon_hours: float = 96.0


class LeagueHarvestRequest(BaseModel):
    """POST /entry/league/harvest-id — live source_league_id for one book."""

    league: str
    sport: str = ""
    optic_league_id: str
    sportsbook: str
    fixture_horizon_hours: float | None = None


class BatchEntryRequest(BaseModel):
    """POST /entry/batch/verify — staged cart payloads."""

    entity_aliases: list[EntityAliasPayload] = Field(default_factory=list)
    leagues: list[MappingLeaguePayload] = Field(default_factory=list)
    market_rules: list[MappingMarketRulesPayload] = Field(default_factory=list)
    note: str | None = None
    acknowledge_shadow: bool = False


class ReviewActionRequest(BaseModel):
    """Reject / request-changes body (comment only)."""

    comment: str = Field(default="")


class ChatRequest(BaseModel):
    """POST /chat — Mapper Chat turn (V0 stub; V1+ agent)."""

    message: str
    conversation_id: str | None = None
    page_context: dict[str, Any] | None = None


class ChatReplyButton(BaseModel):
    """Clickable chip that re-sends a fixed user message."""

    id: str
    label: str
    send: str


class ChatResponse(BaseModel):
    """Assistant turn returned to the console dock."""

    reply_markdown: str
    agent_available: bool = True
    conversation_id: str | None = None
    reply_buttons: list[ChatReplyButton] = Field(default_factory=list)
    ui_actions: list[dict[str, Any]] = Field(default_factory=list)


class ConflictError(Exception):
    """HTTP 409 — stale expected_rule_set_id or missing current."""

    def __init__(self, message: str, *, reason_code: str = "stale_rule_set") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ForbiddenError(Exception):
    """HTTP 403 — role or maker/checker violation."""

    def __init__(self, message: str, *, reason_code: str = "forbidden") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ValidationFailedError(Exception):
    """HTTP 422 — dry-run or precondition failure."""

    def __init__(self, message: str, *, reason_code: str, dry_run: dict[str, Any]) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.dry_run = dry_run


class BigQueryUnavailableError(Exception):
    """HTTP 503 — BigQuery IAM / quota project denied."""

    def __init__(self, message: str, *, reason_code: str = "bq_forbidden") -> None:
        super().__init__(message)
        self.reason_code = reason_code
