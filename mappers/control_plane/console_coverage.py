"""Fixture coverage explorer: Optic fixtures + published market_mapping."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.console_coverage_json import json_safe_row
from mappers.control_plane.console_coverage_optic_bq import query_optic_coverage_fixtures
from mappers.control_plane.console_coverage_stamps import coverage_stamp_row
from mappers.control_plane.console_fixture_phase import (
    coverage_matches_phase,
    is_complete_status,
    normalize_fixture_phase,
    row_is_open,
)
from mappers.control_plane.console_mapping_fixtures import (
    fixture_rows_from_optic,
    fixture_start_sort_key,
)
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.control_plane.league_review import book_label

CoverageQueryFn = Callable[[list[str]], list[dict[str, Any]]]
OpticQueryFn = Callable[..., tuple[list[dict[str, Any]], int]]

_MAPPING_SQL = """
select
  fixture_id,
  game_id,
  sportsbook,
  market_type,
  market_id,
  entity,
  selection,
  line,
  points,
  side,
  selection_line,
  source_ids,
  last_updated,
  home,
  away,
  league,
  sport
from `{project}.markets_us.market_mapping`
where start_date > timestamp_sub(current_timestamp(), interval 14 day)
  and (
    fixture_id in unnest(@ids)
    or game_id in unnest(@ids)
  )
"""


def _bq_project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def query_published_mappings(fixture_ids: list[str]) -> list[dict[str, Any]]:
    """Published market_mapping rows for Optic fixture ids (start_date filtered)."""
    ids = [fid for fid in fixture_ids if fid]
    if not ids:
        return []
    project = _bq_project()
    client = bigquery.Client(project=project)
    job = ro_query(
        client,
        _MAPPING_SQL.format(project=project),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]
        ),
    )
    return [dict(row) for row in job]


def _safe_published_mappings(fixture_ids: list[str]) -> list[dict[str, Any]]:
    try:
        return query_published_mappings(fixture_ids)
    except Exception:
        return []


def _tip_leagues(store: Any) -> list[Any]:
    rid = store.current_rule_set_id
    if not rid:
        return []
    return list(store.leagues_for(rid))


def _expected_markets(store: Any, league_slug: str) -> list[dict[str, Any]]:
    rid = store.current_rule_set_id
    if not rid:
        return []
    out: list[dict[str, Any]] = []
    for rule in store.market_rules_for(rid):
        if rule.league != league_slug or not rule.enabled:
            continue
        if rule.action != "map" or not rule.canonical_market_type:
            continue
        out.append(
            {
                "canonical_market_type": rule.canonical_market_type,
                "sportsbook": rule.sportsbook,
                "sportsbook_label": book_label(rule.sportsbook),
                "source_key": rule.source_key,
            }
        )
    return out


def _mtype(value: Any) -> str:
    return str(value or "").strip().casefold()


def _fixture_lookup_ids(fx: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("fixture_id", "game_id"):
        val = str(fx.get(key) or "").strip()
        if val and val not in out:
            out.append(val)
    return out


def _mapping_query_ids(page: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for fx in page:
        for alias in _fixture_lookup_ids(fx):
            if alias not in ids:
                ids.append(alias)
    return ids


def _index_published_mappings(
    rows: list[dict[str, Any]],
    page: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    alias_to_fid: dict[str, str] = {}
    for fx in page:
        fid = str(fx.get("fixture_id") or "").strip()
        if not fid:
            continue
        for alias in _fixture_lookup_ids(fx):
            alias_to_fid[alias] = fid
    mapped_by_fixture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for row in rows:
        keys = [
            str(row.get("fixture_id") or "").strip(),
            str(row.get("game_id") or "").strip(),
        ]
        for fid in {alias_to_fid[key] for key in keys if key in alias_to_fid}:
            marker = (fid, id(row))
            if marker in seen:
                continue
            seen.add(marker)
            mapped_by_fixture[fid].append(row)
    return mapped_by_fixture


def _fixture_coverage(
    mapped_rows: list[dict[str, Any]],
    expected: list[dict[str, Any]],
) -> dict[str, Any]:
    by_book: dict[str, set[str]] = defaultdict(set)
    for row in mapped_rows:
        book = str(row.get("sportsbook") or "").lower()
        mtype = _mtype(row.get("market_type") or row.get("canonical_market_type"))
        if book and mtype:
            by_book[book].add(mtype)
    expected_types = {_mtype(e.get("canonical_market_type")) for e in expected}
    expected_types.discard("")
    mapped_types: set[str] = set()
    for types in by_book.values():
        mapped_types |= types
    mapped_count = len(mapped_types & expected_types) if expected_types else len(mapped_types)
    expected_count = len(expected_types) if expected_types else max(len(mapped_types), 1)
    platforms: list[dict[str, Any]] = []
    books = sorted({str(e.get("sportsbook") or "") for e in expected} | set(by_book))
    for book in books:
        if not book:
            continue
        exp_for_book = {
            _mtype(e.get("canonical_market_type"))
            for e in expected
            if str(e.get("sportsbook") or "").lower() == book.lower()
        }
        exp_for_book.discard("")
        have = by_book.get(book.lower(), set())
        platforms.append(
            {
                "sportsbook": book,
                "sportsbook_label": book_label(book),
                "mapped_count": len(have & exp_for_book) if exp_for_book else len(have),
                "expected_count": len(exp_for_book) if exp_for_book else len(have) or 0,
                "markets": [
                    {
                        "canonical_market_type": mtype,
                        "mapped": mtype in have,
                    }
                    for mtype in sorted(exp_for_book or have)
                ],
            }
        )
    return {
        "mapped_count": mapped_count,
        "expected_count": expected_count,
        "platforms": platforms,
        "stamps": [json_safe_row(coverage_stamp_row(row)) for row in mapped_rows],
    }


def _collect_coverage_fixtures(
    store: Any,
    leagues: list[Any],
    *,
    fetch_fn: Any | None,
    phase: str | None = "live",
) -> list[dict[str, Any]]:
    tab = normalize_fixture_phase(phase) if phase else None
    fixtures: list[dict[str, Any]] = []
    for row in leagues:
        oid = str(getattr(row, "optic_league_id", "") or "").strip()
        if not oid:
            continue
        horizon = optic_horizon_hours(row)
        raw = cached_optic_fixtures(oid, horizon_hours=horizon, fetch_fn=fetch_fn)
        for fx in fixture_rows_from_optic(raw, sort=False):
            if is_complete_status(str(fx.get("optic_status") or "")):
                continue
            if not row_is_open(fx.get("ttko_hours")):
                continue
            if tab is not None and not coverage_matches_phase(fx, tab):
                continue
            fx["league"] = row.league
            fx["league_label"] = league_label(row.league)
            fx["sport"] = str(row.sport or "")
            fixtures.append(fx)
    fixtures.sort(key=fixture_start_sort_key)
    return fixtures


def _optic_id_map(leagues: list[Any]) -> dict[str, Any]:
    by_oid: dict[str, Any] = {}
    for row in leagues:
        oids = [str(getattr(row, "optic_league_id", "") or "").strip()]
        extra = getattr(row, "extra_optic_league_ids", None) or []
        oids.extend(str(oid).strip() for oid in extra)
        for oid in oids:
            if oid:
                by_oid[oid] = row
    return by_oid


def _fwd_hours(leagues: list[Any]) -> int:
    hours = [optic_horizon_hours(row) for row in leagues]
    return int(max(hours)) if hours else int(optic_horizon_hours(None))


def _bq_competitor(row: dict[str, Any], side: str) -> dict[str, str]:
    """Name / Optic id / abbreviation from a coverage BQ fixture row."""
    return {
        "name": str(row.get(side) or ""),
        "id": str(row.get(f"{side}_id") or ""),
        "abbreviation": str(row.get(f"{side}_abbr") or ""),
    }


def _page_from_optic_rows(
    raw: list[dict[str, Any]],
    by_oid: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in raw:
        oid = str(row.get("optic_league_id") or "").strip()
        league_row = by_oid.get(oid)
        if league_row is None:
            continue
        shaped = fixture_rows_from_optic(
            [
                {
                    "id": row.get("fixture_id"),
                    "game_id": row.get("game_id"),
                    "start_date": str(row.get("start_date") or ""),
                    "status": row.get("status"),
                    "home_competitors": [_bq_competitor(row, "home")],
                    "away_competitors": [_bq_competitor(row, "away")],
                }
            ],
            sort=False,
        )
        if not shaped:
            continue
        fx = shaped[0]
        fx["league"] = league_row.league
        fx["league_label"] = league_label(league_row.league)
        fx["sport"] = str(league_row.sport or "")
        out.append(fx)
    return out


def _annotate_fixture_coverage(
    store: Any,
    page: list[dict[str, Any]],
    mapped_by_fixture: dict[str, list[dict[str, Any]]],
) -> None:
    expected_by_league: dict[str, list[dict[str, Any]]] = {}
    for fx in page:
        slug = str(fx.get("league") or "")
        if slug not in expected_by_league:
            expected_by_league[slug] = _expected_markets(store, slug)
        expected = expected_by_league[slug]
        mapped = mapped_by_fixture.get(str(fx.get("fixture_id") or ""), [])
        cov = _fixture_coverage(mapped, expected)
        fx["coverage"] = {
            "mapped_count": cov["mapped_count"],
            "expected_count": cov["expected_count"],
        }
        fx["status"] = (
            "matched"
            if cov["expected_count"] and cov["mapped_count"] >= cov["expected_count"]
            else "partial"
            if cov["mapped_count"]
            else "unmapped"
        )


def _filter_leagues(
    store: Any,
    *,
    league: str | None,
    sport: str | None,
) -> list[Any]:
    leagues = _tip_leagues(store)
    if league:
        leagues = [row for row in leagues if row.league == league]
    if sport:
        leagues = [row for row in leagues if str(row.sport or "").lower() == sport.lower()]
    return leagues


def _filter_fixtures_by_name(fixtures: list[dict[str, Any]], q: str | None) -> list[dict[str, Any]]:
    needle = (q or "").strip().lower()
    if not needle:
        return fixtures
    out: list[dict[str, Any]] = []
    for fx in fixtures:
        hay = " ".join(str(fx.get(key) or "") for key in ("label", "home", "away")).lower()
        if needle in hay:
            out.append(fx)
    return out


_COVERAGE_DISCLAIMER = (
    "0/N is published market_mapping stamps vs tip map-rules on this "
    "Optic fixture, not 'rules exist'. Live/pre tabs use Optic status; "
    "kickoff time applies when status is missing. May lag after Proposed approve."
)


def _load_coverage_page(
    store: Any,
    leagues: list[Any],
    *,
    q: str | None,
    page_size: int,
    start: int,
    phase: str,
    fetch_fn: Any | None,
    optic_query_fn: OpticQueryFn | None,
) -> tuple[list[dict[str, Any]], int]:
    tab = normalize_fixture_phase(phase)
    if fetch_fn is not None:
        fixtures = _filter_fixtures_by_name(
            _collect_coverage_fixtures(store, leagues, fetch_fn=fetch_fn, phase=tab),
            q,
        )
        return fixtures[start : start + page_size], len(fixtures)
    by_oid = _optic_id_map(leagues)
    fetch_optic = optic_query_fn or query_optic_coverage_fixtures
    raw, total = fetch_optic(
        optic_ids=list(by_oid),
        q=q,
        limit=page_size,
        offset=start,
        fwd_hours=_fwd_hours(leagues),
        phase=tab,
    )
    return _page_from_optic_rows(raw, by_oid), total


def _stamp_fixture_page(
    store: Any,
    page: list[dict[str, Any]],
    mapping_query_fn: CoverageQueryFn | None,
) -> None:
    fetch_mappings = mapping_query_fn or _safe_published_mappings
    mapped = _index_published_mappings(fetch_mappings(_mapping_query_ids(page)), page)
    _annotate_fixture_coverage(store, page, mapped)


def list_coverage_fixtures(
    store: Any,
    *,
    league: str | None = None,
    sport: str | None = None,
    q: str | None = None,
    phase: str = "live",
    limit: int = 10,
    offset: int = 0,
    fetch_fn: Any | None = None,
    mapping_query_fn: CoverageQueryFn | None = None,
    optic_query_fn: OpticQueryFn | None = None,
) -> dict[str, Any]:
    """List Optic fixtures with coverage stats (published market_mapping)."""
    leagues = _filter_leagues(store, league=league, sport=sport)
    page_size = max(1, min(int(limit), 500))
    start = max(0, int(offset))
    page, total = _load_coverage_page(
        store,
        leagues,
        q=q,
        page_size=page_size,
        start=start,
        phase=phase,
        fetch_fn=fetch_fn,
        optic_query_fn=optic_query_fn,
    )
    _stamp_fixture_page(store, page, mapping_query_fn)
    return {
        "count": total,
        "limit": limit,
        "offset": offset,
        "fixtures": page,
        "disclaimer": _COVERAGE_DISCLAIMER,
    }
