"""Runshop exchange mapper — fixture chain + market crosswalk.

Runshop rows are stamped onto Optic-merged canonical rows after the
main merge.  Downstream clients query market_mapping with
sportsbook='Runshop' and resolve betbuilder prices via
tx_odds_fixture_id + market_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mappers.exchanges import optic
from mappers.exchanges.runshop_crosswalk import (
    CrosswalkRule,
    RunshopMarket,
    active_crosswalk_rules,
    build_market_index,
    load_crosswalk,
    lookup_runshop_market_id,
)
from mappers.exchanges.runshop_fixture import (
    FixtureChainRecord,
    FixtureLink,
    build_fixture_chain_index,
    load_fixture_chain,
)
from mappers.exchanges.runshop_vendor import load_vendor_markets
from mappers.shared import CanonicalRow

__all__ = [
    "CrosswalkRule",
    "FixtureChainRecord",
    "FixtureLink",
    "RunshopConfig",
    "RunshopMarket",
    "active_crosswalk_rules",
    "build_fixture_chain_index",
    "build_market_index",
    "load_crosswalk",
    "load_fixture_chain",
    "lookup_runshop_market_id",
    "stamp_runshop_rows",
]


@dataclass(frozen=True)
class RunshopConfig:
    """League-level Runshop settings."""

    markets_path: Path
    crosswalk_path: Path | None = None
    chain_filename: str = "runshop_fixture_chain.jsonl"
    crosswalk_rules: tuple[CrosswalkRule, ...] = ()


def _stamp_row(
    row: CanonicalRow,
    game_ref_lookup: dict[str, optic.GameRef],
    fixture_index: dict[str, FixtureLink],
    market_index: dict[tuple, int],
    active_rules: list[CrosswalkRule],
) -> bool:
    if row.optic_id is None:
        return False
    ref = game_ref_lookup.get(row.optic_id)
    if ref is None:
        return False
    link = fixture_index.get(ref.fixture_id)
    market_id = lookup_runshop_market_id(
        row, market_index, active_rules, flipped=bool(link and link.flipped),
    )
    if link is None or market_id is None:
        return False
    row.runshop_tx_odds_fixture_id = link.tx_odds_fixture_id
    row.runshop_market_id = market_id
    return True


def _crosswalk_for_config(cfg: RunshopConfig) -> list[CrosswalkRule]:
    if cfg.crosswalk_rules:
        return list(cfg.crosswalk_rules)
    if cfg.crosswalk_path is not None:
        return load_crosswalk(cfg.crosswalk_path)
    return []


def stamp_runshop_rows(
    rows: list[CanonicalRow],
    game_ref_lookup: dict[str, optic.GameRef],
    fixtures: list[optic.Fixture],
    chain_path: Path,
    cfg: RunshopConfig,
) -> int:
    """Stamp tx_odds_fixture_id and runshop_market_id on Optic-merged rows."""
    chain_records = load_fixture_chain(chain_path)
    if not chain_records:
        return 0

    markets = load_vendor_markets(cfg.markets_path)
    crosswalk = _crosswalk_for_config(cfg)
    active_rules = active_crosswalk_rules(crosswalk, markets, rows)
    if not active_rules:
        return 0

    fixture_index = build_fixture_chain_index(chain_records, fixtures)
    market_index = build_market_index(markets)
    return sum(
        1 for row in rows
        if _stamp_row(row, game_ref_lookup, fixture_index, market_index, active_rules)
    )
