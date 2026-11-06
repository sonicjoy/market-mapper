"""Bind a Chat entity name to one Optic competitor (gap-propose names_fit)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import fallback_code, names_fit, person_league
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.chat_catalog import tip_league_row
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.gap_fix_keys import name_hit, optic_key, used_keys
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours

logger = logging.getLogger(__name__)

UNIQUE = "unique"
AMBIGUOUS = "ambiguous"
NONE = "none"
ALREADY = "already"
NO_LEAGUE = "no_league"


@dataclass(frozen=True)
class OpticNameBind:
    """One name vs Optic 96h competitors for a single tip league."""

    status: str
    pin: dict[str, Any] | None = None
    names: tuple[str, ...] = ()
    reason: str = ""
    canonical_key: str = ""


def bind_optic_name(
    store: Any,
    *,
    name: str,
    league: str,
    fixtures_fn: Any = None,
) -> OpticNameBind:
    """Unique names_fit hit → Optic pin; verify with Cart Verify, not harvest."""
    needle = name.strip()
    slug = league.strip()
    if not needle or not slug:
        return OpticNameBind(status=NO_LEAGUE, reason="league required")
    row = tip_league_row(store, slug)
    if row is None or not str(row.optic_league_id or "").strip():
        return OpticNameBind(status=NO_LEAGUE, reason=f"{slug} has no optic_league_id")
    hits = _fit_hits(needle, _competitors(row, fixtures_fn), person_league(slug))
    return _bind_hits(store, slug, needle, hits, row)


def _bind_hits(
    store: Any,
    slug: str,
    needle: str,
    hits: list[dict[str, Any]],
    row: Any,
) -> OpticNameBind:
    names = tuple(str(h["name"]) for h in hits)
    if not hits:
        return OpticNameBind(status=NONE, reason="not in Optic window")
    if len(hits) > 1:
        return OpticNameBind(status=AMBIGUOUS, names=names, reason="not unique")
    hit = hits[0]
    oid = str(hit["oid"])
    existing = optic_key(store, slug, oid)
    if existing:
        return OpticNameBind(
            status=ALREADY, names=names, canonical_key=existing,
            reason=f"already on tip as {existing}",
        )
    pin = _draft_pin(store, slug, hit, row)
    if pin is None:
        return OpticNameBind(status=NONE, names=names, reason="no_code")
    return OpticNameBind(status=UNIQUE, pin=pin, names=names)


def _competitors(row: Any, fixtures_fn: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    horizon = optic_horizon_hours(row)
    extra = [str(x).strip() for x in (row.extra_optic_league_ids or [])]
    for oid in [str(row.optic_league_id or "").strip(), *extra]:
        if not oid:
            continue
        try:
            games = cached_optic_fixtures(
                oid, horizon_hours=horizon, fetch_fn=fixtures_fn,
            )
        except Exception as exc:  # noqa: BLE001 — missing key / network
            logger.warning("optic name bind %s %s: %s", row.league, oid, exc)
            games = []
        for game in games:
            out.extend(_sides(game))
    return out


def _sides(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Singles sides only — same skip as harvest_missing_optic_competitors."""
    out: list[dict[str, Any]] = []
    for key in ("home_competitors", "away_competitors"):
        people = game.get(key) or []
        if not isinstance(people, list) or len(people) != 1:
            continue
        comp = people[0] if isinstance(people[0], dict) else {}
        oid = str(comp.get("id") or "").strip()
        name = str(comp.get("name") or "").strip()
        if oid and name:
            out.append({
                "oid": oid,
                "name": name,
                "abbr": str(comp.get("abbreviation") or "").strip(),
                "game": game,
            })
    return out


def _fit_hits(
    needle: str, rows: list[dict[str, Any]], player: bool,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    for row in rows:
        oid = str(row["oid"])
        if oid in seen:
            continue
        if names_fit(needle, str(row["name"]), player=player):
            seen.add(oid)
            hits.append(row)
    return hits


def _draft_pin(
    store: Any, slug: str, hit: dict[str, Any], league_row: Any,
) -> dict[str, Any] | None:
    oid = str(hit["oid"])
    name = str(hit["name"])
    used = used_keys(store, slug)
    player = person_league(slug)
    key = name_hit(store, slug, name, player=player) or _invent(name, used, oid)
    if not key:
        return None
    entity_type = match_entity_type_for_row(league_row)
    refs = _refs(oid, name, str(hit.get("abbr") or ""), hit.get("game"))
    return alias_payload(slug, key, name, entity_type, [optic_pin(oid)], refs)


def _invent(name: str, used: set[str], oid: str) -> str:
    try:
        return fallback_code(name, used, oid)
    except ValueError:
        return ""


def _refs(oid: str, name: str, abbr: str, game: Any) -> list[str]:
    refs = [optic_competitor_ref(oid, name), optic_fixture_ref(game)]
    if name:
        refs.append(f"optic:name:{name}")
    if abbr:
        refs.append(f"optic:abbr:{abbr}")
    return [ref for ref in refs if ref]
