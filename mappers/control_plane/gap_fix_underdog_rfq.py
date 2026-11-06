"""Pin an Underdog RFQ code once its league is on the tip.

Catalog names use the existing team resolver. A code the catalog does not
know is pinned only when one Optic competitor abbreviation equals it.
A 3-letter code is never names-fit onto a display name.
"""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.gap_fix_onboard import stamp_gap_harvest_pin
from mappers.control_plane.gap_fix_underdog_leagues import UNDERDOG_BOOK
from mappers.control_plane.gap_fix_walk import remember_harvest_key
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.underdog_fixture_classify import _SKIP_SELECTIONS
from mappers.control_plane.underdog_fixture_harvest import parse_udx_header
from mappers.control_plane.underdog_legacy_ticker import parse_ticker
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG, market_type_for_venue
from mappers.control_plane.underdog_team_catalog import (
    entity_has_underdog_code,
    resolve_team_entity,
)


def probe_wired_underdog(
    item: RfqGapItem,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    rows: list[LeagueRow],
    catalog: dict[str, dict[str, str]],
    entities: list[EntityRow],
) -> None:
    """Draft the RFQ code, or record why this key still has no alias."""
    header = parse_udx_header(item.key)
    slug = VENUE_TOKEN_TO_LEAGUE_SLUG.get(header.venue, "") if header else ""
    code = _team_code(header.selection if header else "")
    if header is None or not slug:
        _skip(skipped, item.key, "no_source_league")
        return
    if _ignored(header):
        _skip(skipped, item.key, "out_of_scope")
        return
    league_entities = [row for row in entities if str(row.league) == slug]
    if not code:
        _pin_matchup(
            slug, header.venue, header.product, header.period, item.key,
            rows, league_entities, pins, skipped,
        )
        return
    venue_name = (catalog.get(slug) or {}).get(code, "")
    if venue_name:
        _pin_known_name(slug, code, venue_name, item.key, league_entities, pins, skipped)
        return
    _pin_optic_abbr(slug, code, item.key, rows, league_entities, pins, skipped)


def _team_code(selection: str) -> str:
    code = selection.strip().upper()
    if code.isalpha() and code not in _SKIP_SELECTIONS:
        return code
    return ""


# A player prop's selection is the team code plus a player stub plus the line
# ("WASTRAYOUNG34.5"); a total's or team total's is one letter ("O225.5", "A13.5").
_PLAYER_SELECTION = re.compile(r"^[A-Z]{6,}\d+(?:\.\d+)?$")

# The mapper binds an Underdog prop from the catalogue's own Optic market and
# player ids, never from this ticker grammar, so an unmapped prop is Optic
# supply (no prop or no such line yet) or the player witness, not a parser gap.
PROP_SUPPLY = "prop_supply"


def _player_prop(gap_key: str) -> bool:
    header = parse_udx_header(gap_key)
    return bool(header and _PLAYER_SELECTION.match(header.selection.strip().upper()))


def _ignored(header: Any) -> bool:
    if header is None:
        return False
    return header.selection.strip().upper() in _SKIP_SELECTIONS


def _pin_matchup(
    slug: str,
    venue: str,
    product: str,
    period: str,
    gap_key: str,
    rows: list[LeagueRow],
    entities: list[EntityRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    """A total or spread has no selection code. Pin the two Optic abbreviations."""
    optic_id = next(
        (str(row.optic_league_id) for row in rows if str(row.league) == slug and row.optic_league_id),
        "",
    )
    if not optic_id:
        _skip(skipped, gap_key, "needs_probe")
        return
    try:
        fixtures = cached_optic_fixtures(optic_id)
    except Exception:  # noqa: BLE001 — Optic outage retries; it is not a missing side
        _skip(skipped, gap_key, "needs_probe")
        return
    parsed = parse_ticker(gap_key, _fixture_abbrs(fixtures), sport=venue)
    teams = [code for code in ((parsed.away, parsed.home) if parsed else ()) if code]
    if not teams:
        known = market_type_for_venue(venue, product, period) is not None
        if known:
            _skip(skipped, gap_key, "missing_optic")
        else:
            _skip(skipped, gap_key, PROP_SUPPLY if _player_prop(gap_key) else "needs_code")
        return
    missing = [team for team in teams if not _entity_has_code(entities, team)]
    if not missing:
        _skip(skipped, gap_key, PROP_SUPPLY if parsed and parsed.player_token else "already_mapped")
        return
    for team in missing:
        _pin_optic_abbr(slug, team, gap_key, rows, entities, pins, skipped)


def _fixture_abbrs(fixtures: list[dict[str, Any]]) -> frozenset[str]:
    codes: set[str] = set()
    for game in fixtures:
        for side in ("home_competitors", "away_competitors"):
            people = game.get(side) or []
            if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], dict):
                continue
            abbr = str(people[0].get("abbreviation") or "").strip().upper()
            if abbr:
                codes.add(abbr)
    return frozenset(codes)


def _entity_has_code(entities: list[EntityRow], code: str) -> bool:
    return any(entity_has_underdog_code(entity, code) for entity in entities)


def _pin_known_name(
    slug: str,
    code: str,
    venue_name: str,
    gap_key: str,
    entities: list[EntityRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    entity = resolve_team_entity(entities, code, venue_name)
    if entity is None:
        _skip(skipped, gap_key, "needs_code")
        return
    if entity_has_underdog_code(entity, code):
        _skip(skipped, gap_key, "already_mapped")
        return
    _append_code_pin(slug, code, entity, gap_key, pins)


def _pin_optic_abbr(
    slug: str,
    code: str,
    gap_key: str,
    rows: list[LeagueRow],
    entities: list[EntityRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    optic_id = next(
        (str(row.optic_league_id) for row in rows if str(row.league) == slug and row.optic_league_id),
        "",
    )
    if not optic_id:
        _skip(skipped, gap_key, "needs_probe")
        return
    try:
        fixtures = cached_optic_fixtures(optic_id)
    except Exception:  # noqa: BLE001 — Optic outage retries; it is not a missing side
        _skip(skipped, gap_key, "needs_probe")
        return
    hits = _abbr_hits(fixtures, code)
    if len(hits) != 1:
        _skip(skipped, gap_key, "missing_optic" if not hits else "no_unique_optic")
        return
    oid, name = next(iter(hits.items()))
    entity = _entity_for_optic(entities, oid)
    if entity is None:
        _skip(skipped, gap_key, "needs_code")
        return
    if entity_has_underdog_code(entity, code):
        _skip(skipped, gap_key, "already_mapped")
        return
    _append_code_pin(slug, code, entity, gap_key, pins, name=name)


def _abbr_hits(fixtures: list[dict[str, Any]], code: str) -> dict[str, str]:
    hits: dict[str, str] = {}
    for game in fixtures:
        for side in ("home_competitors", "away_competitors"):
            people = game.get(side) or []
            if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], dict):
                continue
            row = people[0]
            abbr = str(row.get("abbreviation") or "").strip().upper()
            oid = str(row.get("id") or "").strip()
            if abbr == code and oid:
                hits.setdefault(oid, str(row.get("name") or "").strip())
    return hits


def _entity_for_optic(entities: list[EntityRow], oid: str) -> EntityRow | None:
    for entity in entities:
        if entity.tombstone or not entity.enabled:
            continue
        if str(entity.canonical_key) == oid:
            return entity
        for alias in entity.aliases or []:
            if str(alias.get("alias_value") or "") == oid:
                return entity
    return None


def _append_code_pin(
    slug: str,
    code: str,
    entity: EntityRow,
    gap_key: str,
    pins: list[dict[str, Any]],
    *,
    name: str = "",
) -> None:
    prior = _same_code_pin(pins, slug, code)
    if prior is not None:
        remember_harvest_key(prior, {"harvest_book": UNDERDOG_BOOK, "harvest_key": gap_key})
        return
    pin = alias_payload(
        slug,
        str(entity.canonical_key),
        str(entity.canonical_name or name),
        str(entity.entity_type or "team"),
        [{"sportsbook": UNDERDOG_BOOK, "alias_kind": "code", "alias_value": code}],
        [f"gap:udx:{slug}:{code}"],
    )
    stamp_gap_harvest_pin(pin, book=UNDERDOG_BOOK, key=gap_key)
    pins.append(pin)


def _same_code_pin(
    pins: list[dict[str, Any]], slug: str, code: str,
) -> dict[str, Any] | None:
    """Pin already drafted for this Underdog code in this harvest."""
    for pin in pins:
        if str(pin.get("league") or "") != slug:
            continue
        for alias in pin.get("aliases") or []:
            if alias.get("remove"):
                continue
            if (
                alias.get("sportsbook") == UNDERDOG_BOOK
                and alias.get("alias_kind") == "code"
                and str(alias.get("alias_value") or "") == code
            ):
                return pin
    return None


def _skip(skipped: list[dict[str, str]], key: str, reason: str) -> None:
    skipped.append({"book": UNDERDOG_BOOK, "key": key, "reason": reason})
