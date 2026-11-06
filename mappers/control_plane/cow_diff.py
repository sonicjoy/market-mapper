"""Diff full logical snapshots into COW deltas (upserts + tombstones)."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from copy import deepcopy

from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def entity_key(row: EntityRow) -> tuple[str, str, str]:
    """Natural key for an entity row."""
    return (row.league, row.entity_type, row.canonical_key)


def league_key(row: LeagueRow) -> str:
    """Natural key for a league row."""
    return row.league


def market_rule_key(row: MarketRuleRow) -> tuple[str | None, str, str, str]:
    """Natural key for a market rule row."""
    return (row.league, row.sportsbook, row.source_key_type, row.source_key)


def entity_key_str(row: EntityRow) -> str:
    """Pipe-separated natural key for validity / history."""
    return f"{row.league}|{row.entity_type}|{row.canonical_key}"


def league_key_str(row: LeagueRow) -> str:
    """Pipe-separated natural key for a league."""
    return row.league


def market_rule_key_str(row: MarketRuleRow) -> str:
    """Pipe-separated natural key for a market rule."""
    return f"{row.league or ''}|{row.sportsbook}|{row.source_key_type}|{row.source_key}"


_CONTENT_NOISE = ("tombstone", "notes", "confidence", "rule_id")


def _content_eq(left: EntityRow | LeagueRow | MarketRuleRow, right: EntityRow | LeagueRow | MarketRuleRow) -> bool:
    """Compare mapping effect; ignore audit-only fields."""
    a = deepcopy(left.__dict__)
    b = deepcopy(right.__dict__)
    for key in _CONTENT_NOISE:
        a.pop(key, None)
        b.pop(key, None)
    _norm_side_swap(a)
    _norm_side_swap(b)
    return a == b


def _norm_side_swap(fields: dict[str, object]) -> None:
    """False and null are the same served value: no flip."""
    if "side_swap" in fields:
        fields["side_swap"] = bool(fields["side_swap"])


def _alive_map[K: Hashable, R: (EntityRow, LeagueRow, MarketRuleRow)](
    rows: list[R],
    key_fn: Callable[[R], K],
) -> dict[K, R]:
    """Index live (non-tombstone) rows by natural key."""
    return {key_fn(row): row for row in rows if not row.tombstone}


def classify_changes[K: Hashable, R: (EntityRow, LeagueRow, MarketRuleRow)](
    parent_map: dict[K, R],
    child_map: dict[K, R],
) -> tuple[list[R], list[R], list[R]]:
    """Split a keyed snapshot pair into added / modified / removed rows."""
    added: list[R] = []
    modified: list[R] = []
    removed: list[R] = []
    for key, row in child_map.items():
        prior = parent_map.get(key)
        if prior is None:
            added.append(row)
        elif not _content_eq(prior, row):
            modified.append(row)
    for key, row in parent_map.items():
        if key not in child_map:
            removed.append(row)
    return added, modified, removed


def keyed_change_counts[K: Hashable, R: (EntityRow, LeagueRow, MarketRuleRow)](
    parent_map: dict[K, R],
    child_map: dict[K, R],
) -> dict[str, int]:
    """added / removed / modified counts for a keyed snapshot pair."""
    added, modified, removed = classify_changes(parent_map, child_map)
    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
    }


def entity_change_counts(parent: list[EntityRow], child: list[EntityRow]) -> dict[str, int]:
    """added / removed / modified counts for a logical entity snapshot pair."""
    return keyed_change_counts(_alive_map(parent, entity_key), _alive_map(child, entity_key))


def league_change_counts(parent: list[LeagueRow], child: list[LeagueRow]) -> dict[str, int]:
    """added / removed / modified counts for a logical league snapshot pair."""
    return keyed_change_counts(_alive_map(parent, league_key), _alive_map(child, league_key))


def market_rule_change_counts(
    parent: list[MarketRuleRow],
    child: list[MarketRuleRow],
) -> dict[str, int]:
    """added / removed / modified counts for a logical market-rule snapshot pair."""
    return keyed_change_counts(
        _alive_map(parent, market_rule_key),
        _alive_map(child, market_rule_key),
    )


def add_change_counts(*parts: dict[str, int]) -> dict[str, int]:
    """Sum added / removed / modified dicts."""
    return {
        "added_count": sum(part["added_count"] for part in parts),
        "removed_count": sum(part["removed_count"] for part in parts),
        "modified_count": sum(part["modified_count"] for part in parts),
    }


def snapshot_change_counts(
    parent_ent: list[EntityRow],
    child_ent: list[EntityRow],
    parent_lg: list[LeagueRow],
    child_lg: list[LeagueRow],
    parent_mr: list[MarketRuleRow],
    child_mr: list[MarketRuleRow],
) -> dict[str, int]:
    """Entity + league + market-rule added / removed / modified vs parent."""
    return add_change_counts(
        entity_change_counts(parent_ent, child_ent),
        league_change_counts(parent_lg, child_lg),
        market_rule_change_counts(parent_mr, child_mr),
    )


def diff_entities(parent: list[EntityRow], child: list[EntityRow]) -> list[EntityRow]:
    """Return entity upserts/tombstones that turn parent into child."""
    parent_map = {entity_key(row): row for row in parent if not row.tombstone}
    child_map = {entity_key(row): row for row in child if not row.tombstone}
    out: list[EntityRow] = []
    for key, row in child_map.items():
        prior = parent_map.get(key)
        if prior is None or not _content_eq(prior, row):
            clone = deepcopy(row)
            clone.tombstone = False
            out.append(clone)
    for key, prior in parent_map.items():
        if key not in child_map:
            out.append(
                EntityRow(
                    league=prior.league,
                    entity_type=prior.entity_type,
                    canonical_key=prior.canonical_key,
                    canonical_name=prior.canonical_name,
                    aliases=[],
                    enabled=False,
                    notes=prior.notes,
                    tombstone=True,
                )
            )
    return out


def diff_leagues(parent: list[LeagueRow], child: list[LeagueRow]) -> list[LeagueRow]:
    """Return league upserts/tombstones that turn parent into child."""
    parent_map = {league_key(row): row for row in parent if not row.tombstone}
    child_map = {league_key(row): row for row in child if not row.tombstone}
    out: list[LeagueRow] = []
    for key, row in child_map.items():
        prior = parent_map.get(key)
        if prior is None or not _content_eq(prior, row):
            clone = deepcopy(row)
            clone.tombstone = False
            out.append(clone)
    for key, prior in parent_map.items():
        if key not in child_map:
            out.append(
                LeagueRow(
                    league=prior.league,
                    sport=prior.sport,
                    optic_league_id=prior.optic_league_id,
                    extra_optic_league_ids=[],
                    fixture_source=prior.fixture_source,
                    fixture_horizon_hours=prior.fixture_horizon_hours,
                    enabled=False,
                    output_order=[],
                    exchanges=[],
                    notes=prior.notes,
                    tombstone=True,
                )
            )
    return out


def diff_market_rules(
    parent: list[MarketRuleRow],
    child: list[MarketRuleRow],
) -> list[MarketRuleRow]:
    """Return market-rule upserts/tombstones that turn parent into child."""
    parent_map = {market_rule_key(row): row for row in parent if not row.tombstone}
    child_map = {market_rule_key(row): row for row in child if not row.tombstone}
    out: list[MarketRuleRow] = []
    for key, row in child_map.items():
        prior = parent_map.get(key)
        if prior is None or not _content_eq(prior, row):
            clone = deepcopy(row)
            clone.tombstone = False
            out.append(clone)
    for key, prior in parent_map.items():
        if key not in child_map:
            out.append(
                MarketRuleRow(
                    rule_id=prior.rule_id,
                    league=prior.league,
                    sportsbook=prior.sportsbook,
                    rule_kind=prior.rule_kind,
                    source_key_type=prior.source_key_type,
                    source_key=prior.source_key,
                    action=prior.action,
                    canonical_market_type=prior.canonical_market_type,
                    priority=prior.priority,
                    enabled=False,
                    confidence=prior.confidence,
                    match_operator=prior.match_operator,
                    notes=prior.notes,
                    tombstone=True,
                    line_offset=prior.line_offset,
                    yes_side=prior.yes_side,
                    side_swap=prior.side_swap,
                    official_description=prior.official_description,
                    citation_url=prior.citation_url,
                    rule_group_id=prior.rule_group_id,
                    market_family=prior.market_family,
                    settlement_note=prior.settlement_note,
                )
            )
    return out
