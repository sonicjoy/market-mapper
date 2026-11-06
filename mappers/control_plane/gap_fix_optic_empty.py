"""Harvest Optic competitor pins missing from the tip (empty-abbr / tennis).

Mapper ``bootstrap_empty_abbrs`` already pins these in-memory for the live
tick. Gap-propose must draft the same class onto Review even when RFQ
inventory is empty — Coverage ``No tip alias`` never produces a true-gap row.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date
from datetime import datetime as dt
from typing import Any

from mappers.alias_kinds import alias_value, is_optic_id, optic_pin
from mappers.canonical_codes import person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_keys import CryptoAssigned, crypto_aliases
from mappers.control_plane.gap_fix_optic_merge import (
    OpticDrafted,
    optic_draft_key,
    register_optic_draft,
)
from mappers.control_plane.gap_fix_slots import EmptyHarvestBudget
from mappers.control_plane.crypto_optic_match import other_competitor_name
from mappers.control_plane.gap_fix_tip import (
    TipLeagueIndex,
    canonical_from_index,
    fold_harvest,
    harvest_cid,
    index_tip_leagues,
)
from mappers.control_plane.gap_fix_verify import alias_in_blocker
from mappers.control_plane.gap_harvest_ttl import (
    load_optic_skips,
    optic_skip_blocks,
    remember_optic_skips,
)
from mappers.control_plane.gap_inventory import _is_close
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.crypto_meta import CLOSE_EVENT_DAYS, crypto_meta_code
from mappers.crypto_meta import harvest_team_ids_from_fix as _default_harvest

logger = logging.getLogger(__name__)

MAX_MISSING_PINS = 40
MAX_PER_LEAGUE = 8
MAX_EXTRA_PER_LEAGUE = 8
_COMBAT = frozenset({"mma", "combat", "ufc", "boxing"})
FixturesFn = Callable[..., list[dict[str, Any]]]
HarvestFn = Callable[[str, int], dict[str, str]]
Tips = dict[str, TipLeagueIndex]


def remember_verify_optic_misses(
    pins: list[dict[str, Any]],
    blockers: list[str],
    now: dt | None = None,
) -> None:
    """TTL-skip Optic ids that failed live 'not in active fixtures'."""
    clock = now or dt.now(UTC)
    failed: dict[str, str] = {}
    for pin in pins:
        oid = _pin_optic_id(pin)
        if oid and any(_inactive_optic_hit(oid, text) for text in blockers):
            failed[oid] = str(pin.get("start") or "")
    if failed:
        remember_optic_skips(failed, clock)


def _pin_optic_id(pin: dict[str, Any]) -> str:
    for alias in pin.get("aliases") or []:
        if is_optic_id(alias):
            return alias_value(alias)
    return ""


def _inactive_optic_hit(oid: str, blocker: str) -> bool:
    return "not in active" in blocker and alias_in_blocker(oid, blocker)


def harvest_catalogue_days(lg: Any) -> int:
    """Full FIX catalogue only for small combat sports; else the close window.

    ``days=0`` is O(all historical names) and OOMs tennis. Close
    ``meta_event_date`` rows still match when last publish is stale.
    """
    sport = str(getattr(lg, "sport", "") or "").lower()
    league = str(getattr(lg, "league", "") or "").lower()
    if sport in _COMBAT or any(part in league for part in _COMBAT):
        return 0
    return CLOSE_EVENT_DAYS


def harvest_missing_optic_competitors(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: FixturesFn | None = None,
    optic_drafted: OpticDrafted | None = None,
    harvest_fn: HarvestFn | None = None,
    crypto_assigned: CryptoAssigned | None = None,
    today: date | None = None,
    tips: Tips | None = None,
    empty_budget: EmptyHarvestBudget | None = None,
) -> None:
    """Draft Optic ids for close fixture sides that are not on the activated tip."""
    drafted = {} if optic_drafted is None else optic_drafted
    assigned = crypto_assigned if crypto_assigned is not None else set()
    before = len(pins)
    day = today or dt.now(tz=UTC).date()
    started = time.monotonic()
    try:
        leagues = _optic_leagues(store)
        indexed = tips if tips is not None else index_tip_leagues(
            store, {str(lg.league) for lg in leagues},
        )
        pin_cap = MAX_MISSING_PINS
        if empty_budget is not None:
            pin_cap = min(pin_cap, empty_budget.remaining())
        candidates = _candidates(leagues, fixtures_fn, harvest_fn, day, indexed)
        _apply_candidates(
            candidates, pins, skipped, seen, drafted, assigned, indexed,
            max_pins=pin_cap,
        )
        if empty_budget is not None:
            empty_budget.record(len(pins) - before)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest optic_missing failed")
        skipped.append({"book": "optic_missing", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info(
        "pipeline gap-fix stage=probe book=optic_missing pins=%d sec=%.1f",
        len(pins) - before,
        time.monotonic() - started,
    )


def _candidates(
    leagues: list[Any],
    fixtures_fn: FixturesFn | None,
    harvest_fn: HarvestFn | None,
    today: date,
    tips: Tips,
) -> list[dict[str, Any]]:
    """Close extra-league sides first, then close primary. Far fixtures stay out."""
    rows: list[dict[str, Any]] = []
    harvest_by_league: dict[str, dict[str, str]] = {}
    for lg in leagues:
        league = str(lg.league)
        tip = tips.get(league, TipLeagueIndex())
        league_rows = _league_candidates(lg, fixtures_fn, today, tip)
        if league_rows and league not in harvest_by_league:
            harvest_by_league[league] = _load_league_harvest(
                lg, harvest_fn, fixtures_fn,
            )
        harvest = harvest_by_league.get(league, {})
        for row in league_rows:
            row["harvest"] = harvest
        rows.extend(league_rows)
    rows.sort(
        key=lambda row: (
            _candidate_tier(row),
            row["start"],
            row["league"],
            row["oid"],
        ),
    )
    return rows


def _candidate_tier(row: dict[str, Any]) -> int:
    """0=close extra, 1=close primary, 2=far extra, 3=far primary."""
    close = bool(row.get("close"))
    extra = bool(row.get("is_extra"))
    if close and extra:
        return 0
    if close and not extra:
        return 1
    if not close and extra:
        return 2
    return 3


def _load_league_harvest(
    lg: Any,
    harvest_fn: HarvestFn | None,
    fixtures_fn: FixturesFn | None,
) -> dict[str, str]:
    """Full FIX catalogue for a tip league (close events may lag publish_time)."""
    if harvest_fn is None and fixtures_fn is not None:
        return {}
    meta = crypto_meta_code(lg)
    if not meta:
        return {}
    try:
        days = harvest_catalogue_days(lg)
        if harvest_fn is not None:
            return harvest_fn(meta, days)
        return _default_harvest(meta, days=days)
    except Exception as exc:  # noqa: BLE001 — optic harvest still runs
        logger.warning("optic missing harvest %s FIX ids: %s", lg.league, exc)
        return {}


def _optic_leagues(store: Any) -> list[Any]:
    """Enabled tip leagues that have an Optic league id."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    out: list[Any] = []
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        if str(lg.optic_league_id or "").strip():
            out.append(lg)
    return out


def _league_candidates(
    lg: Any,
    fixtures_fn: FixturesFn | None,
    today: date,
    tip: TipLeagueIndex,
) -> list[dict[str, Any]]:
    """Missing sides for one league's close Optic fixtures."""
    league = str(lg.league)
    primary = str(lg.optic_league_id or "").strip()
    extra_ids = {
        str(x).strip()
        for x in (lg.extra_optic_league_ids or [])
        if str(x).strip()
    }
    entity_type = match_entity_type_for_row(lg)
    player = person_league(league)
    out: list[dict[str, Any]] = []
    for game in _league_games(lg, fixtures_fn):
        close = _game_is_close(game, today)
        if not close:
            continue
        start = str(game.get("start_date") or "9999")
        optic_league = _game_league_id(game)
        is_extra = optic_league in extra_ids and optic_league != primary
        for oid, name, abbr in _singles(game):
            if oid in tip.optic:
                continue
            if abbr and not player:
                continue
            out.append({
                "league": league, "oid": oid, "name": name, "abbr": abbr,
                "game": game, "start": start, "entity_type": entity_type,
                "player": player,
                "optic_league": optic_league, "is_extra": is_extra, "close": close,
            })
    return out


def _league_games(lg: Any, fixtures_fn: FixturesFn | None) -> list[dict[str, Any]]:
    """Optic fixtures stamped for this league id (injected stubs must stamp)."""
    horizon = optic_horizon_hours(lg)
    extra = [str(x).strip() for x in (lg.extra_optic_league_ids or [])]
    ids = [str(lg.optic_league_id or "").strip(), *extra]
    games: list[dict[str, Any]] = []
    for oid in ids:
        if not oid:
            continue
        try:
            raw = cached_optic_fixtures(
                oid, horizon_hours=horizon, fetch_fn=fixtures_fn,
            )
        except Exception as exc:  # noqa: BLE001 — missing key / network
            logger.warning("optic missing harvest %s %s: %s", lg.league, oid, exc)
            continue
        games.extend(g for g in raw if _game_league_id(g) == oid)
    return games


def _game_league_id(game: dict[str, Any]) -> str:
    """Optic league id on the fixture, or empty when the stub omitted it."""
    league = game.get("league") or {}
    if isinstance(league, dict):
        return str(league.get("id") or "").strip()
    return str(league).strip()


def _game_is_close(game: dict[str, Any], today: date) -> bool:
    kick = _kick_date(str(game.get("start_date") or ""))
    return _is_close(kick, today)


def _kick_date(raw: str) -> date | None:
    text = raw.strip()
    if not text or text == "9999":
        return None
    try:
        return dt.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError:
        return None


def _singles(game: dict[str, Any]) -> list[tuple[str, str, str]]:
    """id, name, abbr for singles sides (skip doubles)."""
    out: list[tuple[str, str, str]] = []
    for key in ("home_competitors", "away_competitors"):
        people = game.get(key) or []
        if not isinstance(people, list) or len(people) != 1:
            continue
        row = people[0] if isinstance(people[0], dict) else {}
        oid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        abbr = str(row.get("abbreviation") or "").strip()
        if oid and name:
            out.append((oid, name, abbr))
    return out


def _apply_candidates(
    candidates: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    optic_drafted: OpticDrafted | None,
    crypto_assigned: CryptoAssigned,
    tips: Tips,
    *,
    max_pins: int = MAX_MISSING_PINS,
) -> None:
    """Draft until the Review cap, diversifying across leagues."""
    taken_primary: dict[str, int] = {}
    taken_extra: dict[str, int] = {}
    capped_primary: set[str] = set()
    capped_extra: set[str] = set()
    used_by_league: dict[str, set[str]] = {}
    folded_by_league: dict[str, dict[str, str]] = {}
    added = 0
    skips = load_optic_skips()
    now = dt.now(UTC)
    failed: dict[str, str] = {}
    for row in candidates:
        if added >= max_pins:
            break
        if _apply_one_candidate(
            row, pins, skipped, seen, optic_drafted, crypto_assigned, tips,
            taken_primary, taken_extra, capped_primary, capped_extra,
            used_by_league, folded_by_league, skips, now, failed,
        ):
            added += 1
    if failed:
        remember_optic_skips(failed, now)


def _apply_one_candidate(
    row: dict[str, Any], pins: list[dict[str, Any]],
    skipped: list[dict[str, str]], seen: set[tuple[str, str, str]],
    optic_drafted: OpticDrafted | None, crypto_assigned: CryptoAssigned,
    tips: Tips, taken_primary: dict[str, int], taken_extra: dict[str, int],
    capped_primary: set[str], capped_extra: set[str],
    used_by_league: dict[str, set[str]], folded_by_league: dict[str, dict[str, str]],
    skips: Any, now: dt, failed: dict[str, str],
) -> bool:
    """Draft one Optic miss. True when a pin was accepted."""
    league = str(row["league"])
    oid = str(row["oid"])
    if optic_skip_blocks(oid, str(row["start"]), skips, now):
        return False
    if _candidate_over_cap(
        row, league, taken_primary, taken_extra, skipped,
        capped_primary, capped_extra,
    ):
        return False
    tip = tips.get(league, TipLeagueIndex())
    used = used_by_league.setdefault(league, set(tip.used))
    before = len(skipped)
    if optic_draft_key(optic_drafted, league, oid):
        return False
    raw_harvest = row.get("harvest")
    harvest: dict[str, str] = raw_harvest if isinstance(raw_harvest, dict) else {}
    folded = folded_by_league.setdefault(league, fold_harvest(harvest))
    pin = _draft_pin(
        row, used, skipped, optic_drafted, crypto_assigned, tip, folded,
    )
    if pin is None:
        if len(skipped) > before:
            failed[oid] = str(row["start"])
        return False
    return _accept_drafted_pin(
        row, pin, league, oid, seen, used, optic_drafted,
        taken_primary, taken_extra, pins,
    )


def _candidate_over_cap(
    row: dict[str, Any],
    league: str,
    taken_primary: dict[str, int],
    taken_extra: dict[str, int],
    skipped: list[dict[str, str]],
    capped_primary: set[str],
    capped_extra: set[str],
) -> bool:
    """True when this league has hit its primary or extra budget."""
    oid = str(row["oid"])
    if row.get("is_extra"):
        if taken_extra.get(league, 0) < MAX_EXTRA_PER_LEAGUE:
            return False
        if league not in capped_extra:
            capped_extra.add(league)
            skipped.append({
                "league": league, "key": oid, "reason": "extra_league_cap",
            })
        return True
    if taken_primary.get(league, 0) < MAX_PER_LEAGUE:
        return False
    if league not in capped_primary:
        capped_primary.add(league)
        skipped.append({"league": league, "key": oid, "reason": "league_cap"})
    return True


def _accept_drafted_pin(
    row: dict[str, Any],
    pin: dict[str, Any],
    league: str,
    oid: str,
    seen: set[tuple[str, str, str]],
    used: set[str],
    optic_drafted: OpticDrafted | None,
    taken_primary: dict[str, int],
    taken_extra: dict[str, int],
    pins: list[dict[str, Any]],
) -> bool:
    """Record a drafted pin when it is new for this harvest pass."""
    ident = (league, str(pin["canonical_key"]), oid)
    if ident in seen:
        return False
    seen.add(ident)
    used.add(str(pin["canonical_key"]).upper())
    register_optic_draft(optic_drafted, league, oid, str(pin["canonical_key"]))
    if row.get("is_extra"):
        taken_extra[league] = taken_extra.get(league, 0) + 1
    else:
        taken_primary[league] = taken_primary.get(league, 0) + 1
    pins.append(pin)
    return True


def _draft_pin(
    row: dict[str, Any],
    used: set[str],
    skipped: list[dict[str, str]],
    optic_drafted: OpticDrafted | None,
    crypto_assigned: CryptoAssigned,
    tip: TipLeagueIndex,
    folded: dict[str, str],
) -> dict[str, Any] | None:
    """One Optic external_id pin, or None when the tip already has this id."""
    league = str(row["league"])
    oid = str(row["oid"])
    name = str(row["name"])
    player = bool(row["player"])
    if oid in tip.optic:
        return None
    key = canonical_from_index(
        tip, league, oid, name, used, player=player, optic_drafted=optic_drafted,
    )
    if not key:
        skipped.append({"league": league, "key": oid, "reason": "no_code"})
        return None
    if oid in tip.optic_on.get(key, set()):
        return None
    entity_type = tip.types.get(key) or str(row["entity_type"])
    raw_harvest = row.get("harvest")
    harvest: dict[str, str] = raw_harvest if isinstance(raw_harvest, dict) else {}
    other = other_competitor_name(row["game"], oid)
    cid = harvest_cid(
        harvest, name, player=player, folded=folded, optic_counterpart=other,
    )
    is_new = key not in tip.keys
    attach_crypto = bool(
        is_new and cid and cid not in tip.crypto
        and (league, cid) not in crypto_assigned,
    )
    if attach_crypto:
        aliases = crypto_aliases(cid, oid, include_optic=True)
        crypto_assigned.add((league, cid))
    else:
        aliases = [optic_pin(oid)]
    refs = _identity_refs(oid, name, str(row.get("abbr") or ""), row["game"])
    if attach_crypto:
        refs.append(f"crypto_id:{cid}")
        refs.append(f"crypto:name:{name}")
    pin = alias_payload(league, key, name, entity_type, aliases, refs)
    start = str(row.get("start") or "")
    if start and start != "9999":
        pin["start"] = start
    return pin


def _identity_refs(oid: str, name: str, abbr: str, game: Any) -> list[str]:
    """Competitor, name, abbr, and fixture — no exchange questions."""
    refs = [optic_competitor_ref(oid, name), optic_fixture_ref(game)]
    if name:
        refs.append(f"optic:name:{name}")
    if abbr:
        refs.append(f"optic:abbr:{abbr}")
    return [ref for ref in refs if ref]
