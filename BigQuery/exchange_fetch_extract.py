"""Extract index keys from fetch JSONL lines for exchange_fetch_raw tables."""

from __future__ import annotations

import json
from typing import Any


def _loads(line: str) -> dict[str, Any] | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def optic_keys(line: str) -> tuple[str | None, str | None]:
    obj = _loads(line)
    if obj is None:
        return None, None
    league = obj.get("league") or {}
    league_id = league.get("id") if isinstance(league, dict) else None
    game_id = obj.get("id")
    if game_id is not None:
        game_id = str(game_id)
    return (
        str(league_id) if league_id is not None else None,
        game_id,
    )


def kalshi_keys(line: str) -> tuple[str | None, str | None]:
    """(sport, event_ticker) from a Kalshi fetch line's typed fields."""
    obj = _loads(line)
    if obj is None:
        return None, None
    sport = obj.get("sport")
    event_ticker = obj.get("event_ticker")
    return (
        str(sport) if sport else None,
        str(event_ticker) if event_ticker else None,
    )


def polymarket_keys(line: str) -> tuple[str | None, str | None]:
    obj = _loads(line)
    if obj is None:
        return None, None
    slug = obj.get("slug")
    if not slug:
        return None, None
    slug = str(slug)
    # legacy: ticker parse — replace with the typed venue field, do not extend
    slug_prefix = slug.split("-", 1)[0]
    cond = obj.get("condition_id")
    return slug_prefix, str(cond) if cond is not None else None


def crypto_keys(line: str) -> str | None:
    obj = _loads(line)
    if obj is None:
        return None
    league = obj.get("league")
    return str(league) if league is not None else None


def novig_keys(line: str, kind: str) -> str | None:
    obj = _loads(line)
    if obj is None:
        return None
    league = obj.get("league")
    return str(league) if league is not None else None


def px_event_keys(line: str) -> tuple[str | None, str | None]:
    obj = _loads(line)
    if obj is None:
        return None, None
    tid = obj.get("tournament_id")
    eid = obj.get("id") or obj.get("event_id")
    return (
        str(tid) if tid is not None else None,
        str(eid) if eid is not None else None,
    )


def px_market_keys(line: str) -> tuple[str | None, str | None]:
    obj = _loads(line)
    if obj is None:
        return None, None
    tid = obj.get("tournament_id")
    mid = obj.get("id") or obj.get("market_id")
    return (
        str(tid) if tid is not None else None,
        str(mid) if mid is not None else None,
    )


def polymarket_usa_keys(line: str) -> tuple[str | None, str | None, str | None]:
    """(gateway league id, event ticker, market symbol) from a structured line.

    Read from the fetcher's typed fields, never split out of the symbol.
    """
    obj = _loads(line)
    if obj is None:
        return None, None, None
    raw = obj.get("league_id")
    league = str(raw) if isinstance(raw, int) and not isinstance(raw, bool) else None
    event = str(obj.get("event_ticker") or "").strip().casefold() or None
    slug = str(obj.get("slug") or "").strip().casefold() or None
    return league, event, slug


def polymarket_usa_side_ids(line: str) -> list[str]:
    """Venue side ids of a structured market line (one BQ row per side)."""
    obj = _loads(line)
    if obj is None:
        return []
    return [
        str(side.get("id"))
        for side in obj.get("sides") or []
        if isinstance(side, dict) and side.get("id") not in (None, "")
    ]


def sxbet_keys(line: str) -> tuple[str | None, str | None, str | None]:
    """(leagueId, sportXeventId, lowercase marketHash) of one SX ``/markets/active`` row."""
    obj = _loads(line)
    if obj is None:
        return None, None, None
    league = obj.get("leagueId")
    event = obj.get("sportXeventId")
    mh = obj.get("marketHash")
    return (
        str(league) if league is not None else None,
        str(event) if event is not None else None,
        str(mh).lower() if mh else None,
    )


def stx_keys(line: str) -> tuple[str | None, str | None]:
    """(event id, market id) of one STX market line; a roster body has only the event id."""
    obj = _loads(line)
    if obj is None:
        return None, None
    event, market = obj.get("event_id"), obj.get("market_id")
    return (str(event) if event else None, str(market) if market else None)


def underdog_keys(line: str) -> tuple[str | None, str | None, str | None]:
    """(series ticker, event ticker, market ticker) of one UDX ``/markets`` row."""
    obj = _loads(line)
    if obj is None:
        return None, None, None
    return (
        str(obj.get("series_ticker") or "") or None,
        str(obj.get("event_ticker") or "") or None,
        str(obj.get("ticker") or "") or None,
    )
