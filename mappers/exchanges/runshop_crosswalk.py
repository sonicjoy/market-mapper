"""Runshop market crosswalk — tip rules, TOML archive, lookup keys."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mappers.shared import CanonicalRow

_SELECTION_MODES = frozenset({"over_under", "home_away", "three_way"})
_ENTITY_VALUES = frozenset({"home", "away"})


@dataclass(frozen=True)
class RunshopMarket:
    """One row from runshop_markets.toml."""

    id: int
    market: str
    value: float
    selection: str
    sport_id: int


@dataclass(frozen=True)
class CrosswalkRule:
    """One Optic market_type → Runshop market name mapping."""

    runshop_market: str
    optic_market_type: str
    selection: str
    entity: str | None = None


def load_runshop_markets(path: Path) -> list[RunshopMarket]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return [
        RunshopMarket(
            id=int(row["id"]),
            market=row["market"],
            value=float(row["value"]),
            selection=row["selection"],
            sport_id=int(row["sport_id"]),
        )
        for row in data.get("market", [])
    ]


def _crosswalk_entity(row: Any) -> str | None:
    """Read home/away entity tag from notes (BQ rows lack market_family)."""
    if row.notes:
        for part in str(row.notes).split(";"):
            piece = part.strip()
            if piece.startswith("entity="):
                val = piece.split("=", 1)[1].strip()
                if val in _ENTITY_VALUES:
                    return val
    return None


def crosswalk_rules_from_market_rules(
    rows: list[Any],
    *,
    league: str,
) -> list[CrosswalkRule]:
    """Invert ``mapping_market_rules`` crosswalk rows into runtime rules."""
    rules: list[CrosswalkRule] = []
    for row in rows:
        if row.league != league or not row.enabled or row.tombstone:
            continue
        if row.sportsbook != "runshop" or row.action != "map":
            continue
        if row.rule_kind != "crosswalk" or row.source_key_type != "optic_market_type":
            continue
        target = row.canonical_market_type
        if not target:
            continue
        selection = row.match_operator
        if selection not in _SELECTION_MODES:
            continue
        entity = _crosswalk_entity(row)
        if entity is not None and entity not in _ENTITY_VALUES:
            continue
        rules.append(CrosswalkRule(
            runshop_market=target,
            optic_market_type=row.source_key,
            selection=selection,
            entity=entity,
        ))
    return rules


def load_crosswalk(path: Path) -> list[CrosswalkRule]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    rules: list[CrosswalkRule] = []
    for row in data.get("crosswalk", []):
        selection = row["selection"]
        if selection not in _SELECTION_MODES:
            raise ValueError(
                f"invalid crosswalk selection {selection!r} for "
                f"{row['runshop_market']!r}",
            )
        entity = row.get("entity")
        if entity is not None and entity not in _ENTITY_VALUES:
            raise ValueError(
                f"invalid crosswalk entity {entity!r} for "
                f"{row['runshop_market']!r}",
            )
        rules.append(CrosswalkRule(
            runshop_market=row["runshop_market"],
            optic_market_type=row["optic_market_type"],
            selection=selection,
            entity=entity,
        ))
    return rules


def active_crosswalk_rules(
    rules: list[CrosswalkRule],
    markets: list[RunshopMarket],
    rows: list[CanonicalRow],
) -> list[CrosswalkRule]:
    """Keep rules whose Runshop market is in TOML and Optic type is upstream."""
    toml_markets = {m.market for m in markets}
    upstream_types = {
        row.market_type for row in rows if row.optic_id is not None
    }
    return [
        rule for rule in rules
        if rule.runshop_market in toml_markets
        and rule.optic_market_type in upstream_types
    ]


def build_market_index(markets: list[RunshopMarket]) -> dict[tuple, int]:
    """Reverse lookup: (market, value, selection) → Runshop market id."""
    index: dict[tuple, int] = {}
    for m in markets:
        index[(m.market, m.value, m.selection)] = m.id
    return index


def _entity_matches(rule: CrosswalkRule, row: CanonicalRow) -> bool:
    if rule.entity is None:
        return True
    if rule.entity == "home":
        return row.entity == row.home
    if rule.entity == "away":
        return row.entity == row.away
    return False


def _home_away_label(*, flipped: bool) -> tuple[str, str]:
    """Runshop Home is the title's first team. A crossed title swaps that against Optic."""
    if flipped:
        return "Away", "Home"
    return "Home", "Away"


def _selection_label(rule: CrosswalkRule, row: CanonicalRow, *, flipped: bool) -> str | None:
    if rule.selection == "over_under":
        if row.side == "over":
            return "Over"
        if row.side == "under":
            return "Under"
        return None
    if rule.selection in {"home_away", "three_way"}:
        home_label, away_label = _home_away_label(flipped=flipped)
        if row.side == row.home:
            return home_label
        if row.side == row.away:
            return away_label
        if rule.selection == "three_way" and row.side in ("tie", "_TIE", "draw"):
            return "Draw"
        return None
    return None


def _lookup_key_from_rule(
    rule: CrosswalkRule,
    row: CanonicalRow,
    *,
    flipped: bool,
) -> tuple[str, float, str] | None:
    if row.market_type != rule.optic_market_type:
        return None
    if not _entity_matches(rule, row):
        return None
    if row.line is None:
        return None
    selection = _selection_label(rule, row, flipped=flipped)
    if selection is None:
        return None
    return (rule.runshop_market, row.line, selection)


def lookup_runshop_market_id(
    row: CanonicalRow,
    market_index: dict[tuple, int],
    active_rules: list[CrosswalkRule],
    *,
    flipped: bool = False,
) -> int | None:
    for rule in active_rules:
        key = _lookup_key_from_rule(rule, row, flipped=flipped)
        if key is None:
            continue
        market_id = market_index.get(key)
        if market_id is not None:
            return market_id
    return None
