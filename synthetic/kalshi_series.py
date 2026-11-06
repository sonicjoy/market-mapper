"""Kalshi market listing for the synthetic-fixture job.

The job lists open markets for each exact series ticker in series.toml.
The ticker is passed to Kalshi as an opaque id; nothing here reads meaning
out of it.
"""

from __future__ import annotations

from collections.abc import Callable

from fetch.kalshi import kalshi_get, strip_market

# Get Markets default is 100; max is 1000.
MARKET_PAGE_LIMIT = 1000


def fetch_markets(
    series_ticker: str, key_id: str, private_key,
    *, max_pages: int = 1000, sink: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Fetch open markets for one ``series_ticker``. Strip each page immediately.

    ``sink``, if set, receives each stripped row and nothing is accumulated.
    Raises RuntimeError if pagination hits ``max_pages`` with a live cursor.
    """
    all_markets: list[dict] = []
    n_seen = 0
    cursor = ""
    for _page in range(max_pages):
        params: dict[str, str | int] = {
            "series_ticker": series_ticker,
            "status": "open",
            "limit": MARKET_PAGE_LIMIT,
        }
        if cursor:
            params["cursor"] = cursor
        result = kalshi_get(
            "/trade-api/v2/markets", params, key_id, private_key,
        )
        page = result.get("markets") or []
        for raw in page:
            row = strip_market(raw)
            n_seen += 1
            if sink is not None:
                sink(row)
            else:
                all_markets.append(row)
        cursor = result.get("cursor") or ""
        if not cursor:
            return all_markets
    raise RuntimeError(
        f"Kalshi {series_ticker} hit max_pages={max_pages} with cursor "
        f"still set ({n_seen} markets) — refusing truncated book"
    )
