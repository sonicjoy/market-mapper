"""Harvest Optic-abbr book codes when the tip canonical is a longer key.

Mapper ``optic_abbr_bind`` already joins Poly USA / PX shorts
(``BBR``, ``MIL``) onto fixture canonicals (``BRF8``, ``MFI2``). Gap-propose
must draft the same class onto Review even when RFQ inventory is empty —
Coverage otherwise shows no book pin on the long key.

Walks only club leagues and close fixtures. Tip lookups are one coalesce,
not a full-entity scan per competitor (that hung CronJobs for hours).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from mappers.alias_kinds import is_optic_id
from mappers.canonical_codes import names_fit, person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_slots import EmptyHarvestBudget
from mappers.control_plane.gap_inventory import _is_close
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK

logger = logging.getLogger(__name__)

_BOOKS = (POLY_USA_BOOK, "px")
_CODE_KINDS = frozenset({"code", ""})
FixturesFn = Callable[..., list[dict[str, Any]]]


@dataclass
class _LeagueTip:
    """Per-league tip indexes so harvest does not rescan entities per side."""

    optic_key: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    pins: dict[str, set[tuple[str, str, str]]] = field(
        default_factory=lambda: defaultdict(set),
    )
    code_owners: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set),
    )


def harvest_optic_abbr_codes(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    fixtures_fn: FixturesFn | None = None,
    empty_budget: EmptyHarvestBudget | None = None,
) -> None:
    """Pin unique Optic abbrs as book codes onto a longer canonical."""
    before = len(pins)
    started = time.monotonic()
    try:
        leagues = _leagues(store)
        tips = _index_tips(store, {str(lg.league) for lg in leagues})
        for lg in leagues:
            if empty_budget is not None and empty_budget.full():
                break
            league_before = len(pins)
            _harvest_league(
                store, lg, tips.get(str(lg.league), _LeagueTip()), pins, skipped, seen, fixtures_fn,
            )
            if empty_budget is not None:
                empty_budget.record(len(pins) - league_before)
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest optic_abbr_code failed")
        skipped.append({"book": "optic_abbr_code", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info(
        "pipeline gap-fix stage=probe book=optic_abbr_code pins=%d sec=%.1f",
        len(pins) - before,
        time.monotonic() - started,
    )


def collect_optic_abbr_code_pins(
    store: Any,
    league: str,
    games: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    books: tuple[str, ...] = _BOOKS,
    entity_type: str = "team",
    tip: _LeagueTip | None = None,
) -> None:
    """Draft one pin per Optic side whose abbr differs from the tip canonical."""
    indexed = tip if tip is not None else _index_tips(store, {league}).get(league, _LeagueTip())
    shared = _shared_abbrs(games)
    for game in games:
        for side_key in ("home_competitors", "away_competitors"):
            oid, name, abbr = _side_triple(game, side_key)
            _draft_side(
                store, league, indexed, oid, name, abbr, game, shared, books,
                pins, skipped, seen, entity_type=entity_type,
            )


def _harvest_league(
    store: Any,
    lg: Any,
    tip: _LeagueTip,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: FixturesFn | None,
) -> None:
    """One enabled tip league: close Optic fixtures vs longer canonicals."""
    books = _enabled_books(lg)
    if not books:
        return
    started = time.monotonic()
    games = _close_games(_league_games(lg, fixtures_fn))
    if not games:
        return
    before = len(pins)
    collect_optic_abbr_code_pins(
        store, str(lg.league), games, pins, skipped, seen,
        books=books,
        entity_type=match_entity_type_for_row(lg),
        tip=tip,
    )
    elapsed = time.monotonic() - started
    if elapsed >= 0.5 or len(pins) > before:
        logger.info(
            "pipeline gap-fix stage=probe book=optic_abbr_code league=%s games=%d pins=%d sec=%.1f",
            lg.league, len(games), len(pins) - before, elapsed,
        )


def _draft_side(
    store: Any,
    league: str,
    tip: _LeagueTip,
    oid: str,
    name: str,
    abbr: str,
    game: dict[str, Any],
    shared: set[str],
    books: tuple[str, ...],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    entity_type: str,
) -> None:
    """Draft missing book codes for one Optic competitor, or skip."""
    if not oid or not abbr:
        return
    if abbr.casefold() in shared:
        skipped.append({"league": league, "key": abbr, "reason": "shared_optic_abbr"})
        return
    key = tip.optic_key.get(oid, "")
    if not key or abbr.casefold() == key.casefold():
        return
    ident = (league, key, abbr.upper())
    if ident in seen:
        return
    if _code_collision(tip, key, abbr, books):
        skipped.append({"league": league, "key": abbr, "reason": "collision"})
        return
    existing = tip.names.get(key, "")
    if existing and existing != key and not names_fit(name, existing, player=False):
        shown = name or existing
    else:
        shown = existing if existing and existing != key else (name or abbr)
    aliases = _aliases_for(store, league, tip, key, abbr, books)
    if not aliases:
        return
    seen.add(ident)
    kind = tip.types.get(key) or entity_type
    pins.append(alias_payload(
        league, key, shown, kind, aliases, _refs(oid, name, abbr, game),
    ))


def _aliases_for(
    store: Any,
    league: str,
    tip: _LeagueTip,
    key: str,
    abbr: str,
    books: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Book-code aliases the owner does not already carry."""
    owned = tip.pins.get(key, set())
    out: list[dict[str, Any]] = []
    for book in books:
        if _code_held(owned, book, abbr):
            continue
        out.append({"sportsbook": book, "alias_kind": "code", "alias_value": abbr})
    return out


def _code_collision(
    tip: _LeagueTip, key: str, abbr: str, books: tuple[str, ...],
) -> bool:
    """True when another canonical already claims this abbr on a target book."""
    want = abbr.upper()
    for book in books:
        owners = tip.code_owners.get((book, want), set())
        if any(owner != key for owner in owners):
            return True
    return False


def _code_held(owned: set[tuple[str, str, str]], book: str, abbr: str) -> bool:
    """True when this canonical already has ``abbr`` as a code on ``book``."""
    want = abbr.upper()
    return (book, "code", want) in owned or (book, "", want) in owned


def _index_tips(store: Any, leagues: set[str]) -> dict[str, _LeagueTip]:
    """One entities_for coalesce, split by league."""
    rid = getattr(store, "current_rule_set_id", None)
    out: dict[str, _LeagueTip] = {league: _LeagueTip() for league in leagues}
    if not rid or not leagues or not hasattr(store, "entities_for"):
        return out
    for ent in store.entities_for(rid):
        league = str(ent.league or "")
        tip = out.get(league)
        if tip is None or ent.tombstone:
            continue
        key = str(ent.canonical_key or "")
        if not key:
            continue
        tip.names[key] = str(ent.canonical_name or key)
        if ent.entity_type:
            tip.types[key] = str(ent.entity_type)
        for alias in ent.aliases or []:
            _index_alias(tip, key, alias)
    return out


def _index_alias(tip: _LeagueTip, key: str, alias: dict[str, Any]) -> None:
    """Record one tip alias onto optic/code indexes."""
    book = str(alias.get("sportsbook") or "").strip().lower()
    kind = str(alias.get("alias_kind") or "").strip().lower()
    value = str(alias.get("alias_value") or "").strip()
    if not book or not value:
        return
    if is_optic_id(alias):
        tip.optic_key[value] = key
    token = value.upper() if kind in _CODE_KINDS else value
    tip.pins[key].add((book, kind, token))
    if kind in _CODE_KINDS:
        tip.code_owners[(book, token)].add(key)


def _shared_abbrs(games: list[dict[str, Any]]) -> set[str]:
    """Optic abbreviations used by more than one competitor id."""
    by_abbr: dict[str, set[str]] = defaultdict(set)
    for game in games:
        for side_key in ("home_competitors", "away_competitors"):
            oid, _name, abbr = _side_triple(game, side_key)
            if oid and abbr:
                by_abbr[abbr.casefold()].add(oid)
    return {abbr for abbr, ids in by_abbr.items() if len(ids) > 1}


def _enabled_books(lg: Any) -> tuple[str, ...]:
    """Poly USA / PX books enabled on this tip league."""
    out: list[str] = []
    seen: set[str] = set()
    for ex in lg.exchanges or []:
        book = str(ex.get("sportsbook") or "").lower()
        if book not in _BOOKS or book in seen:
            continue
        if ex.get("enabled") is False:
            continue
        seen.add(book)
        out.append(book)
    return tuple(out)


def _leagues(store: Any) -> list[Any]:
    """Enabled club tip leagues that have Optic and a target book."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    out: list[Any] = []
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        if person_league(str(lg.league)):
            continue
        if not str(lg.optic_league_id or "").strip():
            continue
        if _enabled_books(lg):
            out.append(lg)
    return out


def _league_games(lg: Any, fixtures_fn: FixturesFn | None) -> list[dict[str, Any]]:
    """Optic fixtures for one league, using the mapper horizon (warm-cache hit)."""
    horizon = optic_horizon_hours(lg)
    extra = [str(x).strip() for x in (lg.extra_optic_league_ids or [])]
    ids = [str(lg.optic_league_id or "").strip(), *extra]
    games: list[dict[str, Any]] = []
    for oid in ids:
        if not oid:
            continue
        try:
            games.extend(cached_optic_fixtures(
                oid, horizon_hours=horizon, fetch_fn=fixtures_fn,
            ))
        except Exception as exc:  # noqa: BLE001 — missing key / network
            logger.warning("optic abbr code harvest %s %s: %s", lg.league, oid, exc)
    return games


def _close_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kickoff within CLOSE_MAX_DAYS — full-horizon walks stall harvest."""
    today = datetime.now(tz=UTC).date()
    out: list[dict[str, Any]] = []
    for game in games:
        kick = _kick_date(str(game.get("start_date") or ""))
        if _is_close(kick, today):
            out.append(game)
    return out


def _kick_date(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError:
        return None


def _side_triple(game: dict[str, Any], key: str) -> tuple[str, str, str]:
    """id, name, abbreviation for the first competitor on one side."""
    row = (game.get(key) or [{}])[0]
    if not isinstance(row, dict):
        return "", "", ""
    return (
        str(row.get("id") or ""),
        str(row.get("name") or ""),
        str(row.get("abbreviation") or "").strip(),
    )


def _refs(oid: str, name: str, abbr: str, game: dict[str, Any]) -> list[str]:
    """Optic competitor / fixture / abbr evidence."""
    refs = [
        optic_competitor_ref(oid, name),
        optic_fixture_ref(game),
        f"optic:abbr:{abbr}",
    ]
    return [ref for ref in refs if ref]
