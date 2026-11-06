"""Live BQ/API harvest for crypto, polymarket, poly_usa, px, novig."""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from typing import Any

from BigQuery.client import ro_client, ro_query
from mappers.control_plane.gap_fix_dkex_leagues import venue_token_for_slug as dkex_venue_for_slug
from mappers.control_plane.gap_fix_poly_bq import fetch_close_us_events, fetch_poly_official_events
from mappers.control_plane.gap_fix_underdog_leagues import venue_token_for_slug
from mappers.control_plane.harvest_league_ids_common import (
    archive_crypto_pin,
    archive_novig_pin,
    archive_underdog_pin,
    fixtures_by_optic_window,
    league_match_needles,
    title_matches_league,
)
from mappers.control_plane.poly_us_match import best_fixture, normalize_fixture, unique_optic_for_questions
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK, US_CODE_OVERRIDES

_POLY_PREFIX_LIMIT = 80
_POLY_US_INNER_LIMIT = 40


def harvest_crypto_meta(
    league_slug: str,
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
    *,
    sport: str,
) -> dict[str, Any]:
    """crypto.com meta from archive config — never Optic league id or display name."""
    archived = archive_crypto_pin(league_slug, sport)
    if archived is not None:
        return archived
    return {
        "ok": True,
        "book": "crypto.com",
        "evidence": False,
        "note": "no crypto.com meta in archive for this league slug",
    }


def harvest_polymarket_prefix(
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Live official Polymarket prefix via gap-propose unique bind."""
    optic = optic_league_id.strip()
    if not optic:
        return {
            "ok": False,
            "book": "polymarket",
            "evidence": False,
            "note": "optic_league_id required",
        }
    if not fixtures:
        return {
            "ok": True,
            "book": "polymarket",
            "evidence": False,
            "note": "no Optic fixtures in horizon",
        }
    prefixes = _recent_poly_prefixes()
    if not prefixes:
        return {
            "ok": True,
            "book": "polymarket",
            "evidence": False,
            "note": "no recent official Polymarket prefixes",
        }
    hits = _poly_prefix_hits(optic, fixtures, prefixes)
    return _single_prefix_result(hits)


def harvest_poly_usa_code(
    league: str,
    optic_league_id: str,
    sport: str,
    fixtures: list[dict[str, Any]],
    store: Any,
) -> dict[str, Any]:
    """Match Poly USA inner league code from recent US events + Optic fixtures."""
    override = _poly_usa_override(league)
    if override is not None:
        return override
    missing = _poly_usa_missing_fields(optic_league_id, fixtures)
    if missing is not None:
        return missing
    normed = _normed_fixtures(optic_league_id, fixtures)
    inners = _recent_us_inners()
    if not inners:
        return _poly_usa_note("no recent Poly USA league codes")
    scores = _score_poly_us_inners(inners, normed)
    return _poly_usa_from_scores(scores)


def harvest_px_tournament(
    league: str,
    optic_league_id: str,
    sport: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match PX tournament id from live events using league name needles."""
    needles = league_match_needles(league, optic_league_id, fixtures)
    if not needles:
        return {
            "ok": True,
            "book": "px",
            "evidence": False,
            "note": "optic league name required",
        }
    try:
        tournaments = _recent_px_tournaments()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "book": "px",
            "evidence": False,
            "error": str(exc)[:160],
        }
    hits = _px_tournament_hits(tournaments, needles)
    if len(hits) == 1:
        tid = next(iter(hits))
        return {
            "ok": True,
            "book": "px",
            "evidence": True,
            "source": str(tid),
            "tournament_id": tid,
        }
    if not hits:
        return {
            "ok": True,
            "book": "px",
            "evidence": False,
            "note": "no PX tournament matched Optic league name",
        }
    return {
        "ok": True,
        "book": "px",
        "evidence": False,
        "note": f"ambiguous PX tournaments: {', '.join(str(t) for t in sorted(hits)[:4])}",
    }

def harvest_dkex_league(
    league_slug: str,
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    """DKEX venue league token (NFL, CFB, …) — not the Optic league id."""
    _ = fixtures
    token = dkex_venue_for_slug(league_slug, optic_league_id)
    if token:
        return {
            "ok": True,
            "book": "dkex",
            "evidence": True,
            "source": token,
            "league": token,
            "note": "DKEX venue league from slug",
        }
    return {
        "ok": True,
        "book": "dkex",
        "evidence": False,
        "note": "no DKEX venue mapping for this league slug",
    }


def harvest_underdog_league(
    league_slug: str,
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Underdog venue league token (NFL, MLB, …) — not the Optic league id."""
    _ = fixtures
    archived = archive_underdog_pin(league_slug)
    if archived is not None:
        return archived
    token = venue_token_for_slug(league_slug, optic_league_id)
    if token:
        return {
            "ok": True,
            "book": "underdog",
            "evidence": True,
            "source": token,
            "league": token,
            "note": "Underdog venue league from slug",
        }
    return {
        "ok": True,
        "book": "underdog",
        "evidence": False,
        "note": "no Underdog venue mapping for this league slug",
    }


def harvest_novig_league(
    league_slug: str,
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Novig league string from archive config — not Optic league id."""
    archived = archive_novig_pin(league_slug)
    if archived is not None:
        return archived
    return {
        "ok": True,
        "book": "novig",
        "evidence": False,
        "note": "no Novig league in archive for this league slug",
    }


def _poly_usa_override(league: str) -> dict[str, Any] | None:
    slug = league.strip().casefold()
    override = US_CODE_OVERRIDES.get(slug)
    if not override:
        return None
    return {
        "ok": True,
        "book": POLY_USA_BOOK,
        "evidence": True,
        "source": override,
        "slug_prefix": override,
        "note": "bootstrap US inner override",
    }


def _poly_usa_missing_fields(
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not optic_league_id.strip():
        return {
            "ok": False,
            "book": POLY_USA_BOOK,
            "evidence": False,
            "note": "optic_league_id required",
        }
    if not fixtures:
        return _poly_usa_note("no Optic fixtures in horizon")
    return None


def _poly_usa_note(note: str) -> dict[str, Any]:
    return {"ok": True, "book": POLY_USA_BOOK, "evidence": False, "note": note}


def _normed_fixtures(
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    optic = optic_league_id.strip()
    return [normalize_fixture({**fx, "optic_league_id": optic}) for fx in fixtures]


def _score_poly_us_inners(
    inners: list[str],
    normed: list[dict[str, Any]],
) -> Counter[str]:
    events = fetch_close_us_events(inners)
    scores: Counter[str] = Counter()
    for event in events:
        inner = str(event.get("inner") or "").strip().casefold()
        if inner and best_fixture(event, normed) is not None:
            scores[inner] += 1
    return scores


def _poly_usa_from_scores(scores: Counter[str]) -> dict[str, Any]:
    if not scores:
        return _poly_usa_note("no Poly USA events matched Optic fixtures")
    top = scores.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return _poly_usa_note("ambiguous Poly USA league codes")
    code = top[0][0]
    return {
        "ok": True,
        "book": POLY_USA_BOOK,
        "evidence": True,
        "source": code,
        "slug_prefix": code,
    }


def _poly_prefix_hits(
    optic: str,
    fixtures: list[dict[str, Any]],
    prefixes: list[str],
) -> list[str]:
    by_optic = fixtures_by_optic_window(optic, fixtures)
    events = fetch_poly_official_events(prefixes)
    by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        prefix = str(event.get("prefix") or "").strip().casefold()
        if prefix:
            by_prefix[prefix].append(event)
    hits: list[str] = []
    for prefix, rows in by_prefix.items():
        found = unique_optic_for_questions(rows, by_optic)
        if found == optic:
            hits.append(prefix)
    return hits


def _single_prefix_result(hits: list[str]) -> dict[str, Any]:
    if len(hits) == 1:
        slug = hits[0]
        return {
            "ok": True,
            "book": "polymarket",
            "evidence": True,
            "source": slug,
            "slug_prefix": slug,
        }
    if not hits:
        return {
            "ok": True,
            "book": "polymarket",
            "evidence": False,
            "note": "no official Polymarket prefix matched Optic fixtures",
        }
    return {
        "ok": True,
        "book": "polymarket",
        "evidence": False,
        "note": f"ambiguous Polymarket prefixes: {', '.join(hits[:4])}",
    }


def _px_tournament_hits(
    tournaments: list[tuple[int, str]],
    needles: list[str],
) -> set[int]:
    hits: set[int] = set()
    for tid, name in tournaments:
        title = _norm(name)
        if title and any(title_matches_league(title, needle) for needle in needles):
            hits.add(tid)
    return hits


def _recent_px_tournaments() -> list[tuple[int, str]]:
    project = os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = f"""
select
  cast(tournament_id as int64) as tournament_id,
  any_value(json_value(data, '$.tournament_name')) as tournament_name
from `{project}.raw_ingestion_us.px_events_fetch_raw`
where fetch_time > timestamp_sub(current_timestamp(), interval 24 hour)
  and tournament_id is not null
group by tournament_id
"""  # nosec B608
    rows = list(ro_query(ro_client(), sql))
    out: list[tuple[int, str]] = []
    for row in rows:
        tid = getattr(row, "tournament_id", None)
        name = str(getattr(row, "tournament_name", "") or "").strip()
        if tid is None or not name:
            continue
        try:
            out.append((int(tid), name))
        except (TypeError, ValueError):
            continue
    return out


def _recent_poly_prefixes() -> list[str]:
    project = os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = f"""
select prefix
from (
  select
    regexp_extract(b.slug, r'^([a-z0-9]+)-') as prefix,
    max(r.last_updated) as latest
  from `{project}.reporting_us.rfq_latest` as r
  cross join unnest(r.legs) as l
  inner join `{project}.raw_ingestion_us.polymarket_position_token_bridge` as b
    on b.position_id = json_value(l.platform_mapping, '$.token_id')
  where lower(r.platform) like 'polymarket%'
    and lower(r.platform) not like '%us%'
    and r.last_updated > timestamp_sub(current_timestamp(), interval 14 day)
    and b.slug is not null
  group by 1
)
where prefix is not null and prefix != ''
order by latest desc
limit {_POLY_PREFIX_LIMIT}
"""  # nosec B608
    try:
        rows = list(ro_query(ro_client(), sql))
    except Exception:  # noqa: BLE001
        return []
    return [str(getattr(row, "prefix", "") or "").strip() for row in rows if getattr(row, "prefix", None)]


def _recent_us_inners() -> list[str]:
    project = os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = f"""
select inner_code
from (
  -- Inner from the gateway record the fetch stored (typed): symbols are
  -- joined on exactly, never split.
  select lower(f.inner_league) as inner_code, max(r.last_updated) as latest
  from `{project}.reporting_us.rfq_latest` as r, unnest(r.legs) as l
  join `{project}.raw_ingestion_us.polymarket_usa_fetch_raw` as f
    on f.market_id = lower(coalesce(
      json_value(l.platform_mapping, '$.ticker'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.symbol')
    ))
  where lower(r.platform) like '%polymarket%us%'
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval 7 day)
    and r.last_updated > timestamp_sub(current_timestamp(), interval 7 day)
    and f.fetch_time > timestamp_sub(current_timestamp(), interval 7 day)
  group by 1
)
where inner_code is not null and inner_code != ''
order by latest desc
limit {_POLY_US_INNER_LIMIT}
"""  # nosec B608
    try:
        rows = list(ro_query(ro_client(), sql))
    except Exception:  # noqa: BLE001
        return []
    return [str(getattr(row, "inner_code", "") or "").strip() for row in rows if getattr(row, "inner_code", None)]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
