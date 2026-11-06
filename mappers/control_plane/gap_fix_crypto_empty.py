"""Harvest crypto_id pins for close Optic fixtures when RFQ inventory is empty.

Gap-propose's RFQ walk only sees demanding / close *symbols*. Coverage UFC
cards with Optic+Kalshi and no crypto.com alias never produce a true-gap row,
so a failed demanding check used to skip the fighters entirely. This sweeper
drafts the same class Chat ``sweep_crypto_ids`` stages — restricted to
kickoffs inside ``CLOSE_MAX_DAYS``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from mappers.alias_kinds import is_crypto_id, is_optic_id
from mappers.canonical_codes import fallback_code, person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_keys import CryptoAssigned, crypto_aliases
from mappers.control_plane.gap_fix_optic_empty import (
    _league_games,
    _load_league_harvest,
    _optic_leagues,
    _singles,
    harvest_catalogue_days,
)
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted, optic_draft_key
from mappers.control_plane.gap_fix_slots import EmptyHarvestBudget
from mappers.control_plane.gap_fix_tip import (
    TipLeagueIndex,
    fold_harvest,
    harvest_cid,
    index_entity_rows,
    name_hit_indexed,
)
from mappers.control_plane.crypto_optic_match import other_competitor_name
from mappers.control_plane.gap_inventory import MAX_EVENTS, _is_close
from mappers.control_plane.sweep_crypto_ids import run_sweep_crypto_ids
from mappers.crypto_meta import crypto_meta_code

logger = logging.getLogger(__name__)

# One NFL week is ~16 games; keep a league from filling the empty-harvest budget.
MAX_PER_LEAGUE = 12
_COMBAT = frozenset({"mma", "combat", "ufc", "boxing"})
FixturesFn = Callable[..., list[dict[str, Any]]]
HarvestFn = Callable[[str, int], dict[str, str]]


def harvest_missing_crypto_ids(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    fixtures_fn: FixturesFn | None = None,
    harvest_fn: HarvestFn | None = None,
    today: date | None = None,
    optic_drafted: OpticDrafted | None = None,
    crypto_assigned: CryptoAssigned | None = None,
    tips: dict[str, TipLeagueIndex] | None = None,
    empty_budget: EmptyHarvestBudget | None = None,
) -> None:
    """Draft crypto_id pins for close fixture sides missing from the tip."""
    if harvest_fn is None and fixtures_fn is not None:
        return
    before = len(pins)
    day = today or datetime.now(tz=UTC).date()
    assigned = crypto_assigned if crypto_assigned is not None else set()
    total_cap = MAX_EVENTS if empty_budget is None else empty_budget.remaining()
    added = 0
    try:
        leagues = _crypto_leagues(store)
        rid = getattr(store, "current_rule_set_id", None)
        ents = (
            list(store.entities_for(rid))
            if rid and hasattr(store, "entities_for") else []
        )
        indexed = tips if tips is not None else index_entity_rows(
            ents, {str(lg.league) for lg in leagues},
        )
        for lg in leagues:
            if added >= total_cap:
                break
            added += _harvest_league(
                store, lg, pins, seen,
                fixtures_fn=fixtures_fn, harvest_fn=harvest_fn, today=day,
                remaining=total_cap - added,
                optic_drafted=optic_drafted,
                crypto_assigned=assigned,
                tip=indexed.get(str(lg.league), TipLeagueIndex()),
                entities=ents,
            )
        if empty_budget is not None:
            empty_budget.record(len(pins) - before)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest crypto_missing failed")
        skipped.append({"book": "crypto_missing", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info(
        "pipeline gap-fix stage=probe book=crypto_missing pins=%d",
        len(pins) - before,
    )


def _crypto_leagues(store: Any) -> list[Any]:
    """Enabled Optic+crypto leagues; combat first so UFC is not crowded out."""
    rows = [lg for lg in _optic_leagues(store) if crypto_meta_code(lg)]
    rows.sort(key=lambda lg: (0 if _is_combat(lg) else 1, str(lg.league)))
    return rows


def _is_combat(lg: Any) -> bool:
    """True for UFC / boxing / MMA tip rows."""
    sport = str(getattr(lg, "sport", "") or "").lower()
    league = str(getattr(lg, "league", "") or "").lower()
    return sport in _COMBAT or any(part in league for part in _COMBAT)


def _harvest_league(
    store: Any,
    lg: Any,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    fixtures_fn: FixturesFn | None,
    harvest_fn: HarvestFn | None,
    today: date,
    remaining: int,
    optic_drafted: OpticDrafted | None,
    crypto_assigned: CryptoAssigned,
    tip: TipLeagueIndex,
    entities: list[Any],
) -> int:
    """Sweep FIX ids for one league and keep pins on close Optic sides."""
    close = _close_sides(lg, fixtures_fn, today, optic_drafted, tip)
    if not close or remaining <= 0:
        return 0
    harvest = _load_league_harvest(lg, harvest_fn, fixtures_fn)
    limit = min(MAX_PER_LEAGUE, remaining)
    taken = _draft_sweep_pins(
        store, lg, close, pins, seen, crypto_assigned,
        fixtures_fn=fixtures_fn, harvest_fn=harvest_fn, today=today, limit=limit,
        tip=tip, entities=entities,
    )
    return taken + _draft_provisional_crypto(
        lg, close, harvest, pins, seen, crypto_assigned,
        remaining=limit - taken, tip=tip,
    )


def _draft_sweep_pins(
    store: Any,
    lg: Any,
    close: dict[str, dict[str, Any]],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    crypto_assigned: CryptoAssigned,
    *,
    fixtures_fn: FixturesFn | None,
    harvest_fn: HarvestFn | None,
    today: date,
    limit: int,
    tip: TipLeagueIndex,
    entities: list[Any],
) -> int:
    """Append sweep suggestions that land on close fixture sides."""
    result = run_sweep_crypto_ids(
        store,
        str(lg.league),
        days=harvest_catalogue_days(lg),
        cap=MAX_PER_LEAGUE,
        harvest_fn=harvest_fn,
        fixtures_fn=_close_fixtures_fn(fixtures_fn, today),
        keys=set(close),
        entities=entities,
    )
    taken = 0
    default_type = match_entity_type_for_row(lg)
    for suggestion in result.get("suggestions") or []:
        if taken >= limit:
            break
        pin = _pin_from_suggestion(suggestion, close, seen, tip, default_type)
        if pin is None:
            continue
        ident = (
            str(pin["league"]),
            str(pin["canonical_key"]),
            str(pin["aliases"][0]["alias_value"]),
        )
        if ident in seen:
            continue
        seen.add(ident)
        pins.append(pin)
        crypto_assigned.add((str(pin["league"]), ident[2]))
        taken += 1
    return taken


def _close_sides(
    lg: Any,
    fixtures_fn: FixturesFn | None,
    today: date,
    optic_drafted: OpticDrafted | None,
    tip: TipLeagueIndex,
) -> dict[str, dict[str, Any]]:
    """canonical_key → close fixture side (oid, name, game)."""
    league = str(lg.league)
    player = person_league(league)
    used = set(tip.used)
    out: dict[str, dict[str, Any]] = {}
    for game in _league_games(lg, fixtures_fn):
        if not _game_is_close(game, today):
            continue
        for oid, name, _abbr in _singles(game):
            key = _side_key(tip, league, oid, name, used, player, optic_drafted)
            if not key or key in out:
                continue
            used.add(key.upper())
            out[key] = {"oid": oid, "name": name, "game": game}
    return out


def _side_key(
    tip: TipLeagueIndex,
    league: str,
    oid: str,
    name: str,
    used: set[str],
    player: bool,
    optic_drafted: OpticDrafted | None,
) -> str:
    """Reuse optic/name match, else invent. Empty when the name cannot code."""
    key = tip.optic.get(oid) or name_hit_indexed(tip, name, player=player)
    if key:
        return key
    drafted = optic_draft_key(optic_drafted, league, oid)
    if drafted:
        return drafted
    try:
        return fallback_code(name, used, oid)
    except ValueError:
        return ""


def _draft_provisional_crypto(
    lg: Any,
    close: dict[str, dict[str, Any]],
    harvest: dict[str, str],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    crypto_assigned: CryptoAssigned,
    *,
    remaining: int,
    tip: TipLeagueIndex,
) -> int:
    """Draft optic+crypto pins for close sides not yet on the tip."""
    if remaining <= 0 or not harvest:
        return 0
    league = str(lg.league)
    player = person_league(league)
    folded = fold_harvest(harvest)
    default_type = match_entity_type_for_row(lg)
    taken = 0
    for key, side in close.items():
        if taken >= remaining:
            break
        if _append_provisional_pin(
            league, key, side, harvest, folded, player, pins, seen,
            crypto_assigned, tip, default_type,
        ):
            taken += 1
    return taken


def _append_provisional_pin(
    league: str,
    key: str,
    side: dict[str, Any],
    harvest: dict[str, str],
    folded: dict[str, str],
    player: bool,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    crypto_assigned: CryptoAssigned,
    tip: TipLeagueIndex,
    default_type: str,
) -> bool:
    """True when a new-canonical optic+crypto pin was appended."""
    if key in tip.keys:
        return False
    oid = str(side["oid"])
    name = str(side["name"])
    other = other_competitor_name(side["game"], oid)
    cid = harvest_cid(
        harvest, name, player=player, folded=folded, optic_counterpart=other,
    )
    if not cid or cid in tip.crypto or (league, cid) in crypto_assigned:
        return False
    if _pin_already_covers(pins, league, key, cid, oid):
        return False
    ident = (league, key, cid)
    if ident in seen:
        return False
    pin = alias_payload(
        league, key, name, tip.types.get(key) or default_type,
        crypto_aliases(cid, oid, include_optic=True),
        _evidence(cid, name, side),
    )
    start = str(side["game"].get("start_date") or "")
    if start:
        pin["start"] = start
    seen.add(ident)
    crypto_assigned.add((league, cid))
    pins.append(pin)
    return True


def _pin_already_covers(
    pins: list[dict[str, Any]],
    league: str,
    key: str,
    cid: str,
    oid: str,
) -> bool:
    """True when this harvest pass already drafted crypto for the side."""
    for pin in pins:
        if str(pin.get("league") or "") != league:
            continue
        if str(pin.get("canonical_key") or "") != key:
            continue
        aliases = pin.get("aliases") or []
        has_crypto = any(is_crypto_id(alias, cid) for alias in aliases)
        has_optic = any(is_optic_id(alias, oid) for alias in aliases)
        if has_crypto and has_optic:
            return True
        if has_crypto:
            return True
    return False


def _close_fixtures_fn(
    fixtures_fn: FixturesFn | None, today: date,
) -> FixturesFn | None:
    """Keep Optic name-index on close kickoffs only."""
    if fixtures_fn is None:
        return None

    def _close_only(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [game for game in fixtures_fn(*args, **kwargs) if _game_is_close(game, today)]

    return _close_only


def _game_is_close(game: dict[str, Any], today: date) -> bool:
    """True when the fixture kickoff is today or within CLOSE_MAX_DAYS."""
    kick = _kick_date(str(game.get("start_date") or ""))
    return _is_close(kick, today)


def _kick_date(raw: str) -> date | None:
    """Parse an Optic start_date into a UTC date, or None."""
    text = raw.strip()
    if not text or text == "9999":
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError:
        return None


def _pin_from_suggestion(
    suggestion: dict[str, Any],
    close: dict[str, dict[str, Any]],
    seen: set[tuple[str, str, str]],
    tip: TipLeagueIndex,
    default_type: str,
) -> dict[str, Any] | None:
    """Harvest pin when the swept entity is on a close fixture."""
    payload = dict(suggestion.get("payload") or {})
    aliases = list(payload.get("aliases") or [])
    key = str(payload.get("canonical_key") or "")
    league = str(payload.get("league") or "")
    if not aliases or not key or key not in close:
        return None
    cid = str(aliases[0].get("alias_value") or "").strip()
    if not cid or key in tip.crypto_owner.get(cid, set()):
        return None
    ident = (league, key, cid)
    if ident in seen:
        return None
    side = close[key]
    name = str(payload.get("canonical_name") or side["name"] or key)
    entity_type = str(payload.get("entity_type") or "")
    if entity_type not in ("team", "player", "fighter"):
        entity_type = tip.types.get(key) or default_type
    pin = alias_payload(
        league,
        key,
        name,
        entity_type,
        aliases,
        _evidence(cid, name, side),
    )
    start = str(side["game"].get("start_date") or "")
    if start:
        pin["start"] = start
    return pin


def _evidence(cid: str, name: str, side: dict[str, Any]) -> list[str]:
    """Catalogue id plus the close Optic side that justified the pin."""
    refs = [
        f"crypto_id:{cid}",
        f"crypto:name:{name}",
        optic_competitor_ref(str(side["oid"]), str(side["name"])),
        optic_fixture_ref(side["game"]),
    ]
    return [ref for ref in refs if ref]
