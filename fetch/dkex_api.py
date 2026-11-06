"""DKEX REST v0.6.1: ticker discovery + batch market metadata."""

from __future__ import annotations

import sys
from typing import Any

import requests

API_PAGE_SIZE = 1000
BATCH_SIZE = 1000
BATCH_PATH = "/api/v1/markets/queries"
COMBO_BATCH_PATH = "/api/v1/combos/queries"
MAX_TRIES = 3


def page_market_tickers(
    session: requests.Session,
    base: str,
    statuses: tuple[str, ...],
    *,
    topic: str = "Sports",
) -> list[str]:
    """Page ``GET /api/v1/markets``; each row is a ticker string."""
    tickers: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": API_PAGE_SIZE, "topic": topic}
        if statuses:
            params["status"] = list(statuses)
        if cursor:
            params["cursor"] = cursor
        payload = _get_json(session, f"{base}/api/v1/markets", params)
        batch = payload.get("markets") or []
        for item in batch:
            if isinstance(item, str) and item.strip():
                tickers.append(item.strip())
            elif isinstance(item, dict):
                text = str(item.get("ticker") or item.get("marketTicker") or "").strip()
                if text:
                    tickers.append(text)
        cursor = payload.get("nextCursor")
        if not cursor or not batch:
            break
    return tickers


def page_combos(
    session: requests.Session,
    base: str,
    statuses: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Page ``GET /api/v1/combos``.

    Rows that already include ``legs`` are kept. Bare tickers are returned
    for a follow-up ``POST /api/v1/combos/queries``.
    """
    complete: list[dict[str, Any]] = []
    bare: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": API_PAGE_SIZE}
        if statuses:
            params["status"] = list(statuses)
        if cursor:
            params["cursor"] = cursor
        payload = _get_json(session, f"{base}/api/v1/combos", params)
        batch = payload.get("combos") or payload.get("tickers") or []
        for item in batch:
            if isinstance(item, str) and item.strip():
                bare.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            row = _unwrap_market(item)
            ticker = str(row.get("ticker") or row.get("marketTicker") or "").strip()
            if row.get("legs"):
                if ticker and "ticker" not in row:
                    row = {**row, "ticker": ticker}
                complete.append(row)
            elif ticker:
                bare.append(ticker)
        cursor = payload.get("nextCursor")
        if not cursor or not batch:
            break
    return complete, bare


def fetch_combo_metadata(
    session: requests.Session,
    base: str,
    tickers: list[str],
) -> list[dict[str, Any]]:
    """``POST /api/v1/combos/queries`` — same body as the markets batch."""
    combos: list[dict[str, Any]] = []
    for start in range(0, len(tickers), BATCH_SIZE):
        chunk = tickers[start : start + BATCH_SIZE]
        payload = _post_json(
            session,
            f"{base}{COMBO_BATCH_PATH}",
            {"tickers": chunk},
        )
        rows = payload.get("combos") or payload.get("markets") or []
        for row in rows:
            if isinstance(row, dict):
                combos.append(_unwrap_market(row))
    return combos


def fetch_market_metadata(
    session: requests.Session,
    base: str,
    tickers: list[str],
    missing: list[str] | None = None,
) -> list[dict[str, Any]]:
    """``POST /api/v1/markets/queries`` in batches of 1000.

    When ``missing`` is given, each batch's ``missingTickers`` is appended to it.
    """
    markets: list[dict[str, Any]] = []
    for start in range(0, len(tickers), BATCH_SIZE):
        chunk = tickers[start : start + BATCH_SIZE]
        payload = _post_json(
            session,
            f"{base}{BATCH_PATH}",
            {"tickers": chunk},
        )
        for row in payload.get("markets") or []:
            if isinstance(row, dict):
                markets.append(_unwrap_market(row))
        if missing is not None:
            missing.extend(str(t) for t in payload.get("missingTickers") or [])
    return markets


def fetch_single_market(
    session: requests.Session, base: str, ticker: str
) -> dict[str, Any] | None:
    """``GET /api/v1/markets/{ticker}``; None unless it returns a market."""
    url = f"{base}/api/v1/markets/{ticker}"
    for attempt in range(1, MAX_TRIES + 1):
        resp = session.get(url, timeout=60)
        if resp.status_code == 200:
            row = resp.json().get("market")
            return _unwrap_market(row) if isinstance(row, dict) else None
        if attempt == MAX_TRIES or resp.status_code < 500:
            return None
    return None


def _unwrap_market(row: dict[str, Any]) -> dict[str, Any]:
    inner = row.get("market")
    if isinstance(inner, dict):
        return inner
    return row


def _get_json(session: requests.Session, url: str, params: dict) -> dict:
    for attempt in range(1, MAX_TRIES + 1):
        resp = session.get(url, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if attempt == MAX_TRIES or resp.status_code < 500:
            sys.exit(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
    return {}


def _post_json(session: requests.Session, url: str, body: dict) -> dict:
    for attempt in range(1, MAX_TRIES + 1):
        resp = session.post(url, json=body, timeout=120)
        if resp.status_code == 200:
            return resp.json()
        if attempt == MAX_TRIES or resp.status_code < 500:
            sys.exit(f"POST {url} -> {resp.status_code}: {resp.text[:300]}")
    return {}
