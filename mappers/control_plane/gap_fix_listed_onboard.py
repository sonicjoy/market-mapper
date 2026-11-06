"""Draft mapping_league for Underdog, DKEX, and Novig RFQ gaps when Optic has the league.

The venue token comes from the key (Underdog UDX venue, DKEX symbol league) or the
planner lookup (Novig league). The Optic league comes from the tip row that owns the
slug, ``optic_spine.csv``, or Novig's own ``opticOddsId``. Keys we cannot tie to one
Optic league stay ``needs_probe`` once the league is on the tip, unless the
Underdog code is in the team catalog or equals one Optic abbreviation. A key
with no venue token is ``no_source_league``. Nothing is guessed.
"""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_tools_dkex_mapping import dkex_league_token
from mappers.control_plane.gap_fix_dkex_leagues import DKEX_VENUE_BY_SLUG
from mappers.control_plane.gap_fix_novig_rfq import probe_wired_novig
from mappers.control_plane.gap_fix_onboard import gap_onboard_enabled, try_onboard_league_pin
from mappers.control_plane.gap_fix_underdog_rfq import probe_wired_underdog
from mappers.control_plane.gap_fix_walk import ensure_walk_recorded
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_inventory_league import LEAGUE_META_KEY, OPTIC_META_KEY
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.suggest_markets import spine_optic_league_id
from mappers.control_plane.underdog_legacy_ticker import venue_token_from_body
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG
from mappers.control_plane.underdog_team_catalog import team_catalog

LISTED_ONBOARD_BOOKS = frozenset({"underdog", "dkex", "novig"})


def harvest_listed_rfq_onboard(
    store: Any,
    book: str,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    rows: list[LeagueRow],
) -> None:
    """One league pin per venue league; every other key records why it did not pin."""
    seen: set[tuple[str, str, str]] = set()
    catalog = team_catalog() if book == "underdog" else {}
    entities = _entities(store) if book == "underdog" else []
    for item in items:
        if item.book != book or not item.key:
            continue
        before = len(skipped)
        if gap_onboard_enabled() and _try_onboard(store, book, item, pins, skipped, seen, rows):
            continue
        if book == "underdog" and _ready_for_alias(skipped, before, item.key):
            probe_wired_underdog(item, pins, skipped, rows, catalog, entities)
            ensure_walk_recorded(book, item.key, pins, skipped, 0, before)
            continue
        if book == "novig" and _ready_for_alias(skipped, before, item.key):
            probe_wired_novig(item, skipped, rows, _tip_rules(store))
            ensure_walk_recorded(book, item.key, pins, skipped, 0, before)
            continue
        if len(skipped) == before:
            skipped.append({"book": book, "key": item.key, "reason": "needs_probe"})


def _tip_rules(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "market_rules_for"):
        return []
    return list(store.market_rules_for(rid))


def _entities(store: Any) -> list[EntityRow]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return []
    return list(store.entities_for(rid))


def _ready_for_alias(skipped: list[dict[str, str]], before: int, key: str) -> bool:
    if len(skipped) == before:
        return True
    last = skipped[-1]
    if last.get("key") == key and last.get("reason") == "needs_probe":
        skipped.pop()
        return True
    return False


def _try_onboard(
    store: Any,
    book: str,
    item: RfqGapItem,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
) -> bool:
    token, optic_id = _venue_and_optic(book, item, rows)
    if not token:
        skipped.append({"book": book, "key": item.key, "reason": "no_source_league"})
        return False
    if not optic_id:
        skipped.append({"book": book, "key": item.key, "reason": "needs_league"})
        return False
    sport = _sport(optic_id, rows)
    if not sport:
        skipped.append({"book": book, "key": item.key, "reason": "needs_league"})
        return False
    return try_onboard_league_pin(
        store,
        optic_id=optic_id,
        sport=sport,
        source_token=token,
        book=book,
        pins=pins,
        skipped=skipped,
        seen=seen,
        rows=rows,
        fixtures={},
        gap_key=item.key,
        harvest_book=book,
    )


def _venue_and_optic(book: str, item: RfqGapItem, rows: list[LeagueRow]) -> tuple[str, str]:
    """(venue league token, Optic league id); empty strings when we have no evidence."""
    meta = item.meta or {}
    if book == "novig":
        return str(meta.get(LEAGUE_META_KEY) or ""), str(meta.get(OPTIC_META_KEY) or "")
    if book == "underdog":
        key = item.key.strip().upper()
        token = venue_token_from_body(key[3:] if key.startswith("UDX") else key) or ""
        slug = VENUE_TOKEN_TO_LEAGUE_SLUG.get(token, "")
    else:
        token = dkex_league_token(item.key).upper()
        slugs = [slug for slug, venue in DKEX_VENUE_BY_SLUG.items() if venue.upper() == token]
        slug = slugs[0] if len(slugs) == 1 else ""
    return token, (_optic_for_slug(slug, rows) if slug else "")


def _optic_for_slug(slug: str, rows: list[LeagueRow]) -> str:
    for row in rows:
        if str(row.league) == slug and not row.tombstone and row.optic_league_id:
            return str(row.optic_league_id)
    return spine_optic_league_id(slug)


def _sport(optic_id: str, rows: list[LeagueRow]) -> str:
    """Tip row sport, else the one sport Optic lists for the league; empty when unsure."""
    for row in rows:
        if row.optic_league_id == optic_id and row.sport and not row.tombstone:
            return str(row.sport)
    try:
        fixtures = cached_optic_fixtures(optic_id)
    except Exception:  # noqa: BLE001 — Optic outage leaves the key needs_league, not a failed card
        return ""
    sports = {_sport_id(fx.get("sport")) for fx in fixtures} - {""}
    return next(iter(sports)) if len(sports) == 1 else ""


def _sport_id(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("id") or "").strip()
    return str(raw or "").strip()
