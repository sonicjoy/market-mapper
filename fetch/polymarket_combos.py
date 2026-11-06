"""Fetch the Polymarket combos-RFQ combinable-leg catalog.

``GET {COMBOS_API}/v1/rfq/combo-markets`` (cursor-paginated) returns every
single-leg market currently combinable into a combo, each with its
``condition_id`` + ``position_ids`` (the per-outcome NegRisk combo-leg token ids)
+ ``outcomes``. This is the authoritative universe of combo-leg ``position_id``s —
Gamma's bulk ``/markets`` does NOT expose ``positionIds``, so we enumerate cids
here and enrich clob_token_ids via Gamma by-condition_id (see fetch/polymarket_gamma).

The API sits behind Cloudflare, which geoblocks some egress IPs; set
``COMBOS_PROXY_URL`` (http[s]://[user:pass@]host:port) to route through a proxy
in an allowed region. Mirrors the runtime fetcher in
MMPolymarket.common.mapping_loader.fetch_combo_markets.
"""

import itertools
import os
import sys
import time

import requests

COMBOS_API = os.environ.get("COMBOS_API_URL", "https://combos-rfq-api.polymarket.sh").rstrip("/")
COMBOS_PROXY_URL = os.environ.get("COMBOS_PROXY_URL", "").strip()

_FETCH_RETRIES = 4
_BACKOFF_SECONDS = 1.0


def _proxies() -> dict | None:
    """requests proxies dict from COMBOS_PROXY_URL, or None for a direct connection."""
    return {"http": COMBOS_PROXY_URL, "https": COMBOS_PROXY_URL} if COMBOS_PROXY_URL else None


def _fetch_page(base_url: str, params: dict, proxies: dict | None) -> tuple[dict | None, Exception | None]:
    """One combo-markets page, with retry + exponential backoff. Returns (data, last_err)."""
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(
                f"{base_url}/v1/rfq/combo-markets",
                params=params,
                proxies=proxies,
                headers={"User-Agent": "mmmapper/polymarket-bridge"},
                timeout=25,
            )
            resp.raise_for_status()
            return resp.json(), None
        except Exception as e:  # flaky 400/429/5xx, timeout, JSON
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS * (2**attempt))
    return None, last_err


def fetch_combo_markets(base_url: str = COMBOS_API, max_pages: int | None = None) -> list[dict]:
    """Page every combo-markets entry until the API itself reports no next_cursor.
    Resilient: returns what was collected on a mid-pagination failure (a partial
    catalog beats none); a first-page failure raises.

    No default page limit: the catalog is sorted by volume, not date (confirmed via
    the endpoint's docs + observed mixed past/future dates in early pages), with no
    server-side date filter -- a budget cap here would truncate an arbitrary slice,
    including legs still tradeable. (This is exactly what happened: the old default of
    200 pages x 50/page capped every run at precisely 10,000 markets against a real
    catalog of 43,000+, with no warning.) The job's ``activeDeadlineSeconds`` is the
    real backstop, not a page count here. Filtering to what's worth enriching (upcoming,
    not-yet-bridged) belongs downstream, in ``BigQuery.load_polymarket_position_bridge``.

    ``max_pages`` exists only as an explicit, loudly-logged override (e.g. tests).
    """
    markets: list[dict] = []
    cursor = None
    proxies = _proxies()
    page_iter = range(max_pages) if max_pages is not None else itertools.count()
    for page_no in page_iter:
        params = {"limit": 50}
        if cursor:
            params["cursor"] = cursor
        data, last_err = _fetch_page(base_url, params, proxies)
        if data is None:
            if page_no == 0:
                raise last_err  # type: ignore[misc]
            print(
                f"  combo-markets page {page_no} failed ({last_err}); returning {len(markets)} collected",
                file=sys.stderr,
            )
            break
        page = data.get("markets") or []
        markets.extend(page)
        cursor = data.get("next_cursor")
        if not page or not cursor:
            break
    else:
        # Only reachable when max_pages was explicitly set (range() exhausted without
        # a break) -- itertools.count() never exhausts on its own. Silent truncation
        # is the exact bug this guards against, so this must be loud.
        if max_pages is not None and cursor:
            print(
                f"  combo-markets pagination hit max_pages={max_pages} cap with pages "
                f"still remaining (next_cursor={cursor!r}); catalog is truncated -- "
                f"raise max_pages",
                file=sys.stderr,
            )
    return markets


def fetch_combo_condition_ids(base_url: str = COMBOS_API) -> list[str]:
    """Distinct combo-leg ``condition_id``s from the combo-markets catalog."""
    seen: dict[str, None] = {}
    for m in fetch_combo_markets(base_url=base_url):
        cid = m.get("condition_id")
        if cid:
            seen.setdefault(str(cid), None)
    return list(seen)
