"""Harvest DKEX league enable + name aliases (empty RFQ inventory ok).

No market-rule pins: DKEX market types come from the per-sport code
vocab (``mappers/vocab/dkex_markets.py``) and tip rules never reach the
DKEX pass.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from mappers.canonical_codes import names_fit
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.gap_fix_dkex_leagues import (
    DKEX_BOOK,
    ENABLED_LEAGUE_SLUGS,
    dkex_venue_token,
    enable_dkex_pin,
    venue_token_for_slug,
)
from mappers.control_plane.rows import LeagueRow
from mappers.exchanges import dkex as dkex_mod
from mappers.exchanges.dkex_names import city_abbrev_fits

logger = logging.getLogger(__name__)


def harvest_dkex_catalog_gaps(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    """Draft DKEX tip pins even when RFQ inventory is empty."""
    before = len(pins)
    try:
        _harvest_leagues(store, pins, seen)
        _harvest_name_aliases(store, pins, seen, skipped)
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest dkex failed")
        skipped.append({"book": "dkex", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info("pipeline gap-fix stage=probe book=dkex pins=%d", len(pins) - before)


def _harvest_leagues(
    store: Any,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return
    by_slug = {
        str(row.league): row
        for row in store.leagues_for(rid)
        if not row.tombstone
    }
    for slug in ENABLED_LEAGUE_SLUGS:
        row = by_slug.get(slug)
        if row is None:
            continue
        _maybe_enable_league(row, pins, seen)


def _maybe_enable_league(
    row: LeagueRow,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    want = venue_token_for_slug(str(row.league), str(row.optic_league_id))
    if not want:
        return
    token = dkex_venue_token(row)
    if _dkex_enabled(row) and token == want:
        return
    pin = enable_dkex_pin(row, want)
    key = ("mapping_league", str(row.league), str(row.optic_league_id))
    if key in seen:
        return
    seen.add(key)
    pins.append(pin)


def _dkex_enabled(row: LeagueRow) -> bool:
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != DKEX_BOOK:
            continue
        return bool(ex.get("enabled", True))
    return False


def _harvest_name_aliases(
    store: Any,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    skipped: list[dict[str, str]],
) -> None:
    path = _catalogue_path()
    if path is None or not path.is_file():
        return
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return
    entities = store.entities_for(rid)
    by_slug = {
        str(row.league): row
        for row in store.leagues_for(rid)
        if not row.tombstone
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        _alias_from_row(rec, by_slug, entities, pins, seen, skipped)


def _catalogue_path() -> Path | None:
    raw = os.environ.get("MAPPING_DATA_DIR", "").strip()
    if not raw:
        return None
    return Path(raw) / "dkex_markets.jsonl"


#: DKEX statAchievement tokens whose participant is a team (moneyline,
#: spread, team total).  Their participants carry the home/away role.
_TEAM_MARKETS = frozenset({"WIN", "MOVY", "TMPTS"})


def _alias_from_row(
    rec: dict[str, Any],
    by_slug: dict[str, LeagueRow],
    entities: list[Any],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    skipped: list[dict[str, str]],
) -> None:
    """Draft a ``(dkex, name)`` alias from one typed catalogue row.

    League, market and the team's display name all come from typed REST
    fields (``sub_topic``, ``stat_achievement``, ``participant_name``);
    the ticker is quoted as evidence only.  A row without typed fields
    (a CSV report row) drafts nothing.
    """
    market = str(rec.get("stat_achievement") or "")
    if market not in _TEAM_MARKETS or not rec.get("participant_id"):
        return
    name = str(rec.get("participant_name") or "").strip()
    if not name:
        return
    slug = _slug_for_venue(dkex_mod.league_token(rec.get("sub_topic")), by_slug)
    if slug is None:
        return
    row = by_slug[slug]
    if _has_name_alias(entities, slug, name):
        return
    bound, skip = _alias_bind(name, entities, slug)
    if bound is None:
        skipped.append({"book": "dkex", "reason": f"{skip}:{name}"})
        return
    key, shown = bound
    symbol = str(rec.get("symbol") or "")
    pin = alias_payload(
        slug,
        key,
        shown,
        match_entity_type_for_row(row),
        [{
            "sportsbook": DKEX_BOOK,
            "alias_kind": "name",
            "alias_value": name,
        }],
        [f"dkex:ticker:{symbol}", f"gap:dkex:{slug}:{name}"],
    )
    ident = (slug, key, name)
    if ident in seen:
        return
    seen.add(ident)
    pins.append(pin)


def _slug_for_venue(venue: str, by_slug: dict[str, LeagueRow]) -> str | None:
    token = venue.strip().upper()
    for slug in ENABLED_LEAGUE_SLUGS:
        row = by_slug.get(slug)
        optic = str(row.optic_league_id) if row is not None else ""
        if venue_token_for_slug(slug, optic) == token:
            return slug
    return None


def _has_name_alias(entities: list[Any], league: str, name: str) -> bool:
    """True when some entity already carries this ``(dkex, name)`` alias."""
    want = name.casefold()
    for ent in entities:
        if str(getattr(ent, "league", "")) != league:
            continue
        for alias in getattr(ent, "aliases", None) or []:
            if (
                str(alias.get("sportsbook") or "") == DKEX_BOOK
                and str(alias.get("alias_kind") or "") == "name"
                and str(alias.get("alias_value") or "").casefold() == want
            ):
                return True
    return False


def _alias_bind(
    name: str,
    entities: list[Any],
    league: str,
) -> tuple[tuple[str, str] | None, str]:
    hits: list[tuple[str, str]] = []
    for ent in entities:
        if str(getattr(ent, "league", "")) != league:
            continue
        shown = str(getattr(ent, "canonical_name", "") or getattr(ent, "canonical_key", ""))
        key = str(ent.canonical_key)
        if names_fit(name, shown, player=False) or city_abbrev_fits(name, shown, key):
            hits.append((key, shown))
    if not hits:
        return None, "no_entity"
    if len(hits) > 1:
        return None, "ambiguous"
    return hits[0], ""
