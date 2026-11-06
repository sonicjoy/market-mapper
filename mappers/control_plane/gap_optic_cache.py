"""Process-local Optic fixture cache (once per optic_league_id + horizon).

Harvest warms from ``opticodds_us.opticodds_fixtures`` (Coverage's table), then
falls back to live ``/fixtures/active`` for leagues BQ did not return.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.suggest_aliases import fetch_optic_fixtures
from mappers.shared import FIXTURE_HORIZON_HOURS

logger = logging.getLogger(__name__)

FixturesFn = Callable[..., list[dict[str, Any]]]
OpticQueryFn = Callable[[str, list[str], int], Any]

PREFETCH_WORKERS = 16
# /fixtures/active drops a fixture once it finishes, but the BQ table keeps the
# row forever. Bound the look-back to the length of an in-play game so the two
# sources agree on what "active" means.
_BACK_HOURS = 6
_ACTIVE_STATUS = ("unplayed", "live")

_CACHE: dict[tuple[str, float], list[dict[str, Any]]] = {}
_LOCK = threading.Lock()
_KEY_LOCKS: dict[tuple[str, float], threading.Lock] = {}

_FIXTURES_SQL = """
select
  coalesce(nullif(id, ''), game_id) as fixture_id,
  game_id,
  start_date,
  league.id as optic_league_id,
  home_competitors,
  away_competitors
from `{project}.opticodds_us.opticodds_fixtures`
where league.id in unnest(@optic_ids)
  and status in unnest(@active_status)
  and start_date > timestamp_sub(current_timestamp(), interval @back_hours hour)
  and start_date < timestamp_add(current_timestamp(), interval @fwd_hours hour)
"""


def optic_horizon_hours(league_row: Any | None) -> float:
    """Mapper window: tip horizon, never narrower than FIXTURE_HORIZON_HOURS."""
    tip = float(getattr(league_row, "fixture_horizon_hours", 0) or 0)
    return max(tip, FIXTURE_HORIZON_HOURS)


def cached_optic_fixtures(
    optic_league_id: str,
    *,
    horizon_hours: float = 96.0,
    fetch_fn: FixturesFn | None = None,
) -> list[dict[str, Any]]:
    """Return Optic fixtures for one league; reuse live fetches within this process.

    Injected ``fetch_fn`` (tests / overrides) is never cached so callers do not
    share stub results across leagues or tests.
    """
    if fetch_fn is not None:
        return list(fetch_fn(str(optic_league_id).strip(), horizon_hours=float(horizon_hours)))
    oid = str(optic_league_id).strip()
    hours = float(horizon_hours)
    key = (oid, hours)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    sliced = _slice_wider_cache(oid, hours)
    if sliced is not None:
        return sliced
    return _load_http(key)


def clear_optic_cache() -> None:
    """Drop cached Optic fixtures (tests / new CronJob run)."""
    with _LOCK:
        _CACHE.clear()
        _KEY_LOCKS.clear()


def tip_optic_keys(
    store: Any,
    leagues: frozenset[str] | None = None,
) -> list[tuple[str, float]]:
    """Enabled tip Optic league ids plus extras, each with the mapper horizon.

    ``leagues`` limits the result to those tip slugs (one drain league card).
    """
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    out: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        if leagues is not None and str(lg.league) not in leagues:
            continue
        horizon = optic_horizon_hours(lg)
        extra = [str(x).strip() for x in (lg.extra_optic_league_ids or [])]
        for oid in [str(lg.optic_league_id or "").strip(), *extra]:
            key = (oid, horizon)
            if oid and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def warm_optic_cache(
    store: Any,
    *,
    fetch_fn: FixturesFn | None = None,
    query_fn: OpticQueryFn | None = None,
    leagues: frozenset[str] | None = None,
) -> None:
    """Fill the process cache from BQ; HTTP only for leagues BQ missed.

    ``leagues`` warms only those tip slugs; other leagues still load on first use.
    """
    if fetch_fn is not None:
        return
    keys = tip_optic_keys(store, leagues)
    if not keys:
        return
    started = time.monotonic()
    loaded = load_optic_fixtures_from_bq(keys, query_fn=query_fn)
    missed = [(oid, hours) for oid, hours in keys if _cache_get((oid, hours)) is None]
    http_n = _prefetch_http(missed)
    logger.info(
        "pipeline gap-fix stage=optic_cache bq=%d http=%d keys=%d sec=%.1f",
        loaded, http_n, len(keys), time.monotonic() - started,
    )


def load_optic_fixtures_from_bq(
    keys: Sequence[tuple[str, float]],
    *,
    query_fn: OpticQueryFn | None = None,
    now: datetime | None = None,
) -> int:
    """Query Coverage's fixture table and write HTTP-shaped rows into the cache."""
    ids = list(dict.fromkeys(oid for oid, _hours in keys if oid))
    if not ids:
        return 0
    fwd = max(int(hours) for _oid, hours in keys)
    try:
        rows = list(
            query_fn(_FIXTURES_SQL, ids, fwd) if query_fn is not None
            else _query_fixtures(ids, fwd)
        )
    except Exception as exc:  # noqa: BLE001 — HTTP fallback still runs
        logger.warning("optic cache BQ failed: %s", str(exc)[:160])
        return 0
    clock = now if now is not None else datetime.now(UTC)
    return _fill_cache(keys, rows, clock)


def _query_fixtures(optic_ids: list[str], fwd_hours: int) -> Any:
    """Bound-parameter read of opticodds_fixtures."""
    project = os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or ""
    if not project:
        return []
    sql = _FIXTURES_SQL.format(project=project)  # nosec B608 — project is env-derived
    job = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("optic_ids", "STRING", optic_ids),
            bigquery.ArrayQueryParameter("active_status", "STRING", list(_ACTIVE_STATUS)),
            bigquery.ScalarQueryParameter("back_hours", "INT64", _BACK_HOURS),
            bigquery.ScalarQueryParameter("fwd_hours", "INT64", max(fwd_hours, 1)),
        ],
    )
    return ro_query(bigquery.Client(project=project), sql, job_config=job)


def _fill_cache(
    keys: Sequence[tuple[str, float]],
    rows: Sequence[Any],
    now: datetime,
) -> int:
    """Group BQ rows by league and store one filtered list per cache key."""
    by_oid: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for row in rows:
        oid, start, game = _game_from_bq(row)
        if oid and start is not None:
            by_oid.setdefault(oid, []).append((start, game))
    filled = 0
    with _LOCK:
        for oid, hours in keys:
            if oid not in by_oid:
                continue
            games = [g for start, g in by_oid[oid] if _in_window(start, now, hours)]
            _CACHE[(oid, float(hours))] = games
            filled += len(games)
    return filled


def _game_from_bq(row: Any) -> tuple[str, datetime | None, dict[str, Any]]:
    """HTTP-shaped fixture dict from one opticodds_fixtures row."""
    oid = str(_cell(row, "optic_league_id") or "").strip()
    fid = str(_cell(row, "fixture_id") or _cell(row, "game_id") or "").strip()
    start = _as_utc(_cell(row, "start_date"))
    game = {
        "id": fid,
        "game_id": str(_cell(row, "game_id") or fid).strip(),
        "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ") if start else "",
        "league": {"id": oid},
        "home_competitors": _competitors(_cell(row, "home_competitors")),
        "away_competitors": _competitors(_cell(row, "away_competitors")),
    }
    return oid, start, game


def _competitors(raw: Any) -> list[dict[str, str]]:
    """id / name / abbreviation from a BQ ARRAY<STRUCT> or list of dicts."""
    out: list[dict[str, str]] = []
    for item in raw or []:
        row = _as_map(item)
        cid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if cid or name:
            out.append({
                "id": cid,
                "name": name,
                "abbreviation": str(row.get("abbreviation") or "").strip(),
            })
    return out


def _prefetch_http(keys: Sequence[tuple[str, float]]) -> int:
    """Live /fixtures/active for cache misses; single-flight per key."""
    if not keys:
        return 0
    workers = min(PREFETCH_WORKERS, len(keys))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_http_one, keys))
    return len(keys)


def _http_one(item: tuple[str, float]) -> None:
    """One HTTP cache fill; a single league miss must not abort the warm."""
    oid, hours = item
    try:
        cached_optic_fixtures(oid, horizon_hours=hours)
    except Exception as exc:  # noqa: BLE001 — isolate Optic key / network
        logger.warning("optic cache HTTP %s: %s", oid, str(exc)[:160])


def _load_http(key: tuple[str, float]) -> list[dict[str, Any]]:
    """Fetch one league from Optic HTTP and cache it."""
    with _key_lock(key):
        hit = _cache_get(key)
        if hit is not None:
            return hit
        fixtures = list(fetch_optic_fixtures(key[0], horizon_hours=key[1]))
        with _LOCK:
            _CACHE[key] = fixtures
        return fixtures


def _slice_wider_cache(oid: str, hours: float) -> list[dict[str, Any]] | None:
    """Reuse a longer cached horizon instead of a second HTTP fetch."""
    with _LOCK:
        wider = [
            (cached_hours, games)
            for (cached_oid, cached_hours), games in _CACHE.items()
            if cached_oid == oid and cached_hours >= hours
        ]
    if not wider:
        return None
    _cached_hours, games = min(wider, key=lambda item: item[0])
    now = datetime.now(UTC)
    sliced = [game for game in games if _game_in_hours(game, now, hours)]
    with _LOCK:
        _CACHE[(oid, hours)] = sliced
    return sliced


def _game_in_hours(game: dict[str, Any], now: datetime, hours: float) -> bool:
    """True when the fixture start is inside this forward window (or unparseable)."""
    start = _as_utc(game.get("start_date"))
    if start is None:
        return True
    return _in_window(start, now, hours)


def _cache_get(key: tuple[str, float]) -> list[dict[str, Any]] | None:
    """Cached list, including empty, or None when the key was never written."""
    with _LOCK:
        hit = _CACHE.get(key)
        return None if hit is None else hit


def _key_lock(key: tuple[str, float]) -> threading.Lock:
    """Per-league lock so HTTP fallback does not stampede one id."""
    with _LOCK:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key] = lock
        return lock


def _in_window(start: datetime, now: datetime, horizon_hours: float) -> bool:
    """Keep fixtures inside the in-play look-back and this key's forward horizon."""
    if start < now - timedelta(hours=_BACK_HOURS):
        return False
    return start <= now + timedelta(hours=horizon_hours)


def _as_utc(value: Any) -> datetime | None:
    """BQ TIMESTAMP or ISO string → aware UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _cell(row: Any, name: str) -> Any:
    """Attribute or mapping field from a BQ row."""
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _as_map(item: Any) -> dict[str, Any]:
    """STRUCT / dict competitor cell."""
    if isinstance(item, dict):
        return item
    try:
        return dict(item)
    except (TypeError, ValueError):
        return {}
