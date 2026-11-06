"""Harvest Optic pins when a fixture's two sides share an abbreviation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import names_fit
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_tip import TipLeagueIndex, index_tip_leagues
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.team_bootstrap import pin_shared_optic_abbr

logger = logging.getLogger(__name__)

_SOCCER = frozenset({"soccer", "football"})
FixturesFn = Callable[..., list[dict[str, Any]]]


def harvest_duplicate_optic_abbrs(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    fixtures_fn: FixturesFn | None = None,
    tips: dict[str, TipLeagueIndex] | None = None,
) -> None:
    """Scan soccer leagues for home/away sharing a non-empty Optic abbr."""
    before = len(pins)
    try:
        leagues = _soccer_leagues(store)
        indexed = tips if tips is not None else index_tip_leagues(
            store, {str(lg.league) for lg in leagues},
        )
        for lg in leagues:
            games = _league_games(lg, fixtures_fn)
            collect_duplicate_abbr_pins(
                store, str(lg.league), games, pins, skipped, seen,
                tip=indexed.get(str(lg.league), TipLeagueIndex()),
            )
    except Exception as exc:  # noqa: BLE001 — isolate from RFQ harvest
        logger.exception("gap harvest optic_abbr failed")
        skipped.append({"book": "optic_abbr", "reason": f"harvest_error:{exc}"[:160]})
        return
    logger.info(
        "pipeline gap-fix stage=probe book=optic_abbr pins=%d",
        len(pins) - before,
    )


def collect_duplicate_abbr_pins(
    store: Any,
    league: str,
    games: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    tip: TipLeagueIndex | None = None,
) -> None:
    """Draft pins for one league's same-abbr fixture pairs."""
    indexed = tip if tip is not None else index_tip_leagues(store, {league}).get(
        league, TipLeagueIndex(),
    )
    used = set(indexed.used)
    used.update(str(v).upper() for v in indexed.optic.values())
    for game in games:
        home = _side_triple(game, "home_competitors")
        away = _side_triple(game, "away_competitors")
        for oid, code, name in pin_shared_optic_abbr(home, away, indexed.optic, used):
            pin = _draft_pin(store, league, oid, code, name, game, skipped, indexed)
            if pin is None:
                continue
            ident = (league, str(pin["canonical_key"]), oid)
            if ident in seen:
                continue
            seen.add(ident)
            pins.append(pin)


def _soccer_leagues(store: Any) -> list[Any]:
    """Enabled soccer tip leagues that have an Optic league id."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    out: list[Any] = []
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        if str(lg.sport or "").lower() not in _SOCCER:
            continue
        if not str(lg.optic_league_id or "").strip():
            continue
        out.append(lg)
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
            logger.warning("optic abbr harvest %s %s: %s", lg.league, oid, exc)
    return games


def _side_triple(game: dict[str, Any], key: str) -> tuple[str, str, str]:
    """id, name, abbreviation for the first competitor on one side."""
    row = (game.get(key) or [{}])[0]
    return (
        str(row.get("id") or ""),
        str(row.get("name") or ""),
        str(row.get("abbreviation") or "").strip(),
    )


def _draft_pin(
    store: Any,
    league: str,
    oid: str,
    code: str,
    name: str,
    game: dict[str, Any],
    skipped: list[dict[str, str]],
    tip: TipLeagueIndex,
) -> dict[str, Any] | None:
    """Cart pin for one Optic id, or None when the tip already has it."""
    if oid in tip.optic_on.get(code, set()):
        return None
    existing = tip.names.get(code, "")
    if existing and not names_fit(name, existing, player=False):
        skipped.append({"league": league, "key": oid, "reason": "name_mismatch"})
        return None
    shown = existing or name
    entity_type = tip.types.get(code) or match_entity_type_for_league(store, league)
    refs = [
        ref for ref in (optic_competitor_ref(oid, name), optic_fixture_ref(game))
        if ref
    ]
    return alias_payload(league, code, shown, entity_type, [optic_pin(oid)], refs)
