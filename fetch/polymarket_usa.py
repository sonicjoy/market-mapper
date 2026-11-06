"""Harvest Polymarket US gateway markets for Path 2 — typed fields only.

Walks every gateway league the mapper reads: the numeric league ids in
``mappers.exchanges.polymarket_usa_leagues``. Each id is looked up in the
gateway's typed league catalogue (``GET /v2/sports``); the catalogue's
``slug`` is used only to build the ``/v2/leagues/{slug}/events`` URL (the
gateway takes no id there) and is never stored or compared. Event detail
comes from ``/v1/events/{id}`` (the full ``astatc`` player-prop set).

Output: ``polymarket_usa_markets.jsonl`` — **the Path 2 input**: one line per
gateway market with its typed fields (``sportsMarketType``, ``line``,
``marketSides[].long/team``, ``metadata.playerName``, ``title``), the gateway
league id it was walked under, and event context (``startTime``,
``sportradarGameId``, ``teams``). Loaded to
``raw_ingestion_us.polymarket_usa_fetch_raw``. See
``mappers.exchanges.polymarket_usa_structured``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from fetch.polymarket_usa_gateway import GATEWAY_BASE
from mappers.exchanges.polymarket_usa_leagues import all_us_league_ids

_HEADERS = {"User-Agent": "mmmapper/polymarket-usa-events"}
_FETCH_RETRIES = 4
_BACKOFF_SECONDS = 1.0
_PAGE_SIZE = 1000
_DEFAULT_HARVEST_WORKERS = 8


def _harvest_workers() -> int:
    raw = os.environ.get("POLY_USA_HARVEST_WORKERS", "").strip()
    if not raw:
        return _DEFAULT_HARVEST_WORKERS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_HARVEST_WORKERS


@dataclass(frozen=True)
class GatewayLeague:
    """One league from the gateway's typed catalogue."""

    league_id: int
    name: str
    # The gateway's own URL key for ``/v2/leagues/{slug}/events``; never
    # an identity.
    url_key: str


def league_catalogue() -> dict[int, GatewayLeague]:
    """{league id -> league} from ``GET /v2/sports``; raises on failure."""
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(
                f"{GATEWAY_BASE}/v2/sports", headers=_HEADERS, timeout=30,
            )
            resp.raise_for_status()
            return parse_catalogue(resp.json())
        except Exception as exc:
            last_err = exc
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS * (2 ** attempt))
    raise RuntimeError(f"polymarket_usa league catalogue: fetch failed ({last_err})")


def parse_catalogue(payload: object) -> dict[int, GatewayLeague]:
    """{league id -> league} from a ``/v2/sports`` payload."""
    out: dict[int, GatewayLeague] = {}
    sports = payload.get("sports") if isinstance(payload, dict) else None
    for sport in sports or []:
        if not isinstance(sport, dict):
            continue
        for row in sport.get("leagues") or []:
            if not isinstance(row, dict):
                continue
            lid, key = row.get("id"), str(row.get("slug") or "").strip()
            if isinstance(lid, int) and not isinstance(lid, bool) and key:
                out[lid] = GatewayLeague(lid, str(row.get("name") or "").strip(), key)
    return out


def _get_event_detail(event_id: int | str) -> dict[str, Any] | None:
    """Full event from ``/v1/events/{id}`` (all ``astatc`` player props)."""
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(
                f"{GATEWAY_BASE}/v1/events/{event_id}",
                headers=_HEADERS,
                timeout=30,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                return None
            event = payload.get("event")
            return event if isinstance(event, dict) else None
        except Exception as exc:
            last_err = exc
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS * (2 ** attempt))
    print(
        f"  polymarket_usa event [{event_id}]: fetch failed ({last_err})",
        file=sys.stderr,
    )
    return None


def league_events(url_key: str) -> list[dict]:
    """Full ``/v2/leagues/{url_key}/events`` pages (404 → no events)."""
    return list(_iter_league_events(url_key))


def _iter_league_events(url_key: str) -> Iterator[dict]:
    """Yield one gateway event per page row."""
    offset = 0
    while True:
        last_err: Exception | None = None
        payload: dict | None = None
        for attempt in range(_FETCH_RETRIES):
            try:
                resp = requests.get(
                    f"{GATEWAY_BASE}/v2/leagues/{url_key}/events",
                    params={
                        "limit": _PAGE_SIZE,
                        "offset": offset,
                        "active": "true",
                        "closed": "false",
                    },
                    headers=_HEADERS,
                    timeout=30,
                )
                if resp.status_code == 404:
                    return
                resp.raise_for_status()
                raw = resp.json()
                payload = raw if isinstance(raw, dict) else {}
                break
            except Exception as exc:
                last_err = exc
                if attempt < _FETCH_RETRIES - 1:
                    time.sleep(_BACKOFF_SECONDS * (2 ** attempt))
        if payload is None:
            print(
                f"  polymarket_usa events [{url_key}]: fetch failed ({last_err})",
                file=sys.stderr,
            )
            return
        page = [row for row in (payload.get("events") or []) if isinstance(row, dict)]
        yield from page
        if len(page) < _PAGE_SIZE:
            return
        offset += _PAGE_SIZE


def _provider_id(team: dict[str, Any], provider: str) -> str:
    """Provider id (e.g. Sportradar) from a gateway team, or empty."""
    for row in team.get("providerIds") or []:
        if isinstance(row, dict) and row.get("provider") == provider:
            return str(row.get("providerId") or "").strip()
    return ""


def _slim_team(team: object) -> dict[str, Any] | None:
    """Identity fields of a gateway team; logos / colours dropped."""
    if not isinstance(team, dict) or team.get("id") in (None, ""):
        return None
    out: dict[str, Any] = {"id": str(team["id"])}
    for src, dst in (
        ("abbreviation", "abbreviation"), ("name", "name"),
        ("safeName", "safe_name"), ("alias", "alias"), ("league", "league"),
    ):
        val = str(team.get(src) or "").strip()
        if val:
            out[dst] = val
    sr = _provider_id(team, "PROVIDER_SPORTRADAR")
    if sr:
        out["sportradar_id"] = sr
    return out


def _slim_side(side: dict[str, Any]) -> dict[str, Any]:
    """Side id, long flag, description and team id; prices dropped."""
    team = side.get("team") if isinstance(side.get("team"), dict) else {}
    team_id = (team or {}).get("id") or side.get("teamId")
    out: dict[str, Any] = {
        "id": str(side.get("id") or ""),
        "long": side.get("long") is True,
        "description": str(side.get("description") or "").strip(),
    }
    if team_id not in (None, ""):
        out["team_id"] = str(team_id)
    return out


_MARKET_META_KEYS = ("playerName", "playerId", "playerAbbreviation", "lineLabel", "teamId")


def market_record(
    market: dict[str, Any], event: dict[str, Any], league_id: int | None,
) -> dict[str, Any] | None:
    """Structured Path 2 line for one gateway market, or None without ids."""
    slug = str(market.get("slug") or "").strip().lower()
    market_id = str(market.get("id") or "").strip()
    if not slug or not market_id:
        return None
    teams = [t for t in (_slim_team(x) for x in event.get("teams") or []) if t]
    known = {t["id"] for t in teams}
    for side in market.get("marketSides") or []:
        team = _slim_team(side.get("team")) if isinstance(side, dict) else None
        if team is not None and team["id"] not in known:
            teams.append(team)
            known.add(team["id"])
    raw_meta = market.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    line = market.get("line")
    return {
        "league_id": league_id,
        "event_id": str(event.get("id") or ""),
        "event_ticker": str(event.get("ticker") or event.get("slug") or "").strip().lower(),
        "event_start": str(event.get("startTime") or "").strip(),
        "sportradar_game_id": str(event.get("sportradarGameId") or "").strip(),
        "teams": teams,
        "market_id": market_id,
        "slug": slug,
        "sports_market_type": str(market.get("sportsMarketType") or "").strip(),
        "market_type": str(market.get("marketType") or "").strip(),
        "line": line if isinstance(line, int | float) and not isinstance(line, bool) else None,
        "title": str(market.get("title") or "").strip(),
        "active": market.get("active") is True,
        "closed": market.get("closed") is True,
        "metadata": {k: meta[k] for k in _MARKET_META_KEYS if k in meta},
        "sides": [
            _slim_side(side) for side in market.get("marketSides") or []
            if isinstance(side, dict)
        ],
    }


def _absorb_records(
    event: dict[str, Any], league: GatewayLeague, out: dict[str, dict[str, Any]],
    conflicts: set[str],
) -> None:
    """Structured records for every market on ``event``; cross-event markets drop."""
    for market in event.get("markets") or []:
        if not isinstance(market, dict):
            continue
        rec = market_record(market, event, league.league_id)
        if rec is None or rec["market_id"] in conflicts:
            continue
        # shortcut: the mapper on main still filters on ``inner`` (the URL key);
        # drop once the league_id mapper (MR !490) is live.
        rec["inner"] = league.url_key.casefold()
        prev = out.get(rec["market_id"])
        if prev is not None and prev["event_id"] != rec["event_id"]:
            out.pop(rec["market_id"], None)
            conflicts.add(rec["market_id"])
            continue
        out[rec["market_id"]] = rec


def write_markets(out_dir: Path, records: dict[str, dict[str, Any]]) -> Path:
    """``polymarket_usa_markets.jsonl`` sorted by gateway market id."""
    out_path = out_dir / "polymarket_usa_markets.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for market_id in sorted(records):
            fh.write(json.dumps(records[market_id], sort_keys=True) + "\n")
    return out_path


def _event_details_for_league(
    events: list[dict],
    *,
    detail_sem: threading.Semaphore | None = None,
) -> dict[Any, dict[str, Any]]:
    ids: list[int | str] = []
    for event in events:
        eid = event.get("id")
        if isinstance(eid, (int, str)) and eid != "":
            ids.append(eid)
    if not ids:
        return {}

    def _fetch_one(eid: int | str) -> tuple[int | str, dict[str, Any] | None]:
        if detail_sem is not None:
            with detail_sem:
                return eid, _get_event_detail(eid)
        return eid, _get_event_detail(eid)

    out: dict[Any, dict[str, Any]] = {}
    workers = min(_harvest_workers(), len(ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_fetch_one, eid) for eid in ids]
        for fut in as_completed(futs):
            eid, detail = fut.result()
            if detail is not None:
                out[eid] = detail
    return out


def _harvest_one_league(
    league: GatewayLeague, *, detail_sem: threading.Semaphore | None = None,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Structured records (+ markets seen on two events) for one league."""
    records: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    events = league_events(league.url_key)
    details = _event_details_for_league(events, detail_sem=detail_sem)
    for event in events:
        # Detail carries the full market set; the page row is the fallback.
        _absorb_records(event, league, records, conflicts)
        detail = details.get(event.get("id"))
        if detail is not None:
            _absorb_records({**event, **detail}, league, records, conflicts)
    return records, conflicts


def harvest_records(leagues: list[GatewayLeague]) -> dict[str, dict[str, Any]]:
    """{market id -> structured record}; a market on two events drops."""
    if not leagues:
        return {}
    detail_sem = threading.Semaphore(_harvest_workers())
    parts: dict[int, tuple[dict[str, dict[str, Any]], set[str]]] = {}
    with ThreadPoolExecutor(max_workers=min(_harvest_workers(), len(leagues))) as pool:
        futs = {
            pool.submit(_harvest_one_league, league, detail_sem=detail_sem): league.league_id
            for league in leagues
        }
        for fut in as_completed(futs):
            parts[futs[fut]] = fut.result()
    out: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for league_id in sorted(parts):
        local, local_conflicts = parts[league_id]
        conflicts |= local_conflicts
        for market_id, rec in local.items():
            prev = out.get(market_id)
            if prev is not None and prev["event_id"] != rec["event_id"]:
                conflicts.add(market_id)
            out[market_id] = rec
    for market_id in conflicts:
        out.pop(market_id, None)
    return out


def wanted_leagues(
    catalogue: dict[int, GatewayLeague], wanted: frozenset[int],
) -> tuple[list[GatewayLeague], list[int]]:
    """(catalogue leagues to walk, wanted ids the catalogue does not list)."""
    found = [catalogue[lid] for lid in sorted(wanted) if lid in catalogue]
    return found, sorted(lid for lid in wanted if lid not in catalogue)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest Polymarket US gateway markets (Path 2 input).",
    )
    parser.add_argument(
        "--out-dir", required=True, help="Fetch output directory",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    leagues, missing = wanted_leagues(league_catalogue(), all_us_league_ids())
    if missing:
        # The events URL answers [] for any key, so a league the catalogue
        # dropped would otherwise go quiet.
        print(
            f"ALERT: polymarket_usa league ids not in the gateway catalogue: {missing}",
            file=sys.stderr,
        )
    records = harvest_records(leagues)
    mpath = write_markets(out_dir, records)
    print(f"Wrote {len(records)} structured markets to {mpath} ({len(leagues)} leagues)")


if __name__ == "__main__":
    main()
