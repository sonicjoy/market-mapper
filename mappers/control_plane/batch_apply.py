"""Dry-run and apply for compound batch_changes payloads."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.dry_run import apply_alias_payload, thin_dry_run
from mappers.control_plane.dry_run_already import NOOP_BLOCKER, noop_blockers
from mappers.control_plane.dry_run_league import apply_league_payload, thin_dry_run_league
from mappers.control_plane.dry_run_market_rules import (
    apply_market_rules_payload,
    clone_rules_for_league,
    thin_dry_run_market_rules,
)
from mappers.control_plane.gap_fix_ai_suggest import is_ai_suggest_pin
from mappers.control_plane.models import (
    BatchChangesPayload,
    EntityAliasPayload,
    MappingMarketRulesPayload,
)
from mappers.control_plane.store import EntityRow, LeagueRow, MarketRuleRow, ProposalStore


def batch_summary(payload: BatchChangesPayload) -> str:
    """One-line review summary for a compound batch."""
    n_rules = sum(len(group.rules) for group in payload.market_rules)
    n_ai = sum(1 for ea in payload.entity_aliases if is_ai_suggest_pin(ea))
    n_ai += sum(1 for mr in payload.market_rules if is_ai_suggest_pin(mr))
    aliases = f"{len(payload.entity_aliases)} aliases"
    if n_ai:
        label = "AI suggestion last" if n_ai == 1 else "AI suggestions last"
        aliases = f"{len(payload.entity_aliases)} aliases ({n_ai} {label})"
    return (
        f"Batch: {aliases}, "
        f"{len(payload.leagues)} leagues, {n_rules} market rules"
    )


def _fold_league(
    leagues: list[LeagueRow],
    rules: list[MarketRuleRow],
    payload: Any,
) -> tuple[list[LeagueRow], list[MarketRuleRow]]:
    """Apply one league payload plus optional clone / embedded market rules."""
    leagues = apply_league_payload(leagues, payload)
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
    return leagues, rules


def _hard_blockers(dry: dict[str, Any]) -> list[str]:
    """Blockers that are not the batch-level already-live verdict."""
    return [item for item in dry.get("blockers") or [] if item != NOOP_BLOCKER]


def _absorb_dry(
    dry: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
) -> tuple[bool, int, int]:
    """Merge one sub-dry-run; True when it is safe to apply (noop allowed)."""
    hard = _hard_blockers(dry)
    blockers.extend(hard)
    warnings.extend(dry.get("warnings") or [])
    return (
        not hard,
        int(dry.get("change_count") or 0),
        int(dry.get("item_count") or 0),
    )


def _alias_fold_ok(dry: dict[str, Any]) -> bool:
    """True when alias resolve passed or the only failure is already-live."""
    if dry.get("ok"):
        return True
    return not _hard_blockers(dry) and NOOP_BLOCKER in (dry.get("blockers") or [])


def _is_remove_payload(payload: EntityAliasPayload) -> bool:
    """True when every alias on this canonical is a delete."""
    return bool(payload.aliases) and all(pin.remove for pin in payload.aliases)


def _removes_first(aliases: list[EntityAliasPayload]) -> list[EntityAliasPayload]:
    """Deletes before adds, so a move is not an ambiguous second owner."""
    removes = [payload for payload in aliases if _is_remove_payload(payload)]
    rest = [payload for payload in aliases if payload not in removes]
    return [*removes, *rest]


def dry_run_batch(
    store: ProposalStore,
    current: str,
    payload: BatchChangesPayload,
) -> dict[str, Any]:
    """Rolling dry-run of each sub-payload; block when the whole cart is already live."""
    entities = list(store.entities_for(current))
    leagues = list(store.leagues_for(current))
    rules = list(store.market_rules_for(current))
    blockers: list[str] = []
    warnings: list[str] = []
    change_count = 0
    item_count = 0
    for lg in payload.leagues:
        ok, delta, items = _absorb_dry(thin_dry_run_league(leagues, lg), blockers, warnings)
        change_count += delta
        item_count += items
        if ok:
            leagues, rules = _fold_league(leagues, rules, lg)
    for mr in payload.market_rules:
        ok, delta, items = _absorb_dry(thin_dry_run_market_rules(leagues, rules, mr), blockers, warnings)
        change_count += delta
        item_count += items
        if ok:
            rules = apply_market_rules_payload(rules, mr)
    for ea in _removes_first(payload.entity_aliases):
        dry = thin_dry_run(entities, ea)
        ok, delta, items = _absorb_dry(dry, blockers, warnings)
        change_count += delta
        item_count += items
        if ok and _alias_fold_ok(dry):
            entities = apply_alias_payload(entities, ea)
        elif not _alias_fold_ok(dry):
            blockers.append(
                f"entity_alias dry-run failed for {ea.canonical_key} "
                f"({ea.league}): {dry.get('alias_checks')}"
            )
    blockers.extend(noop_blockers(change_count=change_count, item_count=item_count))
    return {
        "blockers": blockers,
        "warnings": warnings,
        "ok": not blockers,
        "summary": batch_summary(payload),
        "change_count": change_count,
        "item_count": item_count,
    }


def apply_batch(
    store: ProposalStore,
    current: str,
    payload: BatchChangesPayload,
) -> tuple[list[EntityRow], list[LeagueRow], list[MarketRuleRow]]:
    """Apply leagues → market_rules → entity_aliases; return full triple."""
    entities = list(store.entities_for(current))
    leagues = list(store.leagues_for(current))
    rules = list(store.market_rules_for(current))
    for lg in payload.leagues:
        leagues, rules = _fold_league(leagues, rules, lg)
    for mr in payload.market_rules:
        rules = apply_market_rules_payload(rules, mr)
    for ea in _removes_first(payload.entity_aliases):
        entities = apply_alias_payload(entities, ea)
    return entities, leagues, rules
