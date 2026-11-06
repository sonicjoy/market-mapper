"""Batch ``crypto_security_def`` lookups for gap harvest.

Chat still probes one symbol; harvest passes the tick's NX keys so one BQ job
covers the walk instead of one job per symbol.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.client import CRYPTO_SECURITY_DEF_TABLE, ro_client, ro_query

logger = logging.getLogger(__name__)

CatalogueFn = Callable[[str], dict[str, Any]]

_MATURITY = re.compile(r"\.\d{8}$")

_CATALOGUE_SQL = """
select
  symbol,
  regexp_replace(symbol, r'\\.[0-9]{8}$', '') as base,
  meta_predict_market_type as market_type,
  meta_predict_contract_type as contract_type,
  meta_name,
  meta_event_date,
  meta_league,
  cast(meta_external_home_id as string) as home_id,
  cast(meta_external_away_id as string) as away_id,
  meta_home_participant as home_name,
  meta_away_participant as away_name,
  cast(meta_player_id as string) as player_id,
  meta_participant as player_name,
  publish_time
from `{table}`
where symbol in unnest(@syms)
qualify row_number() over (partition by symbol order by publish_time desc) = 1
"""


def prefetch_crypto_catalogue(
    symbols: Sequence[str],
    *,
    query_fn: Callable[[list[str]], Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Latest catalogue row per requested symbol (exact match, else maturity base)."""
    keys = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
    if not keys:
        return {}
    started = time.monotonic()
    try:
        rows = list(_fetch_exact(keys, query_fn))
        rows.extend(_fetch_bases(keys, rows, query_fn))
    except Exception as exc:  # noqa: BLE001 — harvest falls back to per-symbol
        logger.warning("crypto catalogue BQ failed: %s", str(exc)[:160])
        return {}
    out = _assign_rows(keys, rows)
    logger.info(
        "pipeline gap-fix stage=crypto_catalogue symbols=%d hits=%d sec=%.1f",
        len(keys),
        sum(1 for row in out.values() if row.get("seen")),
        time.monotonic() - started,
    )
    return out


def batched_catalogue_fn(
    symbols: Sequence[str],
    *,
    query_fn: Callable[[list[str]], Any] | None = None,
) -> CatalogueFn | None:
    """Lookup closure over one prefetch, or None when BQ returned nothing."""
    cache = prefetch_crypto_catalogue(symbols, query_fn=query_fn)
    if not cache:
        return None
    return lambda symbol: cache.get(symbol) or _miss(symbol)


def catalogue_lookup(symbol: str) -> dict[str, Any]:
    """One-symbol live lookup (Mapper Chat). Same SQL as the harvest batch."""
    cache = prefetch_crypto_catalogue([symbol])
    return cache.get(symbol) or _miss(symbol)


def _fetch_exact(
    keys: list[str],
    query_fn: Callable[[list[str]], Any] | None,
) -> Any:
    """Exact-symbol catalogue rows."""
    return query_fn(keys) if query_fn is not None else _query(keys)


def _fetch_bases(
    keys: list[str],
    exact_rows: Sequence[Any],
    query_fn: Callable[[list[str]], Any] | None,
) -> list[Any]:
    """Second query: maturity-stripped bases for keys the exact lookup missed."""
    have = {str(_cell(row, "symbol") or "") for row in exact_rows}
    bases = list(dict.fromkeys(
        _MATURITY.sub("", key) for key in keys if key not in have
    ))
    bases = [base for base in bases if base and base not in have]
    if not bases:
        return []
    return list(query_fn(bases) if query_fn is not None else _query(bases))


def _query(syms: list[str]) -> Any:
    """Bound-parameter read of crypto_security_def (exact symbols only)."""
    sql = _CATALOGUE_SQL.replace("{table}", CRYPTO_SECURITY_DEF_TABLE)
    job = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("syms", "STRING", syms),
        ],
    )
    return ro_query(ro_client(), sql, job_config=job)


def _assign_rows(keys: list[str], rows: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Prefer exact symbol, else stripped maturity base; latest publish_time."""
    by_sym: dict[str, Any] = {}
    by_base: dict[str, Any] = {}
    for row in rows:
        _keep_latest(by_sym, str(_cell(row, "symbol") or ""), row)
        _keep_latest(by_base, str(_cell(row, "base") or ""), row)
    out: dict[str, dict[str, Any]] = {}
    for key in keys:
        row = by_sym.get(key) or by_base.get(_MATURITY.sub("", key))
        out[key] = _row_to_cat(key, row) if row is not None else _miss(key)
    return out


def _keep_latest(bucket: dict[str, Any], key: str, row: Any) -> None:
    """Keep the row with the newest publish_time for this key."""
    if not key:
        return
    prev = bucket.get(key)
    if prev is None or _publish(row) >= _publish(prev):
        bucket[key] = row


def _publish(row: Any) -> float:
    """Epoch seconds for latest-row; unusable publish_time sorts first.

    Never mixes types: one NULL alongside a TIMESTAMP would otherwise raise
    from :func:`_assign_rows`, which runs outside the query's error handling.
    """
    value = _cell(row, "publish_time")
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=UTC)
        return stamp.timestamp()
    text = str(value or "").strip()
    if not text:
        return float("-inf")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _row_to_cat(symbol: str, row: Any) -> dict[str, Any]:
    """Flatten one security_def row into the probe catalogue dict."""
    return {
        "ok": True,
        "seen": True,
        "symbol": str(_cell(row, "symbol") or symbol),
        "market_type": _text(_cell(row, "market_type")),
        "contract_type": _text(_cell(row, "contract_type")),
        "meta_name": _text(_cell(row, "meta_name")),
        "meta_event_date": _text(_cell(row, "meta_event_date")),
        "meta_league": _text(_cell(row, "meta_league")),
        "home_id": _text(_cell(row, "home_id")),
        "away_id": _text(_cell(row, "away_id")),
        "home_name": _text(_cell(row, "home_name")),
        "away_name": _text(_cell(row, "away_name")),
        "player_id": _text(_cell(row, "player_id")),
        "player_name": _text(_cell(row, "player_name")),
    }


def _miss(symbol: str) -> dict[str, Any]:
    """Soft miss matching the previous per-symbol catalogue shape."""
    return {"ok": True, "seen": False, "symbol": symbol}


def _cell(row: Any, name: str) -> Any:
    """Attribute or mapping field from a BQ row."""
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _text(value: Any) -> str:
    """Stringify a catalogue cell; None → empty."""
    if value is None:
        return ""
    return str(value).strip()
