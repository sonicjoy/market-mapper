"""Trim items from a batch proposal then re-validate."""

from __future__ import annotations

from mappers.control_plane.console_mapping_clone import (
    clone_rule_pins,
    parse_clone_key,
    rule_row_key,
)
from mappers.control_plane.models import (
    BatchChangesPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposalRecord,
    ValidationFailedError,
)
from mappers.control_plane.pipeline_gap_merge import superseded_by_ref
from mappers.control_plane.rows import MarketRuleRow


def _parse_alias_key(key: str) -> tuple[str, str, str, str] | None:
    """alias:{league}:{canonical}:{book}:{code}"""
    parts = key.split(":", 4)
    if len(parts) != 5 or parts[0] != "alias":
        return None
    return parts[1], parts[2], parts[3], parts[4]


def _parse_rule_key(key: str) -> tuple[str, str, str, str] | None:
    """rule:{league}:{book}:{source_key_type}:{source_key}"""
    parts = key.split(":", 4)
    if len(parts) != 5 or parts[0] != "rule":
        return None
    return parts[1], parts[2], parts[3], parts[4]


def _parse_league_key(key: str) -> str | None:
    parts = key.split(":", 1)
    if len(parts) != 2 or parts[0] != "league":
        return None
    return parts[1]


def drop_batch_items(
    payload: BatchChangesPayload,
    drops: list[dict[str, str]],
    *,
    tip_league_slugs: set[str],
    tip_market_rules: list[MarketRuleRow] | None = None,
) -> BatchChangesPayload:
    """Return a new payload with dropped rows removed."""
    drop_leagues, drop_aliases, drop_rules, drop_clones = _drop_sets(drops)
    cascade = {lg for lg in drop_leagues if lg not in tip_league_slugs}
    leagues = _trim_leagues(
        payload.leagues, drop_leagues, drop_clones, drop_rules, cascade,
        tip_market_rules or [],
    )
    entity_aliases = _trim_aliases(payload.entity_aliases, drop_aliases, cascade)
    market_rules = _trim_rules(payload.market_rules, drop_rules, cascade)
    if not (entity_aliases or leagues or market_rules):
        raise ValueError("empty_batch")
    return BatchChangesPayload(
        entity_aliases=entity_aliases,
        leagues=leagues,
        market_rules=market_rules,
    )


def _drop_sets(
    drops: list[dict[str, str]],
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Parse trim keys into league / alias / rule / clone-bundle sets."""
    drop_leagues: set[str] = set()
    drop_aliases: set[str] = set()
    drop_rules: set[str] = set()
    drop_clones: set[str] = set()
    for item in drops:
        kind = str(item.get("kind") or "").strip()
        key = str(item.get("key") or "").strip()
        if not kind or not key:
            continue
        _add_drop(kind, key, drop_leagues, drop_aliases, drop_rules, drop_clones)
    return drop_leagues, drop_aliases, drop_rules, drop_clones


def _add_drop(
    kind: str,
    key: str,
    drop_leagues: set[str],
    drop_aliases: set[str],
    drop_rules: set[str],
    drop_clones: set[str],
) -> None:
    if kind == "league":
        slug = _parse_league_key(key)
        if slug:
            drop_leagues.add(slug)
        return
    if kind == "alias":
        if _parse_alias_key(key):
            drop_aliases.add(key)
        return
    if kind != "market_rule":
        return
    clone_slug = parse_clone_key(key)
    if clone_slug:
        drop_clones.add(clone_slug)
        return
    if _parse_rule_key(key):
        drop_rules.add(key)


def _trim_leagues(
    leagues: list[MappingLeaguePayload],
    drop_leagues: set[str],
    drop_clones: set[str],
    drop_rules: set[str],
    cascade_leagues: set[str],
    tip_rules: list[MarketRuleRow],
) -> list[MappingLeaguePayload]:
    out: list[MappingLeaguePayload] = []
    for lg in leagues:
        if lg.league in drop_leagues or lg.league in cascade_leagues:
            continue
        out.append(_trim_league_pin(lg, drop_clones, drop_rules, tip_rules))
    return out


def _trim_league_pin(
    lg: MappingLeaguePayload,
    drop_clones: set[str],
    drop_rules: set[str],
    tip_rules: list[MarketRuleRow],
) -> MappingLeaguePayload:
    if lg.league in drop_clones:
        clone_from, extra = None, []
    else:
        clone_from, extra = _kept_clone_pins(lg, drop_rules, tip_rules)
    kept_embedded = [pin for pin in lg.market_rules if rule_row_key(lg.league, pin) not in drop_rules]
    kept_rules = _merge_rule_pins(lg.league, kept_embedded, extra)
    if clone_from == lg.clone_market_rules_from and kept_rules == lg.market_rules:
        return lg
    return lg.model_copy(update={
        "clone_market_rules_from": clone_from,
        "market_rules": kept_rules,
    })


def _kept_clone_pins(
    lg: MappingLeaguePayload,
    drop_rules: set[str],
    tip_rules: list[MarketRuleRow],
) -> tuple[str | None, list[MarketRulePin]]:
    """Keep clone_from unless an individual cloned rule was dropped."""
    from_league = str(lg.clone_market_rules_from or "").strip()
    if not from_league:
        return None, []
    pins = clone_rule_pins(tip_rules, from_league)
    clone_keys = {rule_row_key(lg.league, pin) for pin in pins}
    if not (drop_rules & clone_keys):
        return from_league, []
    return None, [pin for pin in pins if rule_row_key(lg.league, pin) not in drop_rules]


def _merge_rule_pins(
    league: str,
    primary: list[MarketRulePin],
    extra: list[MarketRulePin],
) -> list[MarketRulePin]:
    seen = {rule_row_key(league, pin) for pin in primary}
    out = list(primary)
    for pin in extra:
        key = rule_row_key(league, pin)
        if key in seen:
            continue
        seen.add(key)
        out.append(pin)
    return out


def _trim_aliases(
    aliases: list[EntityAliasPayload],
    drop_keys: set[str],
    cascade_leagues: set[str],
) -> list[EntityAliasPayload]:
    out: list[EntityAliasPayload] = []
    for ea in aliases:
        if ea.league in cascade_leagues:
            continue
        kept_pins = []
        for pin in ea.aliases:
            key = f"alias:{ea.league}:{ea.canonical_key}:{pin.sportsbook}:{pin.alias_value}"
            if key in drop_keys:
                continue
            kept_pins.append(pin)
        if not kept_pins:
            continue
        out.append(ea.model_copy(update={"aliases": kept_pins}))
    return out


def _trim_rules(
    groups: list[MappingMarketRulesPayload],
    drop_keys: set[str],
    cascade_leagues: set[str],
) -> list[MappingMarketRulesPayload]:
    out: list[MappingMarketRulesPayload] = []
    for group in groups:
        if group.league in cascade_leagues:
            continue
        kept = []
        for rule in group.rules:
            key = (
                f"rule:{group.league}:{rule.sportsbook}:"
                f"{rule.source_key_type}:{rule.source_key}"
            )
            if key in drop_keys:
                continue
            kept.append(rule)
        if not kept:
            continue
        out.append(group.model_copy(update={"rules": kept}))
    return out


def trim_proposal_payload(
    proposal: ProposalRecord,
    drops: list[dict[str, str]],
    *,
    tip_league_slugs: set[str],
    tip_market_rules: list[MarketRuleRow] | None = None,
) -> BatchChangesPayload:
    """Apply drops to a batch proposal; raise if not batch or empty result."""
    payload = proposal.payload
    if not isinstance(payload, BatchChangesPayload):
        raise ValidationFailedError(
            "only batch_changes proposals support item trim",
            reason_code="not_batch",
            dry_run={},
        )
    try:
        return drop_batch_items(
            payload, drops, tip_league_slugs=tip_league_slugs,
            tip_market_rules=tip_market_rules,
        )
    except ValueError as exc:
        if str(exc) == "empty_batch":
            raise ValidationFailedError(
                "proposal would be empty after trim",
                reason_code="empty_batch",
                dry_run={},
            ) from exc
        raise


def payload_unchanged(before: BatchChangesPayload, after: BatchChangesPayload) -> bool:
    """True when trim matched no rows (retry after a timeout)."""
    return before.model_dump() == after.model_dump()


def closed_proposal_trim_error(status: str, note: str | None = None) -> ValidationFailedError:
    """Operator-facing error when Approve hits a card that is no longer open."""
    target = superseded_by_ref(note)
    if status == "rejected" and target:
        message = f"This harvest was superseded. Open the new card {target}."
    elif status == "rejected":
        message = "This harvest was rejected. Open Proposed for the live card."
    else:
        message = f"This proposal cannot be trimmed ({status})."
    return ValidationFailedError(
        message,
        reason_code="bad_status",
        dry_run={"status": status, "superseded_by": target or None},
    )
