"""Fetch SX Bet's whole active catalogue for the SX pass.

Usage:
    python -m fetch.sxbet --league epl nfl --out-dir data/2026-10-13/12_00

Writes ``sxbet_markets.jsonl``: one ``GET /markets/active`` row per line,
verbatim.  The endpoint is public (no key, no geofence on reads -- the SX
maker's market-data collector reads it from GKE without the egress proxy)
and returns every sport, so ``--league`` is accepted for the orchestrator's
contract and ignored; ``mappers/exchanges/sxbet_leagues.py`` decides which
rows each league's pass keeps.

API notes (docs.sx.bet/api-reference/get-markets-active, probed
2026-10-13): ``pageSize`` max 100 (200 returns an error body);
``paginationKey`` = the previous ``nextKey``; a ``nextKey`` can point at
an empty page.  The live book was 12,272 markets in 123 pages of 100.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.sx.bet"
OUT_FILE = "sxbet_markets.jsonl"
PAGE_SIZE = 100
#: Runaway guard: ~125 pages today; anything past this is a pagination bug.
MAX_PAGES = 1000
MAX_TRIES = 3
TIMEOUT_S = 30


def _get_page(session: requests.Session, key: str | None) -> dict[str, Any]:
    """One page of ``/markets/active`` (``data``), retried on transport / 5xx errors."""
    params: dict[str, Any] = {"pageSize": PAGE_SIZE}
    if key:
        params["paginationKey"] = key
    last: Exception | None = None
    for attempt in range(MAX_TRIES):
        try:
            resp = session.get(f"{BASE_URL}/markets/active", params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                raise ValueError(f"SX /markets/active status {body.get('status')!r}")
            return body.get("data") or {}
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"SX /markets/active failed after {MAX_TRIES} tries: {last}")


def fetch_all(session: requests.Session | None = None, *, max_items: int | None = None) -> list[dict[str, Any]]:
    """Every active SX market (stops at ``max_items`` when given)."""
    session = session or requests.Session()
    out: list[dict[str, Any]] = []
    key: str | None = None
    for _ in range(MAX_PAGES):
        data = _get_page(session, key)
        out.extend(m for m in (data.get("markets") or []) if isinstance(m, dict))
        key = data.get("nextKey")
        if not key or (max_items is not None and len(out) >= max_items):
            break
    else:
        raise RuntimeError(f"SX /markets/active did not end within {MAX_PAGES} pages")
    return out[:max_items] if max_items is not None else out


def write_jsonl(markets: list[dict[str, Any]], out_dir: Path) -> Path:
    """Write ``sxbet_markets.jsonl`` into ``out_dir``."""
    path = out_dir / OUT_FILE
    with path.open("w", encoding="utf-8") as fh:
        for m in markets:
            fh.write(json.dumps(m, separators=(",", ":")) + "\n")
    return path


def main() -> None:
    """CLI entry: fetch the whole catalogue into ``--out-dir``."""
    parser = argparse.ArgumentParser(description="Fetch SX Bet's active markets.")
    parser.add_argument("--league", nargs="*", default=[], help="accepted and ignored: the catalogue is one book")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-items", type=int, help="smoke-test cap")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    markets = fetch_all(max_items=args.max_items)
    path = write_jsonl(markets, out_dir)
    print(f"  sxbet: {len(markets)} active markets -> {path} ({time.monotonic() - started:.1f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
