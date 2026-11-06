"""Single-fixture Coverage detail pane."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.console_coverage import (
    CoverageQueryFn,
    _collect_coverage_fixtures,
    _expected_markets,
    _filter_leagues,
    _fixture_coverage,
    _fwd_hours,
    _index_published_mappings,
    _mapping_query_ids,
    _optic_id_map,
    _page_from_optic_rows,
    _safe_published_mappings,
    _tip_leagues,
)
from mappers.control_plane.console_coverage_optic_bq import (
    _BACK_HOURS,
    query_one_optic_coverage_fixture,
)
from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.entry import league_label
from mappers.control_plane.league_review import book_label
from mappers.seed.league_meta import league_settings_from_row, merge_league_meta_into_exchanges
from mappers.shared import FIXTURE_HORIZON_HOURS


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _entity_payload(ent: Any) -> dict[str, Any]:
    """Canonical entity plus per-book code/name pins for Coverage teams."""
    name = _norm(ent.canonical_name) or _norm(ent.canonical_key)
    aliases: list[dict[str, str]] = []
    for alias in ent.aliases or []:
        book = _norm(alias.get("sportsbook"))
        code = _norm(alias.get("alias_value"))
        if not book and not code:
            continue
        aliases.append(
            {
                "sportsbook": book,
                "sportsbook_label": book_label(book),
                "alias_kind": _norm(alias.get("alias_kind")) or "code",
                "code": code,
                "name": name,
            }
        )
    return {
        "league": ent.league,
        "league_label": league_label(ent.league or ""),
        "entity_name": name,
        "entity_type": ent.entity_type,
        "canonical_key": ent.canonical_key,
        "aliases": aliases,
    }


def _alias_values(ent: Any) -> set[str]:
    values: set[str] = set()
    for alias in ent.aliases or []:
        val = _norm(alias.get("alias_value"))
        if val:
            values.add(val)
    return values


def match_side_entity(
    store: Any,
    league_slug: str,
    *,
    name: str,
    competitor_ids: list[str] | None,
) -> dict[str, Any] | None:
    """Exact Optic competitor id or canonical name/key. Does not use names_close."""
    rid = store.current_rule_set_id
    if not rid or not league_slug:
        return None
    ids = {_norm(cid) for cid in competitor_ids or [] if _norm(cid)}
    name_n = _norm(name).casefold()
    by_name: Any | None = None
    for ent in store.entities_for(rid):
        if getattr(ent, "tombstone", False):
            continue
        if ent.league != league_slug:
            continue
        if ids and (_alias_values(ent) & ids):
            return _entity_payload(ent)
        canon_name = _norm(ent.canonical_name).casefold()
        canon_key = _norm(ent.canonical_key).casefold()
        if name_n and name_n in (canon_name, canon_key):
            by_name = by_name or ent
    if by_name is not None:
        return _entity_payload(by_name)
    return None


def _league_detail(league_row: Any | None) -> dict[str, Any] | None:
    if league_row is None:
        return None
    settings = league_settings_from_row(league_row)
    exchanges = merge_league_meta_into_exchanges(
        list(league_row.exchanges or []),
        settings,
    )
    return {
        "sport": str(league_row.sport or ""),
        "optic_league_id": str(league_row.optic_league_id or ""),
        "fixture_source": str(league_row.fixture_source or "api"),
        "fixture_horizon_hours": float(
            league_row.fixture_horizon_hours or FIXTURE_HORIZON_HOURS
        ),
        "enabled": bool(league_row.enabled),
        "entity_type": str(settings.get("entity_type") or ""),
        "alias_enforcement": str(settings.get("alias_enforcement") or "raise"),
        "runshop_enabled": bool(settings.get("runshop_enabled")),
        "exchanges": exchanges,
    }


def _league_market_rule_rows(store: Any, league_slug: str) -> list[dict[str, Any]]:
    rid = store.current_rule_set_id
    if not rid or not league_slug:
        return []
    out: list[dict[str, Any]] = []
    for mr in store.market_rules_for(rid):
        if getattr(mr, "tombstone", False):
            continue
        if (mr.league or "") != league_slug:
            continue
        out.append(
            {
                "league": mr.league or "",
                "league_label": league_label(mr.league or ""),
                "sportsbook_label": book_label(mr.sportsbook),
                "sportsbook": mr.sportsbook,
                "rule_kind": mr.rule_kind,
                "source_key_type": mr.source_key_type,
                "source_key": mr.source_key,
                "action": mr.action,
                "canonical_market_type": mr.canonical_market_type,
                "priority": mr.priority,
                "enabled": mr.enabled,
            }
        )
    return out


def _resolve_coverage_hit(
    store: Any,
    fixture_id: str,
    tip_leagues: list[Any],
    *,
    league: str | None,
    fetch_fn: Any | None,
    optic_one_fn: Any | None,
) -> dict[str, Any] | None:
    if fetch_fn is not None:
        leagues = _filter_leagues(store, league=league, sport=None)
        fixtures = _collect_coverage_fixtures(store, leagues, fetch_fn=fetch_fn, phase=None)
        return next((fx for fx in fixtures if str(fx.get("fixture_id")) == fixture_id), None)
    by_oid = _optic_id_map(tip_leagues)
    horizon = _fwd_hours(tip_leagues)
    fetch_one = optic_one_fn or (
        lambda fid: query_one_optic_coverage_fixture(
            fid,
            fwd_hours=horizon,
            back_hours=_BACK_HOURS,
        )
    )
    raw = fetch_one(fixture_id)
    page = _page_from_optic_rows([raw] if raw else [], by_oid)
    return page[0] if page else None


def _enrich_coverage_hit(
    store: Any,
    hit: dict[str, Any],
    tip_leagues: list[Any],
    *,
    fixture_id: str,
    league: str | None,
    mapping_query_fn: CoverageQueryFn | None,
) -> dict[str, Any]:
    if not str(hit.get("fixture_id") or "").strip():
        hit["fixture_id"] = fixture_id
    fetch_mappings = mapping_query_fn or _safe_published_mappings
    mapped = _index_published_mappings(
        fetch_mappings(_mapping_query_ids([hit])),
        [hit],
    ).get(str(hit.get("fixture_id") or ""), [])
    league_slug = str(hit.get("league") or league or "")
    league_row = next((row for row in tip_leagues if row.league == league_slug), None)
    expected = _expected_markets(store, league_slug)
    cov = _fixture_coverage(mapped, expected)
    hit["coverage"] = {
        "mapped_count": cov["mapped_count"],
        "expected_count": cov["expected_count"],
    }
    hit["home_entity"] = match_side_entity(
        store,
        league_slug,
        name=str(hit.get("home") or ""),
        competitor_ids=list(hit.get("home_competitor_ids") or []),
    )
    hit["away_entity"] = match_side_entity(
        store,
        league_slug,
        name=str(hit.get("away") or ""),
        competitor_ids=list(hit.get("away_competitor_ids") or []),
    )
    hit["league_entity_type"] = match_entity_type_for_row(league_row)
    hit["market_rules"] = _league_market_rule_rows(store, league_slug)
    hit["output_order"] = list(getattr(league_row, "output_order", None) or [])
    hit["league_detail"] = _league_detail(league_row)
    return {**hit, "coverage_detail": cov}


def get_coverage_fixture(
    store: Any,
    fixture_id: str,
    *,
    league: str | None = None,
    fetch_fn: Any | None = None,
    mapping_query_fn: CoverageQueryFn | None = None,
    optic_one_fn: Any | None = None,
) -> dict[str, Any] | None:
    """Detail pane for one fixture."""
    tip_leagues = _tip_leagues(store)
    hit = _resolve_coverage_hit(
        store,
        fixture_id,
        tip_leagues,
        league=league,
        fetch_fn=fetch_fn,
        optic_one_fn=optic_one_fn,
    )
    if hit is None:
        return None
    return _enrich_coverage_hit(
        store,
        hit,
        tip_leagues,
        fixture_id=fixture_id,
        league=league,
        mapping_query_fn=mapping_query_fn,
    )
