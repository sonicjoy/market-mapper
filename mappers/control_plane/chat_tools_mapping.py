"""market_mapping lookups for Mapper Chat probes (every sportsbook)."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_client, ro_query
from mappers.control_plane.chat_tools_dkex_mapping import (
    classify_dkex_symbol,
    dkex_symbol_fields,
)
from mappers.control_plane.chat_tools_poly_usa_mapping import classify_us_symbol, us_symbol_fields
from mappers.control_plane.chat_tools_probe import (
    probe_novig_id,
    probe_polymarket_id,
    probe_px_id,
)
from mappers.control_plane.evidence_format import optic_identity_refs
from mappers.control_plane.underdog_legacy_ticker import (
    find_udx_ticker,
    parse_ticker,
    venue_token_from_body,
)
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG
from mappers.control_plane.underdog_team_catalog import team_catalog
from mappers.exchanges.poly_slug import parse_poly_slug, slug_gap_kind

EventFn = Callable[[str], dict[str, Any]]
MappingFn = Callable[[str], list[dict[str, Any]]]
QueryFn = Callable[[str, dict[str, str]], list[Any]]

_EVENT = re.compile(
    r"^(KX[A-Z0-9]+-\d{2}[A-Z]{3}\d{2}[A-Z0-9]+)(?:-[A-Z0-9.]+)?$",
    re.I,
)
_MATURITY = re.compile(r"\.\d{8}$")
_POLY_CID = re.compile(r"^(?:0x)?[0-9a-f]{64}$", re.I)
_HEX_TOKEN = re.compile(r"^[0-9a-f]{32,80}$", re.I)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_KEYS = (
    "sportsbook",
    "market_ticker",
    "symbol",
    "source_selection_id",
    "source_event_id",
    "league",
    "sport",
    "start_date",
    "home",
    "away",
    "market_type",
    "entity",
    "line",
    "side",
    "fixture_id",
    "game_id",
    "market_id",
    "selection",
)
MAPPING_SELECT = """
select
  sportsbook,
  json_value(to_json_string(source_ids), '$.market_id') as market_ticker,
  json_value(to_json_string(source_ids), '$.symbol') as symbol,
  json_value(to_json_string(source_ids), '$.selection_id') as source_selection_id,
  json_value(to_json_string(source_ids), '$.event_id') as source_event_id,
  league,
  sport,
  cast(start_date as string) as start_date,
  home,
  away,
  market_type,
  entity,
  cast(line as string) as line,
  side,
  fixture_id,
  game_id,
  market_id,
  selection
from `{project}.markets_us.market_mapping`
where start_date > timestamp_sub(current_timestamp(), interval 90 day)
"""
_SQL = MAPPING_SELECT + """  and (
    json_value(to_json_string(source_ids), '$.market_id') = @id
    or json_value(to_json_string(source_ids), '$.market_id') = @event
    or json_value(to_json_string(source_ids), '$.symbol') = @id
    or json_value(to_json_string(source_ids), '$.symbol') = @base
    or json_value(to_json_string(source_ids), '$.selection_id') = @id
    or json_value(to_json_string(source_ids), '$.event_id') = @id
    or (
      starts_with(@event, 'KX')
      and starts_with(
        json_value(to_json_string(source_ids), '$.market_id'),
        concat(@event, '-')
      )
    )
  )
order by start_date desc, sportsbook, side
limit 20
"""


def kalshi_event_ticker(ticker: str) -> str:
    """Strip a market suffix (-TIE, -PSG, -SCST1) to the event ticker."""
    text = ticker.strip()
    m = _EVENT.match(text)
    return m.group(1) if m else text


def source_aliases(source_id: str) -> tuple[str, str, str]:
    """Pasted id plus Kalshi event ticker and crypto.com base symbol."""
    text = source_id.strip()
    event = kalshi_event_ticker(text)
    base = _MATURITY.sub("", text) if text.upper().startswith("NX.") else text
    return text, event, base


def mapping_sql(project: str) -> str:
    """market_mapping probe SQL (all books, partitioned, parameterized)."""
    return _SQL.replace("{project}", project)


def lookup_mapping(
    source_id: str,
    *,
    query_fn: QueryFn | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Rows in market_mapping for any sportsbook source id; soft miss."""
    text, event, base = source_aliases(source_id)
    if not text:
        return []
    try:
        rows = _load_rows(text, event, base, query_fn=query_fn, project=project)
    except Exception:  # noqa: BLE001 — chat tools soft-fail
        return []
    return [mapping_row(row) for row in rows]


def row_from_mapping(source_id: str, mapped: list[dict[str, Any]]) -> dict[str, Any]:
    """Probe row from published mapping — skip live catalogue when mapped."""
    first = mapped[0]
    home = str(first.get("home") or "")
    away = str(first.get("away") or "")
    title = f"{home} vs {away}" if home and away else home or away
    optic = {
        "fixture_id": first.get("fixture_id") or "",
        "start_date": first.get("start_date") or "",
        "home": home,
        "away": away,
    }
    refs = [f"gap:{source_id}"]
    refs.extend(optic_identity_refs(optic))
    return {
        "ok": True,
        "kind": "already_mapped",
        "mapped_rows": mapped,
        "league": first.get("league") or "",
        "sportsbook": first.get("sportsbook") or "",
        "title": title,
        "meta_name": title,
        "event_ticker": kalshi_event_ticker(source_id),
        "market_ticker": source_id,
        "symbol": source_id,
        "codes": [],
        "crypto_ids": [],
        "tip": [],
        "optic": optic,
        "evidence_refs": refs,
    }


def classify_source_id(source_id: str) -> dict[str, str]:
    """Guess book + id kind from a pasted Polymarket / PX / Novig source id."""
    text = source_id.strip()
    if _POLY_CID.fullmatch(text):
        cid = text if text.lower().startswith("0x") else f"0x{text.lower()}"
        return {"id": text, "norm_id": cid, "sportsbook": "polymarket", "id_kind": "condition_id"}
    if _HEX_TOKEN.fullmatch(text):
        return {"id": text, "norm_id": text, "sportsbook": "polymarket", "id_kind": "hex_token"}
    if _UUID.fullmatch(text):
        return {"id": text, "norm_id": text, "sportsbook": "novig", "id_kind": "novig_id"}
    if find_udx_ticker(text):
        return {
            "id": text, "norm_id": text,
            "sportsbook": "underdog", "id_kind": "udx_ticker",
        }
    dkex_hit = classify_dkex_symbol(text)
    if dkex_hit:
        return dkex_hit
    us_hit = classify_us_symbol(text)
    if us_hit:
        return us_hit
    if parse_poly_slug(text) is not None:
        return {
            "id": text, "norm_id": text.lower(),
            "sportsbook": "polymarket", "id_kind": "poly_slug",
        }
    if text.isdigit() and len(text) >= 20:
        return {"id": text, "norm_id": text, "sportsbook": "polymarket", "id_kind": "clob_token_id"}
    if text.isdigit() and len(text) >= 6:
        return {"id": text, "norm_id": text, "sportsbook": "px", "id_kind": "px_id"}
    return {"id": text, "norm_id": text, "sportsbook": "", "id_kind": "unknown"}


def probe_source_mapping(
    source_id: str,
    *,
    query_fn: QueryFn | None = None,
    catalogue_fn: Callable[[dict[str, str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mapping lookup, then Polymarket Gamma / PX / Novig snapshot on a miss."""
    mapped = lookup_mapping(source_id, query_fn=query_fn)
    if mapped:
        row = row_from_mapping(source_id, mapped)
        return {"ok": True, "count": 1, "results": [row]}
    classified = classify_source_id(source_id)
    extra: dict[str, Any] = {}
    if catalogue_fn is not None:
        extra = catalogue_fn(classified) or {}
    elif query_fn is None:
        extra = _live_catalogue(classified)
    if not extra:
        extra = _offline_anatomy(classified, source_id)
    return {"ok": True, "count": 1, "results": [_unmapped_row(source_id, classified, extra)]}


def _live_catalogue(classified: dict[str, str]) -> dict[str, Any]:
    """Soft Gamma, PX, or Novig snapshot for an unmapped source id."""
    kind = classified.get("id_kind") or ""
    ident = classified.get("norm_id") or classified.get("id") or ""
    if kind == "condition_id":
        return probe_polymarket_id(ident, by="condition")
    if kind == "clob_token_id":
        return probe_polymarket_id(ident, by="position")
    if kind == "px_id":
        return probe_px_id(ident)
    if kind == "novig_id":
        return probe_novig_id(ident)
    if kind == "udx_ticker":
        return _udx_ticker_fields(ident)
    if kind == "dkex_symbol":
        return dkex_symbol_fields(ident)
    if kind == "us_symbol":
        return us_symbol_fields(ident)
    if kind == "poly_slug":
        return _offline_anatomy(classified, ident)
    return {}


def _offline_anatomy(classified: dict[str, str], source_id: str) -> dict[str, Any]:
    """Gateway / official slug anatomy when Gamma/PX/Novig do not apply."""
    ident = classified.get("norm_id") or source_id
    kind = classified.get("id_kind") or ""
    if kind == "udx_ticker":
        return _udx_ticker_fields(ident)
    if kind == "dkex_symbol":
        return dkex_symbol_fields(ident)
    if kind == "us_symbol":
        return us_symbol_fields(ident)
    if kind == "poly_slug":
        return _poly_slug_fields(ident)
    return {}


def _udx_ticker_fields(source_id: str) -> dict[str, Any]:
    """Offline anatomy from a Underdog UDX ticker — no network."""
    ident = find_udx_ticker(source_id) or source_id.strip()
    if not ident.startswith("UDX"):
        return {}
    sport = venue_token_from_body(ident[3:])
    slug = VENUE_TOKEN_TO_LEAGUE_SLUG.get(sport, "")
    parsed = parse_ticker(ident, frozenset(team_catalog().get(slug, {})), sport=sport)
    kickoff = ""
    home = away = ""
    title = ident
    if parsed is not None:
        kickoff = parsed.start.isoformat()
        home, away = parsed.home, parsed.away
        title = f"{away} @ {home}"
    return {
        "seen": True,
        "sportsbook": "underdog",
        "id_kind": "udx_ticker",
        "title": title,
        "league": sport,
        "kickoff": kickoff,
        "scheduled": kickoff,
        "home": home,
        "away": away,
    }


def _poly_slug_fields(source_id: str) -> dict[str, Any]:
    """Offline anatomy from an official Polymarket slug — no network."""
    parsed = parse_poly_slug(source_id)
    if parsed is None:
        return {}
    return {
        "seen": True,
        "sportsbook": "polymarket",
        "id_kind": "poly_slug",
        "kind": slug_gap_kind(parsed.suffix),
        "title": f"{parsed.home} vs {parsed.away}",
        "league": parsed.prefix,
        "kickoff": parsed.date,
        "scheduled": parsed.date,
        "home": parsed.home,
        "away": parsed.away,
        "suffix": parsed.suffix,
        "slug": parsed.raw,
    }


def _unmapped_row(
    source_id: str, classified: dict[str, str], extra: dict[str, Any],
) -> dict[str, Any]:
    """Miss row with id anatomy plus any Gamma / PX / Novig catalogue fields."""
    title = str(extra.get("title") or extra.get("question") or "")
    home = str(extra.get("home") or "")
    away = str(extra.get("away") or "")
    if not title and home and away:
        title = f"{home} vs {away}"
    kickoff = str(
        extra.get("kickoff") or extra.get("game_start_time") or extra.get("scheduled") or ""
    )
    return {
        "ok": True,
        "kind": str(extra.get("kind") or "unmapped"),
        "mapped_rows": [],
        "market_ticker": source_id,
        "symbol": source_id,
        "title": title,
        "meta_name": title,
        "meta_event_date": kickoff,
        "league": str(extra.get("league") or extra.get("tournament") or ""),
        "sportsbook": str(extra.get("sportsbook") or classified.get("sportsbook") or ""),
        "id_kind": str(extra.get("id_kind") or classified.get("id_kind") or ""),
        "norm_id": classified.get("norm_id") or source_id,
        "slug": str(extra.get("slug") or ""),
        "outcomes": list(extra.get("outcomes") or []),
        "tournament": str(extra.get("tournament") or ""),
        "novig_type": str(extra.get("novig_type") or ""),
        "event_id": str(extra.get("event_id") or ""),
        "sports_market_type": str(extra.get("sports_market_type") or ""),
        "suffix": str(extra.get("suffix") or ""),
        "codes": [],
        "optic": {
            "home": home,
            "away": away,
            "start_date": kickoff,
            "fixture_id": str(extra.get("fixture_id") or ""),
        },
        "catalogue_seen": bool(extra.get("seen")),
    }


def _load_rows(
    source_id: str,
    event: str,
    base: str,
    *,
    query_fn: QueryFn | None,
    project: str | None,
) -> list[Any]:
    """Run the mapping SQL via inject or BigQuery."""
    params = {"id": source_id, "event": event, "base": base}
    if query_fn is not None:
        return list(query_fn(mapping_sql(project or "marketmaking-test"), params))
    proj = project or os.environ.get("GCP_PROJECT") or ""
    if not proj:
        return []
    return _bq_rows(mapping_sql(proj), params)


def _bq_rows(sql: str, params: dict[str, str]) -> list[Any]:
    """Live parameterized market_mapping read."""
    job = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, "STRING", params[name])
            for name in ("id", "event", "base")
        ]
    )
    return list(ro_query(ro_client(), sql, job_config=job))


def mapping_row(row: Any) -> dict[str, Any]:
    """Flatten a BQ row or dict into probe mapping fields."""
    if isinstance(row, dict):
        return {key: _cell(row.get(key)) for key in _KEYS}
    return {key: _cell(getattr(row, key, None)) for key in _KEYS}


def _cell(value: Any) -> str:
    """Stringify a mapping cell; None → empty."""
    if value is None:
        return ""
    return str(value).strip()


def mapping_fn_from_args(args: dict[str, Any]) -> MappingFn:
    """Live market_mapping lookup unless tests inject a catalogue/event fn."""
    fn = args.get("mapping_fn")
    if fn is not None:
        return fn
    hits = args.get("mapping_hits")
    if isinstance(hits, dict):
        return lambda source_id: list(hits.get(source_id) or [])
    if args.get("catalogue_fn") is not None:
        return lambda _source_id: []
    return lookup_mapping
