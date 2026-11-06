"""Apply validated proposal payloads into candidate snapshot slices."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.batch_apply import apply_batch, dry_run_batch
from mappers.control_plane.combat_entity_retag import (
    apply_combat_entity_retag,
    dry_run_combat_retag,
    resolve_retag_targets,
)
from mappers.control_plane.dry_run import apply_alias_payload, thin_dry_run
from mappers.control_plane.dry_run_league import apply_league_payload, thin_dry_run_league
from mappers.control_plane.dry_run_market_rules import (
    apply_market_rules_payload,
    clone_rules_for_league,
    thin_dry_run_market_rules,
)
from mappers.control_plane.models import (
    BatchChangesPayload,
    CombatEntityRetagPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    ProposalRecord,
    ValidationFailedError,
)
from mappers.control_plane.store import EntityRow, LeagueRow, MarketRuleRow, ProposalStore


def payload_league(payload: Any) -> str:
    """League key from any artifact payload."""
    if isinstance(payload, CombatEntityRetagPayload):
        return payload.leagues[0] if payload.leagues else "combat"
    if isinstance(payload, BatchChangesPayload):
        for item in (*payload.leagues, *payload.market_rules, *payload.entity_aliases):
            return str(item.league)
        return "batch"
    return str(payload.league)


def payload_sportsbook(payload: Any) -> str | None:
    """Best-effort sportsbook for audit rows."""
    if isinstance(payload, EntityAliasPayload) and payload.aliases:
        return payload.aliases[0].sportsbook
    if isinstance(payload, MappingLeaguePayload) and payload.exchanges:
        return payload.exchanges[0].sportsbook
    if isinstance(payload, MappingMarketRulesPayload) and payload.rules:
        return payload.rules[0].sportsbook
    if isinstance(payload, BatchChangesPayload):
        for ea in payload.entity_aliases:
            if ea.aliases:
                return ea.aliases[0].sportsbook
        for lg in payload.leagues:
            if lg.exchanges:
                return lg.exchanges[0].sportsbook
        for mr in payload.market_rules:
            if mr.rules:
                return mr.rules[0].sportsbook
    return None


def dry_run_proposal(
    store: ProposalStore,
    current: str,
    proposal: ProposalRecord,
) -> dict[str, Any]:
    """Run the artifact-specific thin dry-run."""
    payload = proposal.payload
    if isinstance(payload, EntityAliasPayload):
        return thin_dry_run(store.entities_for(current), payload)
    if isinstance(payload, MappingLeaguePayload):
        return thin_dry_run_league(store.leagues_for(current), payload)
    if isinstance(payload, MappingMarketRulesPayload):
        return thin_dry_run_market_rules(
            store.leagues_for(current),
            store.market_rules_for(current),
            payload,
        )
    if isinstance(payload, BatchChangesPayload):
        return dry_run_batch(store, current, payload)
    if isinstance(payload, CombatEntityRetagPayload):
        return _dry_run_combat_retag(store, current, payload)
    raise ValidationFailedError(
        "unsupported artifact",
        reason_code="unsupported_artifact",
        dry_run={},
    )


def _league_candidate(
    store: ProposalStore,
    current: str,
    payload: MappingLeaguePayload,
) -> tuple[None, list[LeagueRow], list[MarketRuleRow]]:
    """Candidate slices for a single mapping_league proposal."""
    leagues = apply_league_payload(store.leagues_for(current), payload)
    rules = store.market_rules_for(current)
    if payload.clone_market_rules_from:
        rules = rules + clone_rules_for_league(
            rules,
            from_league=payload.clone_market_rules_from,
            to_league=payload.league,
        )
    if payload.market_rules:
        rules = apply_market_rules_payload(
            rules,
            MappingMarketRulesPayload(league=payload.league, rules=payload.market_rules),
        )
    return None, leagues, rules


def build_candidate_slices(
    store: ProposalStore,
    current: str,
    proposal: ProposalRecord,
) -> tuple[list[EntityRow] | None, list[LeagueRow] | None, list[MarketRuleRow] | None]:
    """Return (entities, leagues, market_rules) overrides for insert_candidate."""
    payload = proposal.payload
    if isinstance(payload, EntityAliasPayload):
        return apply_alias_payload(store.entities_for(current), payload), None, None
    if isinstance(payload, MappingLeaguePayload):
        return _league_candidate(store, current, payload)
    if isinstance(payload, MappingMarketRulesPayload):
        return None, None, apply_market_rules_payload(store.market_rules_for(current), payload)
    if isinstance(payload, BatchChangesPayload):
        entities, leagues, rules = apply_batch(store, current, payload)
        return entities, leagues, rules
    if isinstance(payload, CombatEntityRetagPayload):
        return _candidate_combat_retag(store, current, payload)
    raise ValidationFailedError(
        "unsupported artifact",
        reason_code="unsupported_artifact",
        dry_run={},
    )


def _target_leagues(payload: CombatEntityRetagPayload) -> list[str]:
    return [slug.strip() for slug in payload.leagues if slug.strip()]


def _dry_run_combat_retag(
    store: ProposalStore,
    current: str,
    payload: CombatEntityRetagPayload,
) -> dict[str, Any]:
    return dry_run_combat_retag(
        store.entities_for(current),
        store.leagues_for(current),
        requested=_target_leagues(payload),
    )


def _candidate_combat_retag(
    store: ProposalStore,
    current: str,
    payload: CombatEntityRetagPayload,
) -> tuple[list[EntityRow], list[LeagueRow], None]:
    entities = store.entities_for(current)
    leagues = store.leagues_for(current)
    requested = _target_leagues(payload)
    dry = dry_run_combat_retag(entities, leagues, requested=requested)
    if not dry["ok"]:
        raise ValidationFailedError(
            "thin dry-run failed", reason_code="dry_run_failed", dry_run=dry,
        )
    want, _blockers = resolve_retag_targets(leagues, requested)
    child_ent, child_lg = apply_combat_entity_retag(
        entities, leagues, target_leagues=want,
    )
    return child_ent, child_lg, None
