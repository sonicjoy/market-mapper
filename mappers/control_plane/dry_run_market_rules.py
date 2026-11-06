"""Thin dry-run for mapping_market_rules proposals."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.dry_run_already import (
    noop_blockers,
    rule_already_msg,
    rule_change_msg,
    rule_effect,
)
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.store import LeagueRow, MarketRuleRow, new_id
from mappers.market_types import MarketType

_MARKET_TYPES = frozenset(member.value for member in MarketType)


def _match_key(league: str, sportsbook: str, source_key_type: str, source_key: str) -> tuple[str, str, str, str]:
    """Identity for upsert (action / canonical are mutable)."""
    return (league, sportsbook, source_key_type, source_key)


def served_signature(row: Any) -> tuple[Any, ...]:
    """Line, side, and official text. Notes and confidence stay noise."""
    offset = _row_field(row, "line_offset")
    return (
        None if offset is None or offset == "" else float(offset),
        _row_text(row, "yes_side"),
        bool(_row_field(row, "side_swap")),
        _row_text(row, "official_description"),
        _row_text(row, "citation_url"),
    )


def served_fields_differ(left: Any, right: Any) -> bool:
    """True when line, side, or official text would change the served tip."""
    return served_signature(left) != served_signature(right)


def _row_field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _row_text(row: Any, name: str) -> str:
    return str(_row_field(row, name) or "").strip()


def _served_change_msg(pin: MarketRulePin, league: str, effect: tuple[str, str]) -> str:
    """Warning when the canonical stays and line, side, or citation changes."""
    label = effect[1] or effect[0]
    return (
        f"{pin.sportsbook} {pin.source_key} on {league} stays {label}; "
        "line, side, or official text changes."
    )


def _rule_live_notes(
    payload: MappingMarketRulesPayload,
    existing: dict[tuple[str, str, str, str], MarketRuleRow],
) -> tuple[list[str], int, int, int]:
    """Per-pin already-live / change notes vs the tip."""
    notes: list[str] = []
    already = 0
    changing = 0
    replacing = 0
    for pin in payload.rules:
        key = _match_key(
            pin.league or payload.league,
            pin.sportsbook,
            pin.source_key_type,
            pin.source_key,
        )
        prior = existing.get(key)
        after = rule_effect(pin.action, pin.canonical_market_type)
        if prior is None:
            changing += 1
            continue
        replacing += 1
        league = pin.league or payload.league
        _count_rule_change(notes, pin, prior, after, league)
        if _rule_is_change(prior, pin, after):
            changing += 1
        else:
            already += 1
    return notes, already, changing, replacing


def _rule_is_change(prior: MarketRuleRow, pin: MarketRulePin, after: tuple[str, str]) -> bool:
    """Same action and canonical is still a change when served fields differ."""
    before = rule_effect(prior.action, prior.canonical_market_type)
    return before != after or served_fields_differ(prior, pin)


def _count_rule_change(
    notes: list[str],
    pin: MarketRulePin,
    prior: MarketRuleRow,
    after: tuple[str, str],
    league: str,
) -> None:
    """Append the trader-facing already-live or change line."""
    before = rule_effect(prior.action, prior.canonical_market_type)
    if before != after:
        notes.append(rule_change_msg(pin.sportsbook, pin.source_key, league, before, after))
        return
    if served_fields_differ(prior, pin):
        notes.append(_served_change_msg(pin, league, after))
        return
    notes.append(rule_already_msg(pin.sportsbook, pin.source_key, league, after))


def thin_dry_run_market_rules(
    leagues: list[LeagueRow],
    rules: list[MarketRuleRow],
    payload: MappingMarketRulesPayload,
) -> dict[str, Any]:
    """Fail closed when league missing, map lacks canonical, or all pins are live."""
    blockers: list[str] = []
    warnings: list[str] = [
        "Writes the mapping-rules snapshot. Approve/activate updates live classify from the BQ tip.",
    ]
    if payload.league not in {row.league for row in leagues}:
        blockers.append(f"league {payload.league!r} not in current snapshot")
    if not payload.rules:
        blockers.append("at least one market rule is required")
    for pin in payload.rules:
        blockers.extend(_kalshi_blockers(pin))
        blockers.extend(_canonical_blockers(pin))
    existing = {
        _match_key(r.league or "", r.sportsbook, r.source_key_type, r.source_key): r
        for r in rules
        if (r.league or "") == payload.league
    }
    notes, _already, changing, replacing = _rule_live_notes(payload, existing)
    warnings.extend(notes)
    blockers.extend(noop_blockers(change_count=changing, item_count=len(payload.rules)))
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "league": payload.league,
        "rule_count": len(payload.rules),
        "replacing": replacing,
        "change_count": changing,
        "item_count": len(payload.rules),
    }


def _kalshi_blockers(pin: MarketRulePin) -> list[str]:
    """Kalshi maps from its own typed fields; it takes no tip market rules."""
    if str(pin.sportsbook or "").strip().lower() != "kalshi":
        return []
    return [f"kalshi rule {pin.source_key!r}: Kalshi takes no market rules"]


def _canonical_blockers(pin: MarketRulePin) -> list[str]:
    """A map needs a canonical that is a real MarketType."""
    if pin.action != "map":
        return []
    canonical = (pin.canonical_market_type or "").strip()
    if not canonical:
        return [f"map rule {pin.source_key!r} needs canonical_market_type"]
    if canonical not in _MARKET_TYPES:
        return [f"map rule {pin.source_key!r} canonical {canonical!r} is not a MarketType"]
    return []


def _pin_to_row(
    league: str,
    pin: MarketRulePin,
    *,
    prior: MarketRuleRow | None = None,
) -> MarketRuleRow:
    """Convert a pin into a store row, keeping columns the pin does not carry."""
    return MarketRuleRow(
        rule_id=(prior.rule_id if prior else None) or new_id("mr"),
        league=pin.league or league,
        sportsbook=pin.sportsbook,
        rule_kind=pin.rule_kind,
        source_key_type=pin.source_key_type,
        source_key=pin.source_key,
        action=pin.action,
        canonical_market_type=pin.canonical_market_type,
        priority=pin.priority,
        enabled=pin.enabled,
        confidence=pin.confidence,
        match_operator=pin.match_operator,
        notes=pin.notes,
        line_offset=pin.line_offset,
        yes_side=pin.yes_side,
        side_swap=pin.side_swap,
        official_description=pin.official_description,
        citation_url=pin.citation_url,
        rule_group_id=prior.rule_group_id if prior else None,
        market_family=prior.market_family if prior else None,
        settlement_note=prior.settlement_note if prior else None,
    )


def apply_market_rules_payload(
    rules: list[MarketRuleRow],
    payload: MappingMarketRulesPayload,
) -> list[MarketRuleRow]:
    """Upsert proposed market rules by (league, sportsbook, source_key_type, source_key)."""
    out = list(rules)
    for pin in payload.rules:
        league = pin.league or payload.league
        key = _match_key(league, pin.sportsbook, pin.source_key_type, pin.source_key)
        kept: list[MarketRuleRow] = []
        prior: MarketRuleRow | None = None
        for row in out:
            row_key = _match_key(row.league or "", row.sportsbook, row.source_key_type, row.source_key)
            if row_key == key and prior is None:
                prior = row
                continue
            kept.append(row)
        kept.append(_pin_to_row(league, pin, prior=prior))
        out = kept
    return out


def clone_rules_for_league(
    rules: list[MarketRuleRow],
    *,
    from_league: str,
    to_league: str,
) -> list[MarketRuleRow]:
    """Copy market_rules from an analogue league onto a new league key."""
    cloned: list[MarketRuleRow] = []
    for row in rules:
        if row.league != from_league or str(row.sportsbook or "").lower() == "kalshi":
            continue
        cloned.append(
            MarketRuleRow(
                rule_id=new_id("mr"),
                league=to_league,
                sportsbook=row.sportsbook,
                rule_kind=row.rule_kind,
                source_key_type=row.source_key_type,
                source_key=row.source_key,
                action=row.action,
                canonical_market_type=row.canonical_market_type,
                priority=row.priority,
                enabled=row.enabled,
                confidence=row.confidence,
                match_operator=row.match_operator,
                notes=row.notes,
                line_offset=row.line_offset,
                yes_side=row.yes_side,
                side_swap=row.side_swap,
                official_description=row.official_description,
                citation_url=row.citation_url,
                rule_group_id=row.rule_group_id,
                market_family=row.market_family,
                settlement_note=row.settlement_note,
            )
        )
    return cloned
