"""Novig RFQ keys whose league is already on the tip.

Novig maps by ``competitor.opticOddsId`` / ``player.opticOddsId``. A wired
league closes from that id and the market type. There is no name guess and
no alias pin.
"""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_inventory_league import LEAGUE_META_KEY, MARKET_TYPE_KEY, OPTIC_ENTITY_KEY
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.market_types import MarketType, Scope
from mappers.seed.overlay_taxonomy import overlay_novig
from mappers.vocab.novig_markets import classify_novig_type, novig_config_for_sport


def harvest_listed_rfq_inventory(
    book: str,
    items: list[RfqGapItem],
    skipped: list[dict[str, str]],
) -> None:
    """Record RFQ keys so the gap ledger sees demand; alias probe TBD."""
    for item in items:
        if item.book != book or not item.key:
            continue
        skipped.append({"book": book, "key": item.key, "reason": "needs_probe"})


def harvest_novig_rfq_inventory(
    items: list[RfqGapItem],
    skipped: list[dict[str, str]],
) -> None:
    """Record Novig RFQ keys so the gap ledger sees demand; alias probe TBD."""
    harvest_listed_rfq_inventory("novig", items, skipped)


def probe_wired_novig(
    item: RfqGapItem,
    skipped: list[dict[str, str]],
    rows: list[LeagueRow],
    rules: list[MarketRuleRow] | None = None,
) -> None:
    """Close a wired Novig key from the Optic id the live mapper already trusts."""
    meta = item.meta or {}
    market_type = str(meta.get(MARKET_TYPE_KEY) or "").strip()
    optic_id = str(meta.get(OPTIC_ENTITY_KEY) or "").strip()
    if not market_type:
        _skip(skipped, item.key, "needs_probe")
        return
    status, mapped, _league = novig_rule_status(
        rows, rules or [], str(meta.get(LEAGUE_META_KEY) or ""), market_type,
    )
    if status == "ignored":
        _skip(skipped, item.key, "out_of_scope")
        return
    if status != "mapped" or mapped is None:
        _skip(skipped, item.key, "needs_code")
        return
    if mapped.scope != Scope.GAME and not optic_id:
        _skip(skipped, item.key, "missing_optic")
        return
    _skip(skipped, item.key, "already_mapped")


def novig_rule_status(
    rows: list[LeagueRow],
    rules: list[MarketRuleRow],
    token: str,
    market_type: str,
) -> tuple[str, MarketType | None, str]:
    """Python crosswalk, then a tip map or ignore for a type the table does not list."""
    sport, league = _league_for_token(rows, token)
    if not market_type or not sport:
        return "unknown", None, league
    status, mapped = classify_novig_type(sport, market_type)
    if status != "unknown":
        return status, mapped, league
    overlaid = _overlay(sport, league, rules)
    if overlaid is None:
        return "unknown", None, league
    if market_type in overlaid.market_types:
        return "mapped", overlaid.market_types[market_type], league
    if market_type in overlaid.ignored_types:
        return "ignored", None, league
    return "unknown", None, league


def _league_for_token(rows: list[LeagueRow], token: str) -> tuple[str, str]:
    """(sport, league slug) for the tip row whose Novig settings.league matches."""
    wanted = token.strip().casefold()
    if not wanted:
        return "", ""
    for row in rows:
        if row.tombstone:
            continue
        for ex in row.exchanges or []:
            if str(ex.get("sportsbook") or "") != "novig":
                continue
            settings: Any = ex.get("settings") or {}
            league = str(settings.get("league") or "").strip()
            if league.casefold() == wanted:
                return str(row.sport or ""), str(row.league or "")
    return "", ""


def _overlay(sport: str, league: str, rules: list[MarketRuleRow]) -> Any:
    base = novig_config_for_sport(sport, league)
    if base is None or not league:
        return base
    mine = [
        row for row in rules
        if str(row.league or "") == league and str(row.sportsbook or "") == "novig"
    ]
    return overlay_novig(base, mine, None)


def _skip(skipped: list[dict[str, str]], key: str, reason: str) -> None:
    skipped.append({"book": "novig", "key": key, "reason": reason})
