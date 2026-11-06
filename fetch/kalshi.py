"""Fetch Kalshi sports markets for the mapping pipeline.

Usage:
    python -m fetch.kalshi --league nba epl --out-dir data/2026-03-06/12_00

One sweep of Kalshi's open events (markets nested) keeps every event whose
series is tagged with a sport the requested leagues play and whose typed
scope that sport maps.  Each market row carries Kalshi's typed identity:
the series scope, the event's competition_scope, the sport, and the game's
milestone (Optic fixture id, Sportradar id, side ids).  Nothing here reads
a ticker: which league a market belongs to is decided in the mapper, by
the Optic fixture its milestone joins.

Uses requests + RSA-PSS auth directly (no MMkalshi dependency).
Credentials from GCP Secret Manager via gcloud CLI.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta, timezone

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from fetch.gcloud_util import gcloud_cmd
from fetch.tip import resolved_leagues
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import market_type_for_scope, sport_for_tags, team_first_td_scope

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://api.elections.kalshi.com"
GCP_PROJECT = os.environ["GCP_PROJECT"]
# Get Events max page size.
EVENT_PAGE_LIMIT = 200
# Kalshi's status for a market that is open for trading, as nested
# markets report it.
ACTIVE = "active"


def requested_sports(leagues: list[str]) -> set[Sport]:
    """Sports of the requested leagues that have Kalshi coverage."""
    configs = resolved_leagues()
    return {
        cfg.KALSHI.sport
        for slug, cfg in configs.items()
        if slug in leagues and cfg.KALSHI is not None
    }


def load_series_catalog() -> dict[str, dict]:
    """series ticker → Kalshi series record (tags, product_metadata.scope).

    The public catalog, fetched once.  An empty payload is an error, not
    an empty book.
    """
    resp = requests.get(
        BASE_URL + "/trade-api/v2/series",
        params={"include_product_metadata": "true"}, timeout=60)
    resp.raise_for_status()
    series = list(resp.json().get("series") or [])
    if not series:
        raise RuntimeError("Kalshi /series returned an empty catalog")
    return {s["ticker"]: s for s in series}


# Keys to keep from each market record — everything else (prices,
# volumes, order book data) is stripped.  Matches Nick's original
# market_mapping_kalshi.py output.
STRUCTURAL_KEYS = (
    "event_ticker", "ticker", "title",
    "yes_sub_title", "no_sub_title",
    "market_type", "status",
    "created_time", "open_time", "close_time", "expected_expiration_time",
    "rules_primary", "rules_secondary",
)

# Typed strike fields — kept when Kalshi sends them.  Kalshi omits them
# on markets with no strike (round of finish, BTTS, ...), so they are not
# required.  The mapper reads line, side, method and round from these.
STRIKE_KEYS = ("strike_type", "floor_strike", "cap_strike", "custom_strike")


def strip_market(market: dict) -> dict:
    """Keep only structural keys from a raw Kalshi market record."""
    missing = set(STRUCTURAL_KEYS) - market.keys()
    if missing:
        print(json.dumps(market, indent=2, default=str), file=sys.stderr)
        raise KeyError(f"Market missing expected keys: {missing}")
    row = {k: market[k] for k in STRUCTURAL_KEYS}
    row.update({k: market[k] for k in STRIKE_KEYS if market.get(k) is not None})
    return row


# ---------------------------------------------------------------------------
# Auth — RSA-PSS signature, replicates KalshiAuth from MMkalshi
# ---------------------------------------------------------------------------


def load_credentials():
    """Fetch API key and private key from GCP Secret Manager."""
    key_id = subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=wsd_1_kalshi_api_key", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    key_pem = subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=wsd_1_kalshi_private_key", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    private_key = serialization.load_pem_private_key(
        key_pem.encode("utf-8"), password=None,
    )
    return key_id, private_key


def auth_headers(method: str, path: str, key_id: str, private_key) -> dict:
    """Generate Kalshi auth headers (RSA-PSS signature)."""
    ts = str(int(time.time() * 1000))
    msg = (ts + method.upper() + path.split("?")[0]).encode("utf-8")
    sig = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }


def kalshi_get(path: str, params: dict | None, key_id: str, private_key) -> dict:
    """Authenticated GET against the Kalshi API."""
    url = BASE_URL + path
    headers = auth_headers("GET", path, key_id, private_key)
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(0.1)
    return resp.json()


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


# Milestones start this far back so games already in play still find
# theirs.  Kalshi lists milestones by start date only.
MILESTONE_LOOKBACK = timedelta(days=3)
MILESTONE_PAGE_LIMIT = 500


# Competitor structured-target types; source_2_id, where Kalshi sets it,
# is Optic's competitor id.  Soccer teams carry only Sportradar ids, so
# they are not listed; about a quarter of UFC fighters carry Optic's id.
OPTIC_TEAM_TARGET_TYPES = (
    "basketball_team", "baseball_team", "football_team", "hockey_team",
    "cricket_team", "tennis_competitor", "esports_competitor",
    "boxing_competitor", "ufc_competitor",
)
# Kalshi files esports milestones under their own category.
MILESTONE_CATEGORIES = ("Sports", "Esports")
# The two sides of a milestone, by detail key.  Team sports name home and
# away; tennis/esports/fights name first/second (or home/away competitor)
# in Kalshi's listing order, which is not Optic's home — orientation is
# always decided by id evidence downstream, never by these names.
_SIDE_KEYS = (
    ("home_team_id", "away_team_id"),
    ("home_competitor_id", "away_competitor_id"),
    ("first_competitor_id", "second_competitor_id"),
    ("first_fighter_id", "second_fighter_id"),
)
TARGET_PAGE_SIZE = 2000


def fetch_team_optic_ids(
    key_id: str, private_key: object, *, max_pages: int = 50,
) -> dict[str, str]:
    """Kalshi team structured-target id → Optic competitor id."""
    out: dict[str, str] = {}
    for target_type in OPTIC_TEAM_TARGET_TYPES:
        cursor = ""
        for _page in range(max_pages):
            params: dict[str, str | int] = {
                "type": target_type, "page_size": TARGET_PAGE_SIZE,
            }
            if cursor:
                params["cursor"] = cursor
            result = kalshi_get(
                "/trade-api/v2/structured_targets", params, key_id, private_key,
            )
            page = result.get("structured_targets") or []
            for t in page:
                optic_id = (t.get("source_ids") or {}).get("source_2_id")
                if t.get("id") and optic_id:
                    out[t["id"]] = optic_id
            cursor = result.get("cursor") or ""
            if not cursor or not page:
                break
        else:
            raise RuntimeError(
                f"Kalshi structured_targets {target_type} hit max_pages")
    return out


def compact_milestone(
    m: dict, team_optic_ids: dict[str, str] | None = None,
) -> dict:
    """Keep the identity fields of one Kalshi sports milestone.

    source_2_id is Optic's own fixture id; source_3_id is Sportradar's
    sport_event id (bare integer = Optic's sportradar_id).  home/away/tie
    are Kalshi structured-target ids — the same ids each market names in
    custom_strike, so a market's team is an id comparison, not a ticker
    decode.  Tennis/esports/fight milestones name first/second competitor
    instead; home_id/away_id hold those in Kalshi's listing order (see
    _SIDE_KEYS).  home/away_optic_id
    are the teams' Optic competitor ids when Kalshi publishes them —
    what orients the game against Optic's home/away.
    """
    details = m.get("details") or {}
    optic_ids = team_optic_ids or {}
    ids = m.get("source_ids") or {}
    side_a = side_b = None
    for a_key, b_key in _SIDE_KEYS:
        if details.get(a_key) and details.get(b_key):
            side_a, side_b = details[a_key], details[b_key]
            break
    sr = ids.get("source_3_id") or ""
    return {
        "id": m.get("id"),
        "type": m.get("type"),
        "start_date": m.get("start_date"),
        "optic_fixture_id": ids.get("source_2_id"),
        "sportradar_id": sr.rsplit(":", 1)[-1] if sr.startswith("sr:") else None,
        "home_id": side_a,
        "away_id": side_b,
        "tie_id": details.get("tie_id"),
        "home_optic_id": optic_ids.get(side_a or ""),
        "away_optic_id": optic_ids.get(side_b or ""),
    }


def fetch_milestones(
    key_id: str, private_key: object, *, now: datetime | None = None,
    max_pages: int = 200,
) -> dict[str, dict]:
    """event_ticker → compact milestone, for every recent sports/esports game.

    One bulk listing (a few pages) instead of one call per event.
    """
    since = (now or datetime.now(timezone.utc)) - MILESTONE_LOOKBACK
    team_optic_ids = fetch_team_optic_ids(key_id, private_key)
    by_event: dict[str, dict] = {}
    for category in MILESTONE_CATEGORIES:
        cursor = ""
        for _page in range(max_pages):
            params: dict[str, str | int] = {
                "category": category,
                "minimum_start_date": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": MILESTONE_PAGE_LIMIT,
            }
            if cursor:
                params["cursor"] = cursor
            result = kalshi_get(
                "/trade-api/v2/milestones", params, key_id, private_key,
            )
            page = result.get("milestones") or []
            for m in page:
                compact = compact_milestone(m, team_optic_ids)
                for et in (m.get("related_event_tickers") or []):
                    by_event[et] = compact
            cursor = result.get("cursor") or ""
            if not cursor or not page:
                break
        else:
            raise RuntimeError(
                f"Kalshi {category} milestones hit max_pages={max_pages} "
                f"with cursor still set"
            )
    return by_event


# ---------------------------------------------------------------------------
# Events sweep
# ---------------------------------------------------------------------------


def sweep_events(
    key_id: str, private_key: object, sink: Callable[[dict], None],
    *, max_pages: int = 1000,
) -> None:
    """Every open Kalshi event with its markets nested, one page at a time."""
    cursor = ""
    for _page in range(max_pages):
        params: dict[str, str | int] = {
            "status": "open",
            "with_nested_markets": "true",
            "limit": EVENT_PAGE_LIMIT,
        }
        if cursor:
            params["cursor"] = cursor
        result = kalshi_get("/trade-api/v2/events", params, key_id, private_key)
        for event in result.get("events") or []:
            sink(event)
        cursor = result.get("cursor") or ""
        if not cursor:
            return
    raise RuntimeError(
        f"Kalshi events hit max_pages={max_pages} with cursor still set "
        f"— refusing a truncated book")


def event_rows(
    event: dict,
    catalog: dict[str, dict],
    sports: set[Sport],
    milestones: dict[str, dict],
) -> list[dict]:
    """Mapping rows for one event's open markets, or [] when out of scope.

    Kept: the series' sport is requested and the event's typed scope (or,
    with none, the series scope) is one that sport maps — the same rule
    mappers.exchanges.kalshi.scoped_market_type applies (including its team-first-TD scope pair,
    whose event scope names the team and so is not a literal key).
    """
    series = catalog.get(event.get("series_ticker") or "") or {}
    sport = sport_for_tags(series.get("tags"))
    if sport is None or sport not in sports:
        return []
    series_scope = ((series.get("product_metadata") or {}).get("scope") or "").strip()
    scope = ((event.get("product_metadata") or {}).get("competition_scope") or "").strip()
    typed = market_type_for_scope(sport, scope or series_scope) is not None
    if not (typed or team_first_td_scope(sport, series_scope, scope)):
        return []
    milestone = milestones.get(event["event_ticker"])
    rows: list[dict] = []
    for market in event.get("markets") or []:
        if market.get("status") != ACTIVE:
            continue
        row = strip_market(market)
        row["sport"] = sport.value
        if series_scope:
            row["series_scope"] = series_scope
        if scope:
            row["competition_scope"] = scope
        if milestone is not None:
            row["milestone"] = milestone
        rows.append(row)
    return rows


def fetch_book(
    sports: set[Sport], key_id: str, private_key: object, out: Callable[[dict], None],
) -> int:
    """Write every in-scope open market; return how many."""
    catalog = load_series_catalog()
    # Milestones only carry identity; without them no market can join a
    # fixture, so a failure here is a failed fetch, not an empty book.
    milestones = fetch_milestones(key_id, private_key)
    print(f"Kalshi milestones: {len(milestones)} event tickers", file=sys.stderr)
    n = 0

    def _sink(event: dict) -> None:
        nonlocal n
        for row in event_rows(event, catalog, sports, milestones):
            out(row)
            n += 1

    sweep_events(key_id, private_key, _sink)
    return n


def _write_book(
    sports: set[Sport], key_id: str, private_key: object, out_dir: str,
) -> int:
    """Stream to a temp file and rename only on success.

    fetch.kalshi is not a REQUIRED fetcher, so the pipeline maps on past
    its failure — a half-written kalshi_markets.jsonl would read as a
    complete-but-short book.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "kalshi_markets.jsonl")
    tmp = path + ".partial"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            total = fetch_book(
                sports, key_id, private_key,
                lambda row: print(json.dumps(row), file=handle))
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise
    os.replace(tmp, path)
    print(f"Wrote {path}")
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Kalshi sports markets for the requested leagues' sports.",
    )
    parser.add_argument(
        "--league", nargs="+",
        help="Leagues to fetch; their sports decide which markets are kept",
    )
    parser.add_argument(
        "--market", metavar="TICKER",
        help="Fetch a single market by ticker and print JSONL to stdout",
    )
    parser.add_argument(
        "--max-items", type=int,
        help="Accepted for orchestrator parity; the sweep is not truncated",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory (written by orchestrator)",
    )
    args = parser.parse_args()

    print("Loading credentials from GCP Secret Manager...", file=sys.stderr)
    key_id, private_key = load_credentials()

    if args.market:
        result = kalshi_get(
            f"/trade-api/v2/markets/{args.market}", None, key_id, private_key,
        )
        print(json.dumps(result["market"]))
        return

    if not args.league:
        parser.error("--league is required when not using --market")

    sports = requested_sports(args.league)
    if not sports:
        print("No requested league has Kalshi coverage", file=sys.stderr)
        return
    if args.out_dir:
        total = _write_book(sports, key_id, private_key, args.out_dir)
    else:
        total = fetch_book(
            sports, key_id, private_key, lambda row: print(json.dumps(row)))
    print(f"\nTotal: {total} markets", file=sys.stderr)


if __name__ == "__main__":
    main()
