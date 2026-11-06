"""Kalshi's public market listing for one goalscorer event."""

from __future__ import annotations

import logging

import requests

from goalscorer.config import KALSHI_API

logger = logging.getLogger(__name__)

# An event lists a few dozen players; this covers it in one page.
_PAGE_LIMIT = 1000
# Market statuses once trading has stopped.
_CLOSED = frozenset({"closed", "determined", "disputed", "amended", "finalized", "settled"})


def player_name(market: dict) -> str:
    """Player a goal market is on: 'Jorgen Strand Larsen: 1+' → 'Jorgen Strand Larsen'."""
    label = market.get("yes_sub_title") or market.get("title") or ""
    return label.split(":")[0].strip()


def event_players(event_ticker: str) -> dict[str, str] | None:
    """ticker → player name for every market on the event; None if Kalshi didn't answer.

    {} before Kalshi lists the event and once every market on it has closed:
    a closed event lists nothing new, so there is nothing left to move onto.
    """
    try:
        resp = requests.get(
            f"{KALSHI_API}/markets", params={"event_ticker": event_ticker, "limit": _PAGE_LIMIT}, timeout=10
        )
        resp.raise_for_status()
        markets = resp.json().get("markets") or []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("kalshi listing failed for %s: %s", event_ticker, exc)
        return None
    if all(m.get("status") in _CLOSED for m in markets):
        return {}
    return {m["ticker"]: player_name(m) for m in markets if m.get("ticker")}
