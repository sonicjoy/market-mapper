"""Trader-facing snapshot deltas for review detail."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any

from mappers.control_plane.cow_diff import (
    classify_changes,
    entity_key,
    league_key,
    market_rule_key,
)
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_fix_ai_suggest import is_ai_suggest_pin
from mappers.control_plane.league_review import (
    book_label,
    format_league_mod,
    format_league_row,
    payload_league_group,
)
from mappers.control_plane.market_rule_card import market_rule_card
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow

_COUNT_KEYS = ("added_count", "modified_count", "removed_count")


def _league_name(slug: str | None) -> str:
    """Display label for a league key."""
    if not slug:
        return "?"
    return league_label(slug)


def _book_name(sportsbook: str) -> str:
    """Display label for a sportsbook id."""
    return book_label(sportsbook)


def _alias_target(key: str, name: str | None) -> str:
    """Canonical key, plus display name when it is not the key."""
    label = (name or "").strip()
    if not label or label == key:
        return key
    return f"{key} {label}"


def _fmt_pin(book: str, value: str, name: str | None) -> str:
    """Sportsbook + value; Optic and Polymarket US pins carry a display name."""
    label = f"{_book_name(book)} {value}".strip()
    shown = (name or "").strip()
    if shown and book.strip().lower() in {"optic", "polymarket_usa"}:
        return f"{label} ({shown})"
    return label


def _fmt_entity(row: EntityRow) -> str:
    """One-line entity pin for a checker."""
    target = _alias_target(row.canonical_key, row.canonical_name)
    pins: list[str] = []
    for alias in row.aliases:
        value = str(alias.get("alias_value") or "").strip()
        if not value:
            continue
        pins.append(
            _fmt_pin(str(alias.get("sportsbook") or ""), value, row.canonical_name)
        )
    pin = ", ".join(pins) if pins else row.canonical_key
    return f"Map {pin} → {target} ({_league_name(row.league)})"


def _fmt_league(row: LeagueRow) -> str:
    """One-line league for a checker."""
    return format_league_row(row)


def _fmt_rule_state(row: MarketRuleRow) -> str:
    """Action a checker needs: ignored vs mapped as a canonical type."""
    canonical = (row.canonical_market_type or "").strip()
    if row.action == "ignore" or not canonical:
        return "ignored"
    return f"mapped as {canonical}"


def _fmt_rule(row: MarketRuleRow) -> str:
    """One-line market rule for add/remove."""
    league = _league_name(row.league)
    book = _book_name(row.sportsbook)
    state = _fmt_rule_state(row)
    if state == "ignored":
        return f"Ignore {book} {row.source_key} on {league}"
    return f"Enable {book} {row.source_key} on {league}: {state}"


def _fmt_rule_mod(parent: MarketRuleRow, child: MarketRuleRow) -> str:
    """Parent → child action/canonical for a modified market rule."""
    league = _league_name(child.league or parent.league)
    book = _book_name(child.sportsbook)
    key = child.source_key
    before = _fmt_rule_state(parent)
    after = _fmt_rule_state(child)
    if before == "ignored" and after.startswith("mapped as"):
        return f"Enable {book} {key} on {league}: {before} → {after}"
    if after == "ignored" and before.startswith("mapped as"):
        return f"Stop mapping {book} {key} on {league}: {before} → {after}"
    if before == after:
        return _served_only_mod(parent, child, book, key, league, before, after)
    return f"Change {book} {key} on {league}: {before} → {after}"


def _served_only_mod(
    parent: MarketRuleRow,
    child: MarketRuleRow,
    book: str,
    key: str,
    league: str,
    before: str,
    after: str,
) -> str:
    """Served-field amend: line, side, or official text, not a retarget."""
    left = market_rule_card(parent, league=str(parent.league or child.league or ""))
    right = market_rule_card(child, league=str(child.league or parent.league or ""))
    if left["transform"] != right["transform"]:
        return f"Change {book} {key} on {league}: {left['transform']} → {right['transform']}"
    if left["venue"] != right["venue"]:
        return f"Change {book} {key} on {league}: {left['venue']} → {right['venue']}"
    return f"Change {book} {key} on {league}: {before} → {after}"


def _n(count: int, one: str, many: str) -> str:
    """Count plus singular/plural noun."""
    return f"{count} {one if count == 1 else many}"


def _kind_parts(one: str, many: str, group: dict[str, Any]) -> list[str]:
    """Human fragments for added/updated/removed of one artifact kind."""
    added = int(group["added_count"])
    modified = int(group["modified_count"])
    removed = int(group["removed_count"])
    bits: list[str] = []
    if added:
        bits.append(f"add {_n(added, one, many)}")
    if modified:
        bits.append(f"update {_n(modified, one, many)}")
    if removed:
        bits.append(f"remove {_n(removed, one, many)}")
    return bits


def _rule_parts(group: dict[str, Any]) -> list[str]:
    """Market-rule headline; special-case ignore↔map so Approve is obvious."""
    added = int(group["added_count"])
    modified = int(group["modified_count"])
    removed = int(group["removed_count"])
    lines = [str(line) for line in group.get("lines") or []]
    if modified and not added and not removed:
        if lines and all("ignored → mapped as" in line for line in lines):
            return [
                f"enable {_n(modified, 'ignored market rule', 'ignored market rules')} so they start mapping"
            ]
        if lines and all("→ ignored" in line for line in lines):
            return [f"ignore {_n(modified, 'mapped market rule', 'mapped market rules')}"]
    return _kind_parts("market rule", "market rules", group)


def change_headline(groups: dict[str, Any]) -> str:
    """One sentence a checker can read before the line list."""
    parts = [
        *_kind_parts("alias", "aliases", groups["aliases"]),
        *_kind_parts("league", "leagues", groups["leagues"]),
        *_rule_parts(groups["market_rules"]),
    ]
    if not parts:
        return "No mapping rows change versus live."
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def headline_from_mapping_rows(rows: list[dict[str, Any]]) -> str:
    """Headline from Keep/Drop cards so it matches Proposed tab counts."""
    def _empty() -> dict[str, Any]:
        return {"added_count": 0, "modified_count": 0, "removed_count": 0, "lines": []}

    buckets = {
        "aliases": _empty(),
        "leagues": _empty(),
        "market_rules": _empty(),
    }
    kind_map = {"alias": "aliases", "league": "leagues", "market_rule": "market_rules"}
    action_map = {"add": "added_count", "update": "modified_count", "delete": "removed_count"}
    for row in rows:
        bucket = buckets.get(kind_map.get(str(row.get("kind") or ""), ""))
        key = action_map.get(str(row.get("action") or "add"))
        if bucket is None or key is None:
            continue
        bucket[key] = int(bucket[key]) + 1
    return change_headline(buckets)


def _group[K: Hashable, R: (EntityRow, LeagueRow, MarketRuleRow)](
    parent: list[R],
    child: list[R],
    key_fn: Callable[[R], K],
    fmt: Callable[[R], str],
    fmt_mod: Callable[[R, R], str] | None = None,
) -> dict[str, Any]:
    """Counts plus prefixed lines for one artifact kind."""
    parent_map = {key_fn(row): row for row in parent if not row.tombstone}
    child_map = {key_fn(row): row for row in child if not row.tombstone}
    added, modified, removed = classify_changes(parent_map, child_map)
    mod_lines: list[str] = []
    for row in modified:
        prior = parent_map[key_fn(row)]
        text = fmt_mod(prior, row) if fmt_mod is not None else fmt(row)
        mod_lines.append(f"~ {text}")
    lines = sorted(
        [f"+ {fmt(row)}" for row in added]
        + mod_lines
        + [f"- {fmt(row)}" for row in removed]
    )
    return {
        "added_count": len(added),
        "modified_count": len(modified),
        "removed_count": len(removed),
        "lines": lines,
    }


def snapshot_change_groups(
    parent_ent: list[EntityRow],
    child_ent: list[EntityRow],
    parent_lg: list[LeagueRow],
    child_lg: list[LeagueRow],
    parent_mr: list[MarketRuleRow],
    child_mr: list[MarketRuleRow],
) -> dict[str, Any]:
    """Per-kind added / modified / removed vs parent, with row lines."""
    return {
        "aliases": _group(parent_ent, child_ent, entity_key, _fmt_entity),
        "leagues": _group(
            parent_lg, child_lg, league_key, _fmt_league, fmt_mod=format_league_mod
        ),
        "market_rules": _group(
            parent_mr, child_mr, market_rule_key, _fmt_rule, fmt_mod=_fmt_rule_mod
        ),
    }


def totals_from_groups(groups: dict[str, Any]) -> dict[str, int]:
    """Flatten per-kind counts into the stored change_summary shape."""
    return {
        key: sum(int(group[key]) for group in groups.values())
        for key in _COUNT_KEYS
    }


def payload_change_groups(
    payload: object, tip_leagues: list[LeagueRow] | None = None
) -> dict[str, Any]:
    """Counts and lines from the submitted payload (no full snapshot walk)."""
    return {
        "aliases": _payload_alias_group(_payload_alias_entries(payload)),
        "leagues": payload_league_group(payload, tip_leagues),
        "market_rules": _added_group(_payload_rule_lines(payload), defer="AI suggestion:"),
    }


def refresh_alias_lines(groups: dict[str, Any], payload: object) -> dict[str, Any]:
    """Rebuild alias checker lines from payload so canonical keys stay visible."""
    entries = _payload_alias_entries(payload)
    if not entries:
        return groups
    aliases = dict(groups.get("aliases") or {})
    aliases["lines"] = _payload_alias_group(entries)["lines"]
    return {**groups, "aliases": aliases}


def _payload_alias_group(entries: list[tuple[str, str]]) -> dict[str, Any]:
    """Split payload alias rows into add (+) and remove (-) checker lines."""
    adds: list[str] = []
    removes: list[str] = []
    defer: list[str] = []
    for kind, text in entries:
        if not text.strip():
            continue
        if kind == "remove":
            removes.append(f"- {text}")
        elif text.startswith("AI suggestion:"):
            defer.append(f"+ {text}")
        else:
            adds.append(f"+ {text}")
    lines = adds + removes + defer
    return {
        "added_count": len(adds) + len(defer),
        "modified_count": 0,
        "removed_count": len(removes),
        "lines": lines,
    }


def _payload_alias_entries(payload: object) -> list[tuple[str, str]]:
    """(add|remove, line) per entity_alias payload row."""
    if isinstance(payload, EntityAliasPayload):
        return [_alias_payload_entry(payload)]
    if isinstance(payload, BatchChangesPayload):
        return [_alias_payload_entry(entity) for entity in payload.entity_aliases]
    return []


def _alias_payload_entry(entity: EntityAliasPayload) -> tuple[str, str]:
    """One checker line for an entity_alias payload."""
    pins = [pin for pin in entity.aliases if pin.alias_value.strip()]
    if pins and all(pin.remove for pin in pins):
        text = "; ".join(_fmt_alias_remove(entity, pin) for pin in pins)
        return "remove", text
    text = _fmt_alias_add(entity)
    if is_ai_suggest_pin(entity):
        text = f"AI suggestion: {text}"
    return "add", text


def _fmt_alias_remove(entity: EntityAliasPayload, pin: AliasPin) -> str:
    """One-line alias removal for a checker."""
    target = _alias_target(entity.canonical_key, entity.canonical_name)
    label = _fmt_pin(pin.sportsbook, pin.alias_value, _pin_name(entity, pin))
    return f"Remove {label} from {target} ({_league_name(entity.league)})"


def _added_group(texts: list[str], *, defer: str = "") -> dict[str, Any]:
    """Treat every payload row as an add versus live. ``defer`` lines sort last."""
    lines = [f"+ {text}" for text in texts if text.strip()]
    lines.sort(key=lambda line: (bool(defer) and defer in line, line))
    return {
        "added_count": len(lines),
        "modified_count": 0,
        "removed_count": 0,
        "lines": lines,
    }


def _fmt_alias_add(entity: EntityAliasPayload) -> str:
    """One-line alias pin for a checker."""
    target = _alias_target(entity.canonical_key, entity.canonical_name)
    pins = [
        _fmt_pin(alias.sportsbook, alias.alias_value, _pin_name(entity, alias))
        for alias in entity.aliases
        if alias.alias_value.strip() and not alias.remove
    ]
    pin = ", ".join(pins) if pins else entity.canonical_key
    return f"Map {pin} → {target} ({_league_name(entity.league)})"


def _fmt_alias_payload(entity: EntityAliasPayload) -> str:
    """One-line alias pin for a checker (legacy callers)."""
    kind, text = _alias_payload_entry(entity)
    return text


def _pin_name(entity: EntityAliasPayload, pin: AliasPin) -> str:
    """Gateway US name when harvested, else the canonical display name."""
    if pin.sportsbook.strip().lower() == "polymarket_usa":
        usa = _usa_evidence_name(entity)
        if usa:
            return usa
    return str(entity.canonical_name or "")


def _usa_evidence_name(entity: EntityAliasPayload) -> str:
    """polymarket_usa:name from harvest evidence, if present."""
    prefix = "polymarket_usa:name:"
    for ref in entity.evidence_refs:
        if ref.startswith(prefix):
            return ref[len(prefix) :].strip()
    return ""


def _fmt_pin_rule(league: str, pin: MarketRulePin, *, ai: bool = False) -> str:
    """One-line market rule from a submitted pin."""
    book = _book_name(pin.sportsbook)
    label = _league_name(league)
    canonical = (pin.canonical_market_type or "").strip()
    if pin.action == "ignore" or not canonical:
        text = f"Ignore {book} {pin.source_key} on {label}"
    else:
        text = f"Enable {book} {pin.source_key} on {label}: mapped as {canonical}"
    if ai:
        return f"AI suggestion: {text}"
    return text


def _payload_rule_lines(payload: object) -> list[str]:
    """Market-rule lines from a rule artifact, league onboard, or batch."""
    if isinstance(payload, MappingMarketRulesPayload):
        ai = is_ai_suggest_pin(payload)
        return [_fmt_pin_rule(payload.league, rule, ai=ai) for rule in payload.rules]
    if isinstance(payload, MappingLeaguePayload):
        ai = is_ai_suggest_pin(payload)
        return [_fmt_pin_rule(payload.league, rule, ai=ai) for rule in payload.market_rules]
    if isinstance(payload, BatchChangesPayload):
        return _batch_rule_lines(payload)
    return []


def _batch_rule_lines(payload: BatchChangesPayload) -> list[str]:
    """Nested league clones plus explicit market_rules groups."""
    lines: list[str] = []
    for league in payload.leagues:
        ai = is_ai_suggest_pin(league)
        lines.extend(_fmt_pin_rule(league.league, rule, ai=ai) for rule in league.market_rules)
    for group in payload.market_rules:
        ai = is_ai_suggest_pin(group)
        lines.extend(_fmt_pin_rule(group.league, rule, ai=ai) for rule in group.rules)
    return lines
