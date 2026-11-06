"""Polymarket US symbols looked up on the public gateway — typed fields only.

A symbol (the market ``slug``) is an opaque venue id: the docs say its format
is not part of the contract, and it is never split here or anywhere else.
What we need to know about one — league, teams, kickoff, sportsMarketType —
comes from the gateway's typed fields via ``GET /v1/markets?slug=…``.

Only team-scoped markets name a league (``marketSides[].team.league``, equal
to the inner code the gateway files the event under); a player prop's sides
carry no team, so its league is unknown here.
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests

GATEWAY_BASE = os.environ.get(
    "POLYMARKET_US_GATEWAY", "https://gateway.polymarket.us",
).rstrip("/")
_HEADERS = {"User-Agent": "mmmapper/polymarket-usa-lookup"}
_BATCH = 100
# Candidate words in free text (chat): a lowercase hyphenated token. Only a
# pre-filter — the gateway decides what is a symbol.
_CANDIDATE_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", re.I)

BatchFn = Callable[[list[str]], list[dict[str, Any]] | None]

# symbol -> (fetched at, summary or None). A miss is re-asked sooner: a new
# market may be listed after it first appears on an RFQ.
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_HIT_TTL_S = 3600.0
_MISS_TTL_S = 300.0


def _cached(symbol: str, now: float) -> tuple[bool, dict[str, Any] | None]:
    """(fresh, summary) for a cached symbol."""
    entry = _cache.get(symbol)
    if entry is None:
        return False, None
    at, row = entry
    ttl = _HIT_TTL_S if row is not None else _MISS_TTL_S
    return now - at < ttl, row


def _fetch_batch(symbols: list[str]) -> list[dict[str, Any]] | None:
    """Raw gateway markets for up to ``_BATCH`` symbols; None on failure."""
    params = [("slug", s) for s in symbols] + [("limit", str(len(symbols)))]
    try:
        resp = requests.get(
            f"{GATEWAY_BASE}/v1/markets", params=params, headers=_HEADERS, timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"  polymarket_usa lookup: gateway failed ({exc})", file=sys.stderr)
        return None
    rows = payload.get("markets") if isinstance(payload, dict) else None
    return [m for m in rows or [] if isinstance(m, dict)]


def _team(team: object) -> dict[str, str] | None:
    """Identity fields of a gateway team."""
    if not isinstance(team, dict) or team.get("id") in (None, ""):
        return None
    out = {"id": str(team["id"])}
    for key in ("abbreviation", "name", "league", "ordering"):
        val = str(team.get(key) or "").strip()
        if val:
            out[key] = val
    return out


def summary(market: dict[str, Any]) -> dict[str, Any]:
    """Typed summary of one gateway market."""
    teams: list[dict[str, str]] = []
    for side in market.get("marketSides") or []:
        team = _team(side.get("team")) if isinstance(side, dict) else None
        if team is not None and all(t["id"] != team["id"] for t in teams):
            teams.append(team)
    leagues = {t["league"].casefold() for t in teams if t.get("league")}
    return {
        "slug": str(market.get("slug") or "").strip().casefold(),
        "sports_market_type": str(market.get("sportsMarketType") or "").strip(),
        "question": str(market.get("question") or "").strip(),
        "game_start": str(market.get("gameStartTime") or "").strip(),
        "active": market.get("active") is True,
        "closed": market.get("closed") is True,
        "teams": teams,
        "league": next(iter(leagues)) if len(leagues) == 1 else "",
    }


def lookup_markets(
    symbols: Iterable[str], *, batch_fn: BatchFn | None = None,
) -> dict[str, dict[str, Any]]:
    """{symbol -> typed summary} for every symbol the gateway knows (cached)."""
    fetch = batch_fn or _fetch_batch
    wanted = sorted({str(s).strip().casefold() for s in symbols if str(s).strip()})
    now = time.monotonic()
    todo = [s for s in wanted if not _cached(s, now)[0]]
    for i in range(0, len(todo), _BATCH):
        chunk = todo[i:i + _BATCH]
        rows = fetch(chunk)
        if rows is None:
            continue  # a failed call is not "unknown": retry next time
        found = {row["slug"]: row for row in (summary(m) for m in rows)}
        for sym in chunk:
            _cache[sym] = (now, found.get(sym))
    return {s: row for s in wanted if (row := _cached(s, now)[1]) is not None}


def lookup_market(symbol: str) -> dict[str, Any] | None:
    """Typed summary of one symbol, or None when the gateway does not know it."""
    return lookup_markets([symbol]).get(str(symbol).strip().casefold())


def find_us_symbol(text: str) -> str:
    """First word of ``text`` that the gateway knows as a symbol, else ''."""
    words = [w.casefold() for w in _CANDIDATE_RE.findall(text or "")]
    if not words:
        return ""
    known = lookup_markets(words)
    return next((w for w in words if w in known), "")


def clear_cache() -> None:
    """Forget cached lookups (tests)."""
    _cache.clear()
