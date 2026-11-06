"""Fetch Polymarket Gamma /markets records — the shared source for both the
position-id bridge and the leg-resolutions loaders.

One Gamma market record carries everything both loaders need, in the SAME
outcome order:

  * ``positionIds``    — the NegRisk combo-leg token ids (the RFQ ``position_id``)
  * ``clobTokenIds``   — the standalone single-market CLOB token ids
  * ``outcomes``       — outcome labels (e.g. ["Yes","No"])            } the bridge
  * ``outcomePrices``  — settled prices once resolved (e.g. ["1","0"]) }
  * ``closed`` / ``umaResolutionStatuses`` / ``endDate``               } resolution

So ``position_ids[i] <-> clob_token_ids[i] <-> outcomes[i] <-> outcome_prices[i]``.
This module only fetches + normalizes; the two BigQuery loaders derive rows.

``fetch_markets_by_condition_ids`` is the only access pattern used: given the
combo-leg condition_ids (from combos-rfq-api, see fetch/polymarket_combos.py), it
returns each market's aligned position/clob/outcome/price arrays. NOTE: Gamma's
bulk ``/markets`` (offset paging) does NOT return ``positionIds`` — only the
by-condition_ids lookup does — which is why the leg universe is enumerated from
combos-rfq-api, not from a Gamma sweep.

No BigQuery here. Mirrors the requests-based conventions of ``fetch/kalshi_all.py``.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

GAMMA_BASE = os.environ.get("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com").rstrip("/")

# condition_ids per /markets request (Gamma accepts repeated params; mirror the
# runtime loader's batch size in MMPolymarket.common.mapping_loader).
CONDITION_ID_BATCH = 40

_FETCH_RETRIES = 4
_BACKOFF_SECONDS = 1.0


def _json_arr(v) -> list:
    """Gamma array fields arrive as either a JSON string or a real list."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return []
    return v or []


def _get(path: str, params, base_url: str = GAMMA_BASE, timeout: int = 30) -> list[dict]:
    """GET a Gamma endpoint, retrying transient errors with exponential backoff.

    Returns the decoded JSON list (Gamma /markets returns a bare array).
    """
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(f"{base_url}{path}", params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data") or []
        except Exception as e:  # HTTPError (incl. flaky 429/5xx), timeout, JSON
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS * (2**attempt))
    raise last_err  # type: ignore[misc]


def normalize_market(m: dict) -> dict:
    """Normalize one raw Gamma market to the flat shape both loaders consume.

    Array fields (``outcomes``/``outcomePrices``/``clobTokenIds``/``positionIds``)
    may arrive JSON-string-encoded; decode them to real lists of strings so
    ``position_ids[i]`` aligns with ``clob_token_ids[i]`` / ``outcomes[i]`` /
    ``outcome_prices[i]``.
    """
    return {
        "condition_id": str(m.get("conditionId") or ""),
        "slug": m.get("slug") or "",
        "question": m.get("question") or m.get("title") or "",
        "position_ids": [str(x) for x in _json_arr(m.get("positionIds"))],
        "clob_token_ids": [str(x) for x in _json_arr(m.get("clobTokenIds"))],
        "outcomes": [str(x) for x in _json_arr(m.get("outcomes"))],
        "outcome_prices": [str(x) for x in _json_arr(m.get("outcomePrices"))],
        "uma_resolution_statuses": [str(x) for x in _json_arr(m.get("umaResolutionStatuses"))],
        "closed": bool(m.get("closed")),
        "end_date": m.get("endDate") or m.get("endDateIso") or None,
        # Polymarket's own kickoff instant for a sports market, e.g.
        # "2026-08-06 01:40:00+00". The ONLY trustworthy fixture key: the slug
        # carries a venue-local date, which cannot be compared to optic's UTC
        # start_date (see pipeline._match_poly_fixture). None for non-sports markets.
        "game_start_time": m.get("gameStartTime") or None,
        "updated_at": m.get("updatedAt") or None,
    }


def fetch_markets_by_condition_ids(
    condition_ids,
    base_url: str = GAMMA_BASE,
    batch_size: int = CONDITION_ID_BATCH,
    closed: bool | None = None,
) -> dict[str, dict]:
    """Return ``{condition_id -> normalized market}`` for the given condition_ids.

    Batched (``batch_size`` per request) and fetched concurrently. Resilient: a
    failed batch is logged to stderr and skipped (partial map) rather than
    aborting the whole fetch — the caller keeps whatever resolved.

    NOTE: the ``condition_ids`` lookup DEFAULTS to active (open) markets only.
    Pass ``closed=True`` to fetch SETTLED markets (the resolution loader needs
    this — a closed market is invisible to the default query). A closed market's
    response no longer carries ``positionIds``, so the caller must take those from
    the bridge, not from here.
    """
    cids = sorted({str(c) for c in condition_ids if c})
    batches = [cids[i : i + batch_size] for i in range(0, len(cids), batch_size)]
    if not batches:
        return {}

    def _one(batch: list[str]) -> list[dict]:
        params = [("condition_ids", c) for c in batch] + [("limit", len(batch))]
        if closed is not None:
            params.append(("closed", "true" if closed else "false"))
        try:
            return _get("/markets", params, base_url=base_url)
        except Exception as e:  # noqa: BLE001 — partial map beats aborting
            print(f"  gamma /markets batch failed ({e}); skipping {len(batch)} cids", file=sys.stderr)
            return []

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for res in pool.map(_one, batches):
            for m in res or []:
                cid = m.get("conditionId")
                if cid:
                    out[str(cid)] = normalize_market(m)
    return out


def fetch_markets_by_position_ids(
    position_ids,
    base_url: str = GAMMA_BASE,
    batch_size: int = CONDITION_ID_BATCH,
    closed: bool | None = None,
) -> dict[str, dict]:
    """Return ``{queried position_id -> normalized market}`` via ``/markets?position_ids=``.

    Unlike the ``condition_ids`` lookup, the ``position_ids`` reverse-lookup returns
    the FULL record — ``positionIds`` + ``clobTokenIds`` + ``outcomes`` + settled
    ``outcome_prices`` — even for SETTLED markets. That is what makes historical
    backfill possible: given a leg ``position_id`` we recorded while it was active,
    we can recover its bridge + settlement long after it delisted. Pass
    ``closed=True`` for settled legs (open ones come from combos-rfq-api).

    Each returned market is mapped back to whichever of the queried position_ids it
    contains (a market carries several).
    """
    pids = sorted({str(p) for p in position_ids if p})
    qset = set(pids)
    batches = [pids[i : i + batch_size] for i in range(0, len(pids), batch_size)]
    if not batches:
        return {}

    def _one(batch: list[str]) -> list[dict]:
        # limit generously (a market has >=2 positions, so N pids -> <=N markets).
        params = [("position_ids", p) for p in batch] + [("limit", 100)]
        if closed is not None:
            params.append(("closed", "true" if closed else "false"))
        try:
            return _get("/markets", params, base_url=base_url)
        except Exception as e:  # noqa: BLE001 — partial map beats aborting
            print(f"  gamma position_ids batch failed ({e}); skipping {len(batch)}", file=sys.stderr)
            return []

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for res in pool.map(_one, batches):
            for m in res or []:
                nm = normalize_market(m)
                for pid in nm["position_ids"]:
                    if pid in qset:
                        out[pid] = nm
    return out
