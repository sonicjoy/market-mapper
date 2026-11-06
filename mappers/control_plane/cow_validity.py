"""Append-only rule validity opens (on/off windows via LEAD at read time)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def new_id(prefix: str) -> str:
    """Allocate a short prefixed opaque id."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ValidityOpen:
    """One append-only open event for a natural key."""

    validity_id: str
    table_kind: str
    natural_key: str
    introduced_in_rule_set_id: str
    effective_from: str
    enabled: bool
    environment: str
    league: str | None = None
    payload: dict[str, Any] | None = None


@dataclass
class ValidityWindow:
    """Reconstructed on/off window for traders / audit."""

    table_kind: str
    natural_key: str
    introduced_in_rule_set_id: str
    effective_from: str
    effective_to: str | None
    enabled: bool
    league: str | None = None
    payload: dict[str, Any] | None = None


def validity_windows(opens: list[ValidityOpen]) -> list[ValidityWindow]:
    """Pair opens with LEAD(effective_from) as effective_to (sorted)."""
    ordered = sorted(opens, key=lambda row: (row.effective_from, row.validity_id))
    out: list[ValidityWindow] = []
    for index, row in enumerate(ordered):
        nxt = ordered[index + 1] if index + 1 < len(ordered) else None
        out.append(
            ValidityWindow(
                table_kind=row.table_kind,
                natural_key=row.natural_key,
                introduced_in_rule_set_id=row.introduced_in_rule_set_id,
                effective_from=row.effective_from,
                effective_to=nxt.effective_from if nxt else None,
                enabled=row.enabled,
                league=row.league,
                payload=row.payload,
            )
        )
    return out


def opens_for_activation(
    *,
    environment: str,
    introduced_in_rule_set_id: str,
    effective_from: str | None = None,
    previous_entities: list[EntityRow],
    next_entities: list[EntityRow],
    previous_leagues: list[LeagueRow] | None = None,
    next_leagues: list[LeagueRow] | None = None,
    previous_market_rules: list[MarketRuleRow] | None = None,
    next_market_rules: list[MarketRuleRow] | None = None,
) -> list[ValidityOpen]:
    """Emit validity opens for natural keys whose winning version changed."""
    from mappers.control_plane.cow_validity_opens import (
        entity_opens,
        league_opens,
        market_rule_opens,
    )

    when = effective_from or _now()
    out = entity_opens(
        environment=environment,
        introduced_in_rule_set_id=introduced_in_rule_set_id,
        when=when,
        previous=previous_entities,
        nxt=next_entities,
    )
    out.extend(
        league_opens(
            environment=environment,
            introduced_in_rule_set_id=introduced_in_rule_set_id,
            when=when,
            previous=previous_leagues or [],
            nxt=next_leagues or [],
        )
    )
    out.extend(
        market_rule_opens(
            environment=environment,
            introduced_in_rule_set_id=introduced_in_rule_set_id,
            when=when,
            previous=previous_market_rules or [],
            nxt=next_market_rules or [],
        )
    )
    return out


@dataclass
class InMemoryValidityStore:
    """Test/local validity opens + window reconstruction."""

    opens: list[ValidityOpen] = field(default_factory=list)

    def append_opens(self, rows: list[ValidityOpen]) -> None:
        """Append validity-open events."""
        self.opens.extend(rows)

    def history(
        self,
        *,
        table_kind: str,
        natural_key: str,
    ) -> list[ValidityWindow]:
        """On/off windows for one natural key."""
        matched = [
            row
            for row in self.opens
            if row.table_kind == table_kind and row.natural_key == natural_key
        ]
        return validity_windows(matched)
