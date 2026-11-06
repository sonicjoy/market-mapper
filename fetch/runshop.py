"""Fetch Runshop fixture ID chain from betbuilder API + Polymarket Postgres.

The betbuilder price API is the authoritative list of fixtures with
Runshop model output.  Each fetch:

  1. GET getBetBuilderModelPrices → unique txOddsFixtureID values
  2. poly_tx_mapping.fixtures → poly game_id (by tx legacy id)
  3. txodds-fusion.public.fixture → legacy id when it differs from tx live
  4. poly public.events → title + start_time for Optic schedule match

Output in the run output dir (current API fixtures only — no accumulated
catalogue):

  - runshop_prices.jsonl — verbatim betbuilder price snapshot
  - runshop_fixture_chain.jsonl — tx/poly/optic fixture join chain

Credentials from GCP Secret Manager via gcloud CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fetch.gcloud_util import gcloud_cmd
from fetch.runshop_db import (
    connect_poly,
    connect_tx,
    fetch_events,
    fetch_poly_by_legacy_ids,
    fetch_tx_legacy_by_fixture_ids,
)

BETBUILDER_BASE_URL = "http://35.246.32.87:8082/api/v10/model/a"
BETBUILDER_MODEL_ID = 224
BETBUILDER_API_KEY_SECRET = "runshop_betbuilder_api_key"

TX_PASSWORD_SECRET = "runshop_txodds_fusion_db_password"
POLY_PASSWORD_SECRET = "runshop_poly_db_password"

CHAIN_FILENAME = "runshop_fixture_chain.jsonl"
PRICES_FILENAME = "runshop_prices.jsonl"

_FETCH_RETRIES = 3
_BACKOFF_SECONDS = 1.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _gcp_project() -> str:
    return os.environ["GCP_PROJECT"]


def _load_secret(name: str) -> str:
    return subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            f"--secret={name}", f"--project={_gcp_project()}",
        ),
        text=True,
    ).strip()


def extract_fixture_ids(prices: list[dict]) -> list[int]:
    """Unique txOddsFixtureID values from a betbuilder price dump."""
    return sorted({int(row["txOddsFixtureID"]) for row in prices})


def filter_prices_by_fixture_ids(
    prices: list[dict],
    fixture_ids: set[int],
) -> list[dict]:
    """Keep price rows whose txOddsFixtureID is in fixture_ids."""
    return [
        row for row in prices
        if int(row["txOddsFixtureID"]) in fixture_ids
    ]


def _get_json(url: str, headers: dict[str, str], timeout_sec: int) -> Any:
    """GET url as JSON, retrying transport errors and 429/5xx with backoff.

    Other 4xx (e.g. a bad API key) raise on the first attempt — retrying
    those only delays an actionable failure.
    """
    req = urllib.request.Request(url, headers=headers)
    last_exc: Exception | None = None
    reason = ""
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code not in _RETRY_STATUSES:
                raise RuntimeError(
                    f"betbuilder API HTTP {exc.code}: {body}",
                ) from exc
            last_exc, reason = exc, f"HTTP {exc.code}: {body}"
        except (urllib.error.URLError, TimeoutError) as exc:
            # urlopen raises a bare TimeoutError once the response has
            # started, and URLError for connect-time failures.
            last_exc, reason = exc, str(getattr(exc, "reason", exc))
        if attempt < _FETCH_RETRIES:
            backoff = _BACKOFF_SECONDS * 2 ** (attempt - 1)
            print(
                f"  betbuilder attempt {attempt} failed: {reason}, "
                f"retrying in {backoff}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
    if isinstance(last_exc, urllib.error.HTTPError):
        raise RuntimeError(
            f"betbuilder API HTTP failed after {_FETCH_RETRIES} attempts: {reason}",
        ) from last_exc
    # Transport / timeout — host unreachable or connection dropped.
    raise RuntimeError(
        f"betbuilder API connectivity failed after {_FETCH_RETRIES} "
        f"attempts: {reason}",
    ) from last_exc


def fetch_betbuilder_prices(
    *,
    api_key: str | None = None,
    model_id: int = BETBUILDER_MODEL_ID,
    timeout_sec: int = 120,
) -> list[dict]:
    """Download the full betbuilder model price snapshot."""
    key = api_key if api_key is not None else _load_secret(BETBUILDER_API_KEY_SECRET)
    url = (
        f"{BETBUILDER_BASE_URL}/getBetBuilderModelPrices"
        f"?modelId={model_id}"
    )
    data = _get_json(url, {"X-WSD-API-KEY": key}, timeout_sec)
    if not isinstance(data, list):
        raise RuntimeError(
            f"betbuilder API returned {type(data).__name__}, expected list",
        )
    return data


def fetch_betbuilder_fixture_ids(
    *,
    api_key: str | None = None,
    prices: list[dict] | None = None,
) -> list[int]:
    """Fixture ids currently priced by the betbuilder model."""
    if prices is None:
        prices = fetch_betbuilder_prices(api_key=api_key)
    return extract_fixture_ids(prices)


def build_chain_records(
    tx_rows: list[tuple[int, int]],
    legacy_to_poly: dict[int, str],
    events_by_game: dict[str, tuple[str | None, str | None]],
) -> list[dict]:
    records: list[dict] = []
    for tx_fixture_id, legacy_id in tx_rows:
        poly_game_id = legacy_to_poly.get(legacy_id)
        if not poly_game_id:
            continue
        title, start_time = events_by_game.get(poly_game_id, (None, None))
        records.append({
            "tx_odds_fixture_id": tx_fixture_id,
            "tx_legacy_fixture_id": legacy_id,
            "poly_game_id": poly_game_id,
            "poly_title": title,
            "poly_start_time": start_time,
        })
    records.sort(key=lambda r: r["tx_odds_fixture_id"])
    return records


def _load_tx_legacy_map(fixture_ids: list[int]) -> dict[int, int]:
    try:
        tx_pw = _load_secret(TX_PASSWORD_SECRET)
        tx_con = connect_tx(tx_pw)
        try:
            return fetch_tx_legacy_by_fixture_ids(tx_con, fixture_ids)
        finally:
            tx_con.close()
    except Exception as exc:
        print(
            f"WARN: txodds-fusion lookup skipped ({exc}); "
            "using tx live id as legacy id",
            file=sys.stderr,
        )
        return {}


def _enrich_chain_from_poly(
    poly_con,
    fixture_ids: list[int],
    tx_legacy: dict[int, int],
) -> list[dict]:
    tx_rows = [(fid, tx_legacy.get(fid, fid)) for fid in fixture_ids]
    legacy_ids = sorted({legacy for _, legacy in tx_rows})
    legacy_to_poly = fetch_poly_by_legacy_ids(poly_con, legacy_ids)
    game_ids = set(legacy_to_poly.values())
    events_by_game = fetch_events(poly_con, game_ids)
    return build_chain_records(tx_rows, legacy_to_poly, events_by_game)


def fetch_fixture_chain(
    *,
    api_fixture_ids: list[int] | None = None,
    api_key: str | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Build fixture chain for betbuilder-active fixtures."""
    fixture_ids = (
        api_fixture_ids
        if api_fixture_ids is not None
        else fetch_betbuilder_fixture_ids(api_key=api_key)
    )
    stats = {
        "api_fixtures": len(fixture_ids),
        "chain_rows": 0,
        "tx_rows_resolved": 0,
    }
    if not fixture_ids:
        return [], stats

    tx_legacy = _load_tx_legacy_map(fixture_ids)
    stats["tx_rows_resolved"] = len(tx_legacy)

    poly_pw = _load_secret(POLY_PASSWORD_SECRET)
    poly_con = connect_poly(poly_pw)
    try:
        records = _enrich_chain_from_poly(poly_con, fixture_ids, tx_legacy)
        stats["chain_rows"] = len(records)
        return records, stats
    finally:
        poly_con.close()


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def write_chain(path: Path, records: list[dict]) -> None:
    write_jsonl(path, records)


def write_prices(path: Path, records: list[dict]) -> None:
    write_jsonl(path, records)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Runshop fixture chain to JSONL",
    )
    parser.add_argument(
        "--league", nargs="+", required=True,
        help="Leagues (only world_cup triggers fetch)",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--max-items", type=int,
        help="Max API fixtures to resolve (for smoke testing)",
    )
    return parser.parse_args()


def _selected_prices(
    prices: list[dict],
    max_items: int | None,
) -> tuple[list[int], list[dict]]:
    """Derive fixture ids and optional price subset for smoke runs."""
    fixture_ids = extract_fixture_ids(prices)
    if max_items is not None:
        fixture_ids = fixture_ids[:max_items]
        return fixture_ids, filter_prices_by_fixture_ids(prices, set(fixture_ids))
    return fixture_ids, prices


def main() -> None:
    args = _parse_args()

    if "world_cup" not in args.league:
        print("runshop: skipped (world_cup not requested)", file=sys.stderr)
        return

    print(
        "Loading Runshop credentials from GCP Secret Manager...",
        file=sys.stderr,
    )
    print(
        f"runshop fixture chain fetch: betbuilder modelId={BETBUILDER_MODEL_ID}",
        file=sys.stderr,
    )

    fixture_ids, prices_to_write = _selected_prices(
        fetch_betbuilder_prices(), args.max_items,
    )
    if not prices_to_write:
        # Reachable API with an empty list is not a failure — model has no
        # priced fixtures (e.g. between tournaments). Distinct from
        # connectivity failures raised by _get_json.
        print(
            f"betbuilder reachable; modelId={BETBUILDER_MODEL_ID} "
            "returned 0 prices (no fixtures this tick)",
            file=sys.stderr,
        )

    prices_path = args.out_dir / PRICES_FILENAME
    write_prices(prices_path, prices_to_write)

    records, stats = fetch_fixture_chain(api_fixture_ids=fixture_ids)
    out_path = args.out_dir / CHAIN_FILENAME
    write_chain(out_path, records)

    print(
        f"Wrote {len(prices_to_write)} price records to {prices_path}",
        file=sys.stderr,
    )
    print(
        f"Wrote {len(records)} fixture chain records to {out_path} "
        f"(api fixtures={stats['api_fixtures']}, "
        f"tx resolved={stats['tx_rows_resolved']}, "
        f"chain rows={stats['chain_rows']})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
