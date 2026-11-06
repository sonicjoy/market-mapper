"""COW lineage coalesce — tip-first last-write-wins, tombstones hide keys."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy

from mappers.control_plane.cow_diff import entity_key, league_key, market_rule_key
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def coalesce_entities(layers: Sequence[Iterable[EntityRow]]) -> list[EntityRow]:
    """Rebuild logical entities from tip→root sparse layers."""
    return _coalesce(
        layers,
        key_fn=entity_key,
        is_tombstone=lambda row: bool(row.tombstone),
    )


def coalesce_leagues(layers: Sequence[Iterable[LeagueRow]]) -> list[LeagueRow]:
    """Rebuild logical leagues from tip→root sparse layers."""
    return _coalesce(
        layers,
        key_fn=league_key,
        is_tombstone=lambda row: bool(row.tombstone),
    )


def coalesce_market_rules(
    layers: Sequence[Iterable[MarketRuleRow]],
) -> list[MarketRuleRow]:
    """Rebuild logical market rules from tip→root sparse layers."""
    return _coalesce(
        layers,
        key_fn=market_rule_key,
        is_tombstone=lambda row: bool(row.tombstone),
    )


def _coalesce[T](
    layers: Sequence[Iterable[T]],
    *,
    key_fn: Callable[[T], object],
    is_tombstone: Callable[[T], bool],
) -> list[T]:
    """Merge sparse layers from tip → root into one logical list."""
    seen: set[object] = set()
    out: list[T] = []
    for layer in layers:
        for row in layer:
            key = key_fn(row)
            if key in seen:
                continue
            seen.add(key)
            if is_tombstone(row):
                continue
            out.append(deepcopy(row))
    return out
