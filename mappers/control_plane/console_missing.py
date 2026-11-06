"""Explore → Missing: catalogue symbols absent from market_mapping."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from BigQuery.client import ro_client, ro_query
from BigQuery.crypto_gap_config import all_gap_leagues
from mappers.control_plane.console_missing_catalogue import (
    sport_crypto_prefixes,
    tip_league_catalogue_keys,
)
from mappers.control_plane.console_missing_local import (
    is_local_missing_project,
    load_missing_local_jsonl,
    missing_local_path,
)
from mappers.control_plane.console_missing_sql import crypto_missing_sql
from mappers.control_plane.console_missing_txodds import (
    TXODDS_NOTE,
    TXODDS_PLATFORM,
    CatalogueUnavailableError,
    fetch_txodds_missing,
    normalize_txodds_row,
)
from mappers.control_plane.console_platforms import (
    default_missing_platform_id,
    explore_platform,
)
from mappers.control_plane.console_unmapped import build_unmapped_tip_index
from mappers.crypto_meta import narrow_crypto_leagues

MissingFetchFn = Callable[[], list[dict[str, Any]]]

_CACHE_TTL_SEC = 15 * 60
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _project() -> str:
    """Console default GCP project from env."""
    return (os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID") or "").strip()


def _missing_bq_project() -> str:
    """BQ project for catalogue anti-join (may differ from console GCP_PROJECT)."""
    override = (os.environ.get("MAPPING_MISSING_BQ_PROJECT") or "").strip()
    return override or _project()


def _missing_dev_row_cap() -> int | None:
    """Optional LIMIT for local dev (MAPPING_MISSING_DEV_MAX_ROWS)."""
    raw = (os.environ.get("MAPPING_MISSING_DEV_MAX_ROWS") or "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def _kickoff_iso(value: Any) -> str | None:
    """Format kickoff for API JSON."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    text = str(value).strip()
    return text or None


def _ttko_hours(kickoff: datetime | None) -> float | None:
    """Hours from now until kickoff (negative after start)."""
    if kickoff is None:
        return None
    dt = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=UTC)
    return (dt.astimezone(UTC) - datetime.now(UTC)).total_seconds() / 3600.0


def _prefix_slugs() -> dict[str, list[str]]:
    """Map NX catalogue token → tip league slug(s)."""
    out: dict[str, list[str]] = {}
    for gap in all_gap_leagues():
        token = gap.league_prefix.removeprefix("NX.F.OPT.")
        out.setdefault(token, []).append(gap.league_key)
    return out


def _infer_league(
    crypto_prefix: str,
    meta_league: str,
    index: dict[str, Any],
    prefix_map: dict[str, list[str]],
) -> tuple[str, str]:
    """Resolve one tip league slug + sport from NX token and meta_league."""
    slugs = list(prefix_map.get(crypto_prefix, []))
    if not slugs:
        return "", ""
    league_rows = []
    rid = index.get("rule_set_id")
    store = index.get("store")
    if rid and store is not None and hasattr(store, "leagues_for"):
        league_rows = list(store.leagues_for(rid))
    narrowed = narrow_crypto_leagues(slugs, meta_league, league_rows)
    if len(narrowed) != 1:
        return "", ""
    slug = narrowed[0]
    sport = ""
    for row in league_rows:
        if str(row.league) == slug:
            sport = str(row.sport or "")
            break
    return slug, sport


def _parse_row_kickoff(raw: dict[str, Any]) -> datetime | None:
    """Parse kickoff from a catalogue or JSONL row."""
    kickoff = raw.get("kickoff")
    if isinstance(kickoff, datetime):
        return kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=UTC)
    if isinstance(kickoff, str) and kickoff.strip():
        try:
            parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _normalize_bq_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one BQ/JSONL catalogue row to console API shape."""
    kick_dt = _parse_row_kickoff(raw)
    return {
        "platform": "crypto",
        "symbol": str(raw.get("symbol") or ""),
        "symbol_base": str(raw.get("symbol_base") or ""),
        "fixture_prefix": str(raw.get("fixture_prefix") or ""),
        "crypto_prefix": str(raw.get("crypto_prefix") or ""),
        "market_group": str(raw.get("market_group") or ""),
        "contract_type": str(raw.get("contract_type") or ""),
        "period_type": str(raw.get("period_type") or ""),
        "fixture_name": str(raw.get("meta_name") or ""),
        "meta_league": str(raw.get("meta_league") or ""),
        "scope": str(raw.get("scope") or "extra"),
        "kickoff": _kickoff_iso(kick_dt),
        "ttko_hours": _ttko_hours(kick_dt),
        "league": "",
        "sport": "",
    }


def _enrich_rows(rows: list[dict[str, Any]], store: Any | None) -> list[dict[str, Any]]:
    """Attach tip league/sport for the current page slice."""
    index = build_unmapped_tip_index(store)
    index["store"] = store
    index["rule_set_id"] = getattr(store, "current_rule_set_id", None) if store else None
    prefix_map = _prefix_slugs()
    out: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        if row.get("platform") != "crypto":  # other catalogues carry their own league/sport
            out.append(enriched)
            continue
        slug, sport = _infer_league(
            str(row.get("crypto_prefix") or ""),
            str(row.get("meta_league") or ""),
            index,
            prefix_map,
        )
        enriched["league"] = slug
        enriched["sport"] = sport or _crypto_sport_token(str(row.get("crypto_prefix") or ""))
        out.append(enriched)
    return out


def _crypto_sport_token(token: str) -> str:
    """Fallback sport label from NX token when tip league is ambiguous."""
    low = token.lower()
    if low in {"fifa", "soccer"}:
        return "soccer"
    if low == "tennis":
        return "tennis"
    return low


def _default_crypto_fetch() -> list[dict[str, Any]]:
    """Load missing catalogue from local JSONL or BigQuery."""
    project = _missing_bq_project()
    if is_local_missing_project(project):
        return load_missing_local_jsonl()
    if not project:
        raise RuntimeError("GCP_PROJECT is not set")
    client = ro_client()
    rows = ro_query(client, crypto_missing_sql(project, row_cap=_missing_dev_row_cap()))
    return [dict(r) for r in rows]


def _default_txodds_fetch() -> list[dict[str, Any]]:
    """TxODDS fixtures the fixture map could not join (see console_missing_txodds)."""
    return fetch_txodds_missing(_missing_bq_project())


_CATALOGUE_NOTE = "Catalogue minus market_mapping — not RFQ demand."
_CATALOGUE_NOTES = {TXODDS_PLATFORM: TXODDS_NOTE}

# Per-platform catalogue source and row normaliser. A platform missing here has no catalogue.
_FETCHERS: dict[str, MissingFetchFn] = {"crypto": _default_crypto_fetch, TXODDS_PLATFORM: _default_txodds_fetch}
_NORMALIZERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {TXODDS_PLATFORM: normalize_txodds_row}


def _cached_rows(platform: str, fetch_fn: MissingFetchFn, refresh: bool) -> tuple[list[dict[str, Any]], float | None]:
    """Fetch and normalize catalogue rows with a short TTL cache."""
    now = time.monotonic()
    hit = _cache.get(platform)
    if not refresh and hit is not None and now - hit[0] < _CACHE_TTL_SEC:
        return hit[1], now - hit[0]
    raw = fetch_fn()
    normalize = _NORMALIZERS.get(platform, _normalize_bq_row)
    normalized = [normalize(row) for row in raw]
    _cache[platform] = (now, normalized)
    return normalized, 0.0


def parse_window_bound(raw: str | None, name: str) -> datetime | None:
    """Parse one kickoff window bound (ISO; naive means UTC)."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is not an ISO datetime: {text!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def contract_type_set(contract_type: str | list[str] | None) -> set[str]:
    """Lower-cased market names to keep; empty means all."""
    values = [contract_type] if isinstance(contract_type, str) else list(contract_type or [])
    return {v.strip().lower() for v in values if v and v.strip()}


def _apply_kickoff_window(
    rows: list[dict[str, Any]],
    kickoff_from: datetime | None,
    kickoff_to: datetime | None,
) -> list[dict[str, Any]]:
    """Keep rows kicking off inside [from, to]; rows with no kickoff drop once a bound is set."""
    if kickoff_from is None and kickoff_to is None:
        return rows
    out = []
    for row in rows:
        kick = _parse_row_kickoff(row)
        if kick is None:
            continue
        if kickoff_from is not None and kick < kickoff_from:
            continue
        if kickoff_to is not None and kick > kickoff_to:
            continue
        out.append(row)
    return out


def _market_options(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distinct market names (contract_type) with row counts, most rows first."""
    counts: dict[str, int] = {}
    for row in rows:
        name = str(row.get("contract_type") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return [
        {"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    ]


def _apply_filters(
    rows: list[dict[str, Any]],
    *,
    league: str | None,
    sport: str | None,
    scope: str | None,
    market_group: str | None,
    q: str | None,
    window: tuple[datetime | None, datetime | None],
    store: Any | None,
) -> list[dict[str, Any]]:
    """Filter in-memory catalogue rows on everything except market name (platform is checked by the caller)."""
    if rows and rows[0].get("platform") not in ("crypto", None):
        return _apply_plain_filters(rows, league=league, sport=sport, scope=scope, q=q, window=window)
    out = rows
    if league:
        token, meta = tip_league_catalogue_keys(store, league)
        if token:
            out = [r for r in out if str(r.get("crypto_prefix") or "") == token]
            if meta:
                want_meta = meta.upper()
                out = [r for r in out if str(r.get("meta_league") or "").upper() == want_meta]
    if sport:
        prefixes = sport_crypto_prefixes(store, sport)
        if prefixes:
            out = [r for r in out if str(r.get("crypto_prefix") or "") in prefixes]
    if scope and scope != "all":
        out = [r for r in out if str(r.get("scope") or "") == scope]
    if market_group:
        want = market_group.strip().lower()
        out = [r for r in out if str(r.get("market_group") or "").lower() == want]
    out = _apply_kickoff_window(out, *window)
    if q:
        needle = q.strip().lower()
        out = [
            r
            for r in out
            if needle in str(r.get("symbol") or "").lower()
            or needle in str(r.get("fixture_name") or "").lower()
            or needle in str(r.get("crypto_prefix") or "").lower()
        ]
    return out


def _apply_plain_filters(
    rows: list[dict[str, Any]],
    *,
    league: str | None,
    sport: str | None,
    scope: str | None,
    q: str | None,
    window: tuple[datetime | None, datetime | None],
) -> list[dict[str, Any]]:
    """Filters for catalogues whose rows already carry league/sport (no NX token inference)."""
    out = [r for r in rows if not league or r.get("league") == league]
    out = [r for r in out if not sport or r.get("sport") == sport]
    out = [r for r in out if not scope or scope == "all" or r.get("scope") == scope]
    out = _apply_kickoff_window(out, *window)
    needle = (q or "").strip().lower()
    if needle:
        out = [r for r in out if needle in f"{r.get('symbol', '')} {r.get('fixture_name', '')}".lower()]
    return out


def _sort_rows(rows: list[dict[str, Any]], sort: str, sort_dir: str) -> None:
    """Sort catalogue rows in place (symbol, league, or kickoff)."""
    reverse = sort_dir.lower() == "desc"
    key = sort.strip().lower()
    if key == "symbol":
        rows.sort(key=lambda r: str(r.get("symbol") or ""), reverse=reverse)
    elif key == "league":
        rows.sort(
            key=lambda r: (str(r.get("league") or ""), str(r.get("symbol") or "")),
            reverse=reverse,
        )
    else:
        rows.sort(
            key=lambda r: (r.get("ttko_hours") is None, r.get("ttko_hours") or 99999.0),
            reverse=reverse,
        )


def _unwired_missing_payload(label: str, limit: int, offset: int, note: str = "") -> dict[str, Any]:
    """Response when the platform has no missing-catalogue inventory (or cannot read it here)."""
    return {
        "count": 0,
        "limit": limit,
        "offset": offset,
        "page": 0,
        "rows": [],
        "market_options": [],
        "cache_age_sec": None,
        "refreshed_at": None,
        "note": f"{label} {note}" if note else f"Missing catalogue inventory is not wired for {label} yet.",
        "error": None,
    }


def _fetch_missing_catalogue_rows(
    book: str,
    *,
    fetch_fn: MissingFetchFn | None,
    refresh: bool,
) -> tuple[list[dict[str, Any]], float | None, str]:
    """Load raw catalogue rows; empty list + error message on fetch failure.

    CatalogueUnavailableError is re-raised: the caller shows the unwired state, not an error.
    """
    try:
        fetch = fetch_fn or _FETCHERS.get(book, _default_crypto_fetch)
        raw, cache_age = _cached_rows(book, fetch, refresh=refresh)
        return raw, cache_age, ""
    except CatalogueUnavailableError:
        raise
    except Exception as exc:
        return [], None, str(exc)


def _missing_symbols_payload(
    *,
    rows: list[dict[str, Any]],
    total: int,
    page_size: int,
    page_offset: int,
    refresh: bool,
    cache_age: float | None = None,
    error: str = "",
    market_options: list[dict[str, Any]] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Assemble list_missing_symbols response body."""
    return {
        "count": total,
        "limit": page_size,
        "offset": page_offset,
        "page": page_offset // page_size if page_size else 0,
        "rows": rows,
        "market_options": market_options or [],
        "cache_age_sec": round(cache_age, 1) if cache_age is not None else None,
        "refreshed_at": datetime.now(UTC).isoformat() if refresh else None,
        "note": note or _CATALOGUE_NOTE,
        "bq_project": _missing_bq_project() or None,
        "local_path": str(missing_local_path()) if is_local_missing_project(_missing_bq_project()) else None,
        "error": error or None,
    }


def _pick_markets(rows: list[dict[str, Any]], contract_type: str | list[str] | None) -> list[dict[str, Any]]:
    """Rows whose market name (contract_type) is one of the picked names; none picked keeps all."""
    wanted = contract_type_set(contract_type)
    if not wanted:
        return list(rows)
    return [r for r in rows if str(r.get("contract_type") or "").strip().lower() in wanted]


# ``contract_type`` is the market-name filter (any of). ``market_options`` lists the
# market names left after every *other* filter, so picking one market does not
# collapse the picker to that one name.
def list_missing_symbols(
    *,
    platform: str | None = None,
    league: str | None = None,
    sport: str | None = None,
    scope: str = "all",
    market_group: str | None = None,
    contract_type: str | list[str] | None = None,
    q: str | None = None,
    kickoff_from: str | None = None,
    kickoff_to: str | None = None,
    sort: str = "kickoff",
    sort_dir: str = "asc",
    limit: int = 100,
    offset: int = 0,
    refresh: bool = False,
    store: Any | None = None,
    fetch_fn: MissingFetchFn | None = None,
) -> dict[str, Any]:
    """Catalogue symbols with no market_mapping row for the selected platform."""
    plat = explore_platform(platform or default_missing_platform_id())
    if plat is None or not plat.missing_catalogue:
        return _unwired_missing_payload(plat.label if plat is not None else (platform or "?"), limit, offset)
    page_size, page_offset = max(1, min(limit, 500)), max(0, offset)
    try:
        window = (parse_window_bound(kickoff_from, "kickoff_from"), parse_window_bound(kickoff_to, "kickoff_to"))
    except ValueError as exc:
        return _missing_symbols_payload(
            rows=[], total=0, page_size=page_size, page_offset=page_offset, refresh=refresh, error=str(exc)
        )
    try:
        raw, cache_age, error = _fetch_missing_catalogue_rows(plat.id, fetch_fn=fetch_fn, refresh=refresh)
    except CatalogueUnavailableError as exc:
        return _unwired_missing_payload(plat.label, limit, offset, f"catalogue is not readable here: {exc}")
    faceted = _apply_filters(
        raw, league=league, sport=sport, scope=scope, market_group=market_group, q=q, window=window, store=store
    )
    filtered = _pick_markets(faceted, contract_type)
    _sort_rows(filtered, sort, sort_dir)
    return _missing_symbols_payload(
        rows=_enrich_rows(filtered[page_offset : page_offset + page_size], store),
        total=len(filtered),
        page_size=page_size,
        page_offset=page_offset,
        refresh=refresh,
        cache_age=cache_age,
        error=error,
        market_options=_market_options(faceted),
        note=_CATALOGUE_NOTES.get(plat.id, _CATALOGUE_NOTE),
    )
