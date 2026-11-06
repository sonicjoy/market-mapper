"""Harvest PX abbreviation pins when Optic fixture names uniquely match.

Mapper ``pin_px_name_miss`` already rewrites the live tick in-memory.
Gap-propose must draft the same class onto Review even when RFQ inventory
is empty — a missing PX 3-letter abbr (HUL vs HCA7) never produces an RFQ
true-gap row, it aborts the league instead.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_client, ro_query
from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import names_fit, person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_onboard import stamp_gap_harvest_pin
from mappers.control_plane.gap_fix_tip import TipLeagueIndex, index_tip_leagues
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.px_name_bind import (
    NamedSide,
    aligned_pairs,
    planned_px_aliases,
    unique_optic_sides,
)
from mappers.shared import to_date_str, to_et_str

logger = logging.getLogger(__name__)

PxEventsFn = Callable[[str], list[dict[str, Any]]]
FixturesFn = Callable[..., list[dict[str, Any]]]


def probe_wired_px_rfq(
    store: Any,
    row: Any,
    raw: dict[str, Any],
    gap_key: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: FixturesFn | None,
) -> None:
    """Draft the shared PX name bind for one RFQ key whose tournament is already on the tip."""
    before_pins, before_skip = len(pins), len(skipped)
    league = str(row.league)
    tip = index_tip_leagues(store, {league}).get(league, TipLeagueIndex())
    _collect_event(
        league, raw, _games_by_date(_league_games(row, fixtures_fn)),
        pins, skipped, seen,
        player=person_league(league),
        entity_type=match_entity_type_for_row(row),
        tip=tip,
    )
    for pin in pins[before_pins:]:
        stamp_gap_harvest_pin(pin, book="prophetx", key=gap_key)
    for skip in skipped[before_skip:]:
        skip["book"] = "prophetx"
        skip["key"] = gap_key
    if len(pins) == before_pins and len(skipped) == before_skip:
        skipped.append({
            "book": "prophetx", "key": gap_key, "reason": "already_mapped",
        })


def league_for_px_tournament(rows: list[Any], tournament_id: str) -> Any | None:
    """Tip row whose enabled PX exchange owns this tournament."""
    tid = tournament_id.strip()
    if not tid:
        return None
    for row in rows:
        if getattr(row, "tombstone", False):
            continue
        if _px_tournament_id(row) == tid and str(row.optic_league_id or "").strip():
            return row
    return None


def harvest_px_code_misses(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    px_events_fn: PxEventsFn | None = None,
    fixtures_fn: FixturesFn | None = None,
    tips: dict[str, TipLeagueIndex] | None = None,
) -> None:
    """Draft PX codes that unique-match Optic fixture names and differ."""
    before = len(pins)
    try:
        leagues = _px_leagues(store)
        indexed = tips if tips is not None else index_tip_leagues(
            store, {str(lg.league) for lg in leagues},
        )
        for lg in leagues:
            _harvest_league(
                store, lg, pins, skipped, seen, px_events_fn, fixtures_fn,
                indexed.get(str(lg.league), TipLeagueIndex()),
            )
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest px_code failed")
        skipped.append({"book": "px", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info(
        "pipeline gap-fix stage=probe book=px pins=%d",
        len(pins) - before,
    )


def _harvest_league(
    store: Any,
    lg: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    px_events_fn: PxEventsFn | None,
    fixtures_fn: FixturesFn | None,
    tip: TipLeagueIndex,
) -> None:
    """One tip league: PX events vs Optic fixtures."""
    tid = _px_tournament_id(lg)
    events = _px_events(tid, px_events_fn)
    games = _league_games(lg, fixtures_fn)
    collect_px_code_pins(
        store, str(lg.league), events, games, pins, skipped, seen,
        entity_type=match_entity_type_for_row(lg),
        tip=tip,
    )


def collect_px_code_pins(
    store: Any,
    league: str,
    events: list[dict[str, Any]],
    games: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    entity_type: str = "team",
    tip: TipLeagueIndex | None = None,
) -> None:
    """Draft pins for one league's PX events against Optic games."""
    indexed = tip if tip is not None else index_tip_leagues(store, {league}).get(
        league, TipLeagueIndex(),
    )
    player = person_league(league)
    by_date = _games_by_date(games)
    for raw in events:
        _collect_event(
            league, raw, by_date, pins, skipped, seen,
            player=player, entity_type=entity_type, tip=indexed,
        )


def _collect_event(
    league: str,
    raw: dict[str, Any],
    by_date: dict[str, list[tuple[NamedSide, NamedSide, dict[str, Any]]]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    player: bool,
    entity_type: str,
    tip: TipLeagueIndex,
) -> None:
    """Draft missing PX codes for one event, or skip."""
    sides = _event_sides(raw)
    date = _et_date(str(raw.get("scheduled") or ""))
    if sides is None or not date:
        skipped.append({"league": league, "key": _event_key(raw), "reason": "px_sides"})
        return
    px_home, px_away = sides
    fixtures = [(h, a) for h, a, _g in by_date.get(date, [])]
    hit = unique_optic_sides(px_home, px_away, fixtures, player=player)
    if hit is None:
        skipped.append({"league": league, "key": _event_key(raw), "reason": "no_unique_optic"})
        return
    game = _game_for_hit(by_date.get(date, []), hit)
    _draft_pairs(
        league, raw, px_home, px_away, hit, game, pins, skipped, seen,
        player=player, entity_type=entity_type, tip=tip,
    )


def _draft_pairs(
    league: str,
    raw: dict[str, Any],
    px_home: NamedSide,
    px_away: NamedSide,
    hit: tuple[NamedSide, NamedSide],
    game: dict[str, Any] | None,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    player: bool,
    entity_type: str,
    tip: TipLeagueIndex,
) -> None:
    """One payload per PX abbr that is not already on the Optic owner."""
    pairs = aligned_pairs(px_home, px_away, hit[0], hit[1], player=player)
    if pairs is None:
        skipped.append({"league": league, "key": _event_key(raw), "reason": "ambiguous_orientation"})
        return
    # Owner collisions are checked per side against tip.px in _draft_pin.
    planned = planned_px_aliases(pairs, {})
    if not planned:
        return
    for px_side, optic_side in pairs:
        if px_side.abbr not in planned:
            continue
        pin = _draft_pin(
            league, px_side, optic_side, raw, game, skipped,
            entity_type=entity_type, player=player, tip=tip,
        )
        if pin is None:
            continue
        ident = (league, str(pin["canonical_key"]), px_side.abbr)
        if ident in seen:
            continue
        seen.add(ident)
        pins.append(pin)


def _draft_pin(
    league: str,
    px_side: NamedSide,
    optic_side: NamedSide,
    raw: dict[str, Any],
    game: dict[str, Any] | None,
    skipped: list[dict[str, str]],
    *,
    entity_type: str,
    player: bool,
    tip: TipLeagueIndex,
) -> dict[str, Any] | None:
    """Cart pin for one PX code onto the Optic canonical, or None."""
    key = tip.optic.get(optic_side.oid) or optic_side.abbr
    owner = tip.px.get(px_side.abbr.upper(), "")
    if owner and owner != key:
        skipped.append({"league": league, "key": px_side.abbr, "reason": "collision"})
        return None
    existing = tip.names.get(key, "")
    identity_locked = tip.optic.get(optic_side.oid) == key
    live_name = optic_side.name or px_side.name
    if existing and not names_fit(live_name, existing, player=player):
        if not identity_locked:
            skipped.append({"league": league, "key": px_side.abbr, "reason": "name_mismatch"})
            return None
        shown = live_name or existing
    else:
        shown = existing or live_name
    aliases = _aliases_for(tip, key, px_side.abbr, optic_side.oid)
    if not aliases:
        return None
    kind = tip.types.get(key) or entity_type
    return alias_payload(
        league, key, shown, kind, aliases, _refs(px_side, optic_side, raw, game),
    )


def _aliases_for(
    tip: TipLeagueIndex, key: str, code: str, oid: str,
) -> list[dict[str, Any]]:
    """PX code plus Optic id when the tip does not already carry them."""
    out: list[dict[str, Any]] = []
    if oid and oid not in tip.optic_on.get(key, set()):
        out.append(optic_pin(oid))
    if tip.px.get(code.upper()) != key:
        out.append({"sportsbook": "px", "alias_kind": "code", "alias_value": code})
    return out


def _refs(
    px_side: NamedSide,
    optic_side: NamedSide,
    raw: dict[str, Any],
    game: dict[str, Any] | None,
) -> list[str]:
    """PX event/name/abbr plus named Optic competitor and fixture."""
    refs = [
        f"px:event:{_event_key(raw)}",
        f"px:name:{px_side.name}",
        f"px:abbr:{px_side.abbr}",
        optic_competitor_ref(optic_side.oid, optic_side.name),
        optic_fixture_ref(game),
    ]
    if optic_side.abbr:
        refs.append(f"optic:abbr:{optic_side.abbr}")
    return [ref for ref in refs if ref]


def _px_leagues(store: Any) -> list[Any]:
    """Enabled tip leagues that have Optic and a PX tournament id."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    out: list[Any] = []
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        if not str(lg.optic_league_id or "").strip():
            continue
        if _px_tournament_id(lg):
            out.append(lg)
    return out


def _px_tournament_id(lg: Any) -> str:
    """PX tournament_id from enabled tip exchange settings."""
    for ex in lg.exchanges or []:
        if str(ex.get("sportsbook") or "").lower() != "px":
            continue
        if ex.get("enabled") is False:
            continue
        tid = dict(ex.get("settings") or {}).get("tournament_id")
        if tid is not None and str(tid).strip():
            return str(tid).strip()
    return ""


def _px_events(tid: str, px_events_fn: PxEventsFn | None) -> list[dict[str, Any]]:
    """PX events for one tournament; injected stubs skip BigQuery."""
    if px_events_fn is not None:
        return list(px_events_fn(tid))
    return _fetch_px_events_bq(tid)


def _fetch_px_events_bq(tid: str) -> list[dict[str, Any]]:
    """Latest PX event snapshot rows for this tournament (24h)."""
    project = os.environ.get("GCP_PROJECT") or "marketmaking-test"
    sql = f"""
select data from `{project}.raw_ingestion_us.px_events_fetch_raw`
where tournament_id = @tid
  and fetch_time > timestamp_sub(current_timestamp(), interval 24 hour)
qualify row_number() over (partition by event_id order by fetch_time desc) = 1
"""  # nosec B608
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("tid", "STRING", tid)],
    )
    rows = ro_query(ro_client(), sql, job_config=job)
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("data") if isinstance(row, dict) else getattr(row, "data", None)
        parsed = _parse_data(payload)
        if parsed:
            out.append(parsed)
    return out


def _league_games(lg: Any, fixtures_fn: FixturesFn | None) -> list[dict[str, Any]]:
    """Optic fixtures for one league, using the mapper horizon at minimum."""
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
            logger.warning("px harvest optic %s %s: %s", lg.league, oid, exc)
    return games


def _games_by_date(
    games: list[dict[str, Any]],
) -> dict[str, list[tuple[NamedSide, NamedSide, dict[str, Any]]]]:
    """ET date → Optic home/away plus the raw game."""
    out: dict[str, list[tuple[NamedSide, NamedSide, dict[str, Any]]]] = {}
    for game in games:
        sides = _game_sides(game)
        date = _et_date(str(game.get("start_date") or ""))
        if sides is None or not date:
            continue
        out.setdefault(date, []).append((sides[0], sides[1], game))
    return out


def _game_for_hit(
    rows: list[tuple[NamedSide, NamedSide, dict[str, Any]]],
    hit: tuple[NamedSide, NamedSide],
) -> dict[str, Any] | None:
    """Raw Optic game whose sides are the unique match."""
    for home, away, game in rows:
        if (home, away) == hit:
            return game
    return None


def _game_sides(game: dict[str, Any]) -> tuple[NamedSide, NamedSide] | None:
    """Home/away Optic sides; skip doubles and empty abbreviations."""
    home = _comp_side(game, "home_competitors")
    away = _comp_side(game, "away_competitors")
    if home is None or away is None:
        return None
    return home, away


def _comp_side(game: dict[str, Any], key: str) -> NamedSide | None:
    """First competitor as NamedSide when the side is a singles abbr."""
    people = game.get(key) or []
    if not isinstance(people, list) or len(people) != 1:
        return None
    row = people[0] if isinstance(people[0], dict) else {}
    abbr = str(row.get("abbreviation") or "").strip()
    name = str(row.get("name") or "").strip()
    oid = str(row.get("id") or "").strip()
    if not abbr or not name:
        return None
    return NamedSide(abbr, name, oid)


def _event_sides(raw: dict[str, Any]) -> tuple[NamedSide, NamedSide] | None:
    """Home/away from a PX event payload."""
    by_side: dict[str, NamedSide] = {}
    for row in raw.get("competitors") or []:
        if not isinstance(row, dict):
            continue
        side = str(row.get("side") or "")
        abbr = str(row.get("abbreviation") or "").strip()
        name = str(row.get("name") or "").strip()
        if side in ("home", "away") and abbr and name:
            by_side[side] = NamedSide(abbr, name)
    if "home" not in by_side or "away" not in by_side:
        return None
    return by_side["home"], by_side["away"]


def _et_date(utc_iso: str) -> str:
    """Eastern calendar date from a UTC ISO timestamp, or empty."""
    if not utc_iso.strip():
        return ""
    try:
        return to_date_str(to_et_str(utc_iso))
    except (TypeError, ValueError):
        return ""


def _event_key(raw: dict[str, Any]) -> str:
    """PX event id for skip rows and evidence."""
    return str(raw.get("event_id") or raw.get("id") or "")


def _parse_data(payload: Any) -> dict[str, Any]:
    """Decode a PX fetch snapshot ``data`` blob."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
