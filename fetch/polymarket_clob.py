"""Cursor-paginate the Polymarket CLOB /markets endpoint — the reliable "all tokens" source.

Gamma's /markets offset-paging caps at ~2000 and its date filters are unreliable, so it
cannot enumerate every Polymarket market. The CLOB /markets endpoint uses an opaque
``next_cursor`` (no cap) and is token-native: each market lists its ``tokens`` with a
resolved ``price`` + ``winner`` flag, plus ``closed`` / ``end_date_iso`` / ``is_50_50_outcome``.
Used by the token-resolution loader to record every token's final settled price.

Markets come back oldest-first, so a full sweep pages the whole history; the loader filters
to the window it wants. No BigQuery here. Mirrors fetch/kalshi_all.py conventions.
"""

import base64
import os
import sys
import time

import requests

CLOB_BASE = os.environ.get("POLYMARKET_CLOB_API", "https://clob.polymarket.com").rstrip("/")

# CLOB returns this base64 sentinel ("-1") as next_cursor once the last page is reached.
_END_CURSOR = "LTE="
_FETCH_RETRIES = 4
_BACKOFF_SECONDS = 1.0


def _get_page(cursor: str, base_url: str, timeout: int = 30) -> dict:
    """GET one /markets page (optionally at ``cursor``), retrying transient errors."""
    params = {"next_cursor": cursor} if cursor else {}
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(f"{base_url}/markets", params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # flaky 429/5xx, timeout, JSON
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS * (2**attempt))
    raise last_err  # type: ignore[misc]


def normalize_clob_market(m: dict) -> dict:
    """Flatten one raw CLOB market to the token-level shape the loader consumes."""
    return {
        "condition_id": str(m.get("condition_id") or ""),
        "closed": bool(m.get("closed")),
        "end_date_iso": m.get("end_date_iso") or None,
        "is_50_50": bool(m.get("is_50_50_outcome")),
        "slug": m.get("market_slug") or "",
        "question": m.get("question") or "",
        "tokens": [
            {
                "token_id": str(t.get("token_id") or ""),
                "outcome": t.get("outcome"),
                "price": t.get("price"),
                "winner": bool(t.get("winner")),
            }
            for t in (m.get("tokens") or [])
        ],
    }


def _offset_cursor(offset: int) -> str:
    """CLOB's next_cursor is base64(str(offset)); build one to seek to ``offset``."""
    return base64.b64encode(str(offset).encode()).decode()


def iter_markets(base_url: str = CLOB_BASE, max_pages: int = 5000, start_offset: int = 0):
    """Yield normalized CLOB markets, cursor-paginating to the end. Progress -> stderr.

    ``start_offset`` seeks past the oldest markets (markets are oldest-first, so recent
    ones sit at high offsets) — lets a steady-state run skip ancient history instead of
    paging all ~1M+ markets every time.
    """
    cursor = _offset_cursor(start_offset) if start_offset else ""
    for page_no in range(max_pages):
        data = _get_page(cursor, base_url)
        page = data.get("data") or []
        for m in page:
            yield normalize_clob_market(m)
        if page_no % 20 == 0:
            print(f"  clob page {page_no}: {len(page)} markets (cursor={str(cursor)[:12]})", file=sys.stderr)
        cursor = data.get("next_cursor")
        if not page or not cursor or cursor == _END_CURSOR:
            break
