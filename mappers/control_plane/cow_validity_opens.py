"""Split validity-open builders (size-guard friendly)."""

from __future__ import annotations

from mappers.control_plane.cow_diff import (
    entity_key,
    entity_key_str,
    league_key,
    league_key_str,
    market_rule_key,
    market_rule_key_str,
)
from mappers.control_plane.cow_validity import ValidityOpen, new_id
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def entity_opens(
    *,
    environment: str,
    introduced_in_rule_set_id: str,
    when: str,
    previous: list[EntityRow],
    nxt: list[EntityRow],
) -> list[ValidityOpen]:
    """Validity opens for entity natural keys that changed."""
    out: list[ValidityOpen] = []
    prev_map = {entity_key(row): row for row in previous if not row.tombstone}
    next_map = {entity_key(row): row for row in nxt if not row.tombstone}
    out.extend(
        _entity_upserts(environment, introduced_in_rule_set_id, when, prev_map, next_map)
    )
    out.extend(
        _entity_tombstones(environment, introduced_in_rule_set_id, when, prev_map, next_map)
    )
    return out


def _entity_upserts(
    environment: str,
    introduced_in: str,
    when: str,
    prev_map: dict,
    next_map: dict,
) -> list[ValidityOpen]:
    out: list[ValidityOpen] = []
    for key, row in next_map.items():
        prior = prev_map.get(key)
        if prior is None or prior != row:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="entity",
                    natural_key=entity_key_str(row),
                    introduced_in_rule_set_id=introduced_in,
                    effective_from=when,
                    enabled=bool(row.enabled),
                    environment=environment,
                    league=row.league,
                    payload={
                        "entity_type": row.entity_type,
                        "canonical_key": row.canonical_key,
                    },
                )
            )
    return out


def _entity_tombstones(
    environment: str,
    introduced_in: str,
    when: str,
    prev_map: dict,
    next_map: dict,
) -> list[ValidityOpen]:
    out: list[ValidityOpen] = []
    for key, prior in prev_map.items():
        if key not in next_map:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="entity",
                    natural_key=entity_key_str(prior),
                    introduced_in_rule_set_id=introduced_in,
                    effective_from=when,
                    enabled=False,
                    environment=environment,
                    league=prior.league,
                    payload={
                        "entity_type": prior.entity_type,
                        "canonical_key": prior.canonical_key,
                        "tombstone": True,
                    },
                )
            )
    return out


def league_opens(
    *,
    environment: str,
    introduced_in_rule_set_id: str,
    when: str,
    previous: list[LeagueRow],
    nxt: list[LeagueRow],
) -> list[ValidityOpen]:
    """Validity opens for league keys that changed."""
    out: list[ValidityOpen] = []
    prev_map = {league_key(row): row for row in previous if not row.tombstone}
    next_map = {league_key(row): row for row in nxt if not row.tombstone}
    for key, row in next_map.items():
        prior = prev_map.get(key)
        if prior is None or prior != row:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="league",
                    natural_key=league_key_str(row),
                    introduced_in_rule_set_id=introduced_in_rule_set_id,
                    effective_from=when,
                    enabled=bool(row.enabled),
                    environment=environment,
                    league=row.league,
                )
            )
    for key, prior in prev_map.items():
        if key not in next_map:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="league",
                    natural_key=league_key_str(prior),
                    introduced_in_rule_set_id=introduced_in_rule_set_id,
                    effective_from=when,
                    enabled=False,
                    environment=environment,
                    league=prior.league,
                    payload={"tombstone": True},
                )
            )
    return out


def market_rule_opens(
    *,
    environment: str,
    introduced_in_rule_set_id: str,
    when: str,
    previous: list[MarketRuleRow],
    nxt: list[MarketRuleRow],
) -> list[ValidityOpen]:
    """Validity opens for market-rule keys that changed."""
    out: list[ValidityOpen] = []
    prev_map = {market_rule_key(row): row for row in previous if not row.tombstone}
    next_map = {market_rule_key(row): row for row in nxt if not row.tombstone}
    for key, row in next_map.items():
        prior = prev_map.get(key)
        if prior is None or prior != row:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="market_rule",
                    natural_key=market_rule_key_str(row),
                    introduced_in_rule_set_id=introduced_in_rule_set_id,
                    effective_from=when,
                    enabled=bool(row.enabled),
                    environment=environment,
                    league=row.league,
                    payload={
                        "sportsbook": row.sportsbook,
                        "source_key_type": row.source_key_type,
                        "source_key": row.source_key,
                    },
                )
            )
    for key, prior in prev_map.items():
        if key not in next_map:
            out.append(
                ValidityOpen(
                    validity_id=new_id("val"),
                    table_kind="market_rule",
                    natural_key=market_rule_key_str(prior),
                    introduced_in_rule_set_id=introduced_in_rule_set_id,
                    effective_from=when,
                    enabled=False,
                    environment=environment,
                    league=prior.league,
                    payload={"tombstone": True},
                )
            )
    return out
