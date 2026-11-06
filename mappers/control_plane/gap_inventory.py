"""RFQ true-gap inventory for gap harvest (every book in ``HARVEST_BOOKS``)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from mappers.control_plane.rfq_platforms import BOOK_CRYPTO, HARVEST_BOOKS
from mappers.seed.poly_usa_exchange import us_league_code

MAX_EVENTS = 100  # pin-producing events per book this tick
# Shared cap for empty-RFQ fixture sweepers (abbr-code / optic_missing / crypto_missing).
# Test proposes ~52 pins in 2Gi; prod Sunday OOM'd at ~126 empty pins + full cache in 4Gi.
MAX_EMPTY_HARVEST_PINS = 40
MAX_PROBE = 200  # legacy name; BQ fetch page size per book uses INVENTORY_PAGE
INVENTORY_PAGE = 5000  # max keys ranked per harvest page (not a pin cap)
MAX_PER_BUCKET = 12  # first-pass cap per crypto sport
MAX_SLOT_MISSES = 3  # consecutive missing_optic/title_miss → skip series
_CRYPTO_SPORT = re.compile(r"^NX\.F\.OPT\.([A-Z0-9]+)", re.I)
_CRYPTO_YYMMDD = re.compile(r"^NX\.F\.OPT\.[A-Z0-9]+-\d+-(\d{6})", re.I)
_UNKNOWN_DAYS = 10_000
# Kickoff within this many days counts as "close" for harvest priority tiers.
CLOSE_MAX_DAYS = 3



@dataclass(frozen=True)
class RfqGapItem:
    """One RFQ true-gap key ranked by demand."""

    book: str
    key: str
    demand: int
    meta: dict[str, str] | None = None


def tip_poly_us_prefixes(store: Any) -> frozenset[str]:
    """Inner Polymarket US league codes from the activated tip."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return frozenset()
    out: set[str] = set()
    for row in store.leagues_for(rid):
        code = us_league_code(row)
        if code:
            out.add(code)
    return frozenset(out)


def tip_poly_prefixes(store: Any) -> frozenset[str]:
    """Polymarket slug_prefix values from the activated tip."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return frozenset()
    out: set[str] = set()
    for row in store.leagues_for(rid):
        for ex in row.exchanges or []:
            if str(ex.get("sportsbook") or "").lower() != "polymarket":
                continue
            if ex.get("enabled") is False:
                continue
            settings = ex.get("settings") or {}
            if not isinstance(settings, dict):
                continue
            prefix = str(settings.get("slug_prefix") or "").strip()
            if prefix:
                out.add(prefix)
    return frozenset(out)


def poly_skip_reason(
    key: str,
    wired: frozenset[str],
    *,
    wired_us: frozenset[str] | None = None,
) -> str:
    """Legacy wired/unwired classifier (harvest no longer pre-skips on this).

    Gap-propose tries a fix first and records a post-attempt reason instead.
    """
    prefix = key.strip().casefold()
    if not prefix or prefix == "(null)":
        return "poly_null_prefix"
    wired_all = {p.casefold() for p in wired}
    if wired_us:
        wired_all |= {p.casefold() for p in wired_us}
    if prefix not in wired_all:
        return "needs_league_card"
    return "wired_optic_or_stamp"


RfqGapRow = tuple[str, str, int] | tuple[str, str, int, dict[str, str]]


def rank_rfq_gaps(
    rows: Sequence[RfqGapRow | RfqGapItem],
    *,
    limit: int = MAX_EVENTS,
    today: date | None = None,
) -> list[RfqGapItem]:
    """Filter + rank; each book keeps its own ``limit``."""
    day = today or datetime.now(tz=UTC).date()
    by_book: dict[str, list[RfqGapItem]] = {book: [] for book in HARVEST_BOOKS}
    for row in rows:
        if isinstance(row, RfqGapItem):
            book, key, demand, meta = row.book, row.key, row.demand, row.meta
        elif len(row) >= 4:
            book, key, demand = str(row[0]), str(row[1]), int(row[2])
            meta = row[3] if isinstance(row[3], dict) else {}
        else:
            book, key, demand = str(row[0]), str(row[1]), int(row[2])
            meta = {}
        if not key or book not in by_book:
            continue
        by_book[book].append(RfqGapItem(book=book, key=key, demand=demand, meta=meta or {}))
    out: list[RfqGapItem] = []
    for book in HARVEST_BOOKS:
        items = by_book[book]
        floor = _demand_threshold(items)
        items.sort(key=lambda item, f=floor: _rank_key(item, day, f))
        if book == BOOK_CRYPTO:
            out.extend(
                diversify_probe_items(items, probe_limit=limit, per_bucket=MAX_PER_BUCKET)
            )
        else:
            out.extend(items[:limit])
    return out


def series_bucket(book: str, key: str, *, meta: str = "") -> str:
    """Crypto sport key used to cap and skip a harvest bucket; other books share one."""
    if book != "crypto":
        return f"{book}:OTHER"
    matched = _CRYPTO_SPORT.match(key.strip().upper())
    sport = matched.group(1) if matched else "OTHER"
    tour = str(meta or "").strip().upper()
    if sport == "TENNIS" and tour:
        return f"crypto:TENNIS:{tour}"
    return f"crypto:{sport}"


def diversify_probe_items(
    items: list[RfqGapItem],
    *,
    probe_limit: int,
    per_bucket: int = MAX_PER_BUCKET,
) -> list[RfqGapItem]:
    """Keep rank order but cap each series so one ITF book cannot fill the pool."""
    taken: dict[str, int] = {}
    primary: list[RfqGapItem] = []
    overflow: list[RfqGapItem] = []
    for item in items:
        bucket = series_bucket(item.book, item.key)
        if taken.get(bucket, 0) < per_bucket:
            primary.append(item)
            taken[bucket] = taken.get(bucket, 0) + 1
        else:
            overflow.append(item)
    if len(primary) >= probe_limit:
        return primary[:probe_limit]
    return (primary + overflow)[:probe_limit]


def drop_dead_buckets(keys: list[str], book: str, dead: set[str]) -> list[str]:
    """Drop series that already exhausted their missing_optic streak."""
    return [key for key in keys if series_bucket(book, key) not in dead]


def note_unproductive(
    dead: set[str],
    streaks: dict[str, int],
    bucket: str,
    kind: str,
) -> None:
    """Skip the rest of a series after consecutive Optic-less probes."""
    if bucket in dead:
        return
    if kind not in {"missing_optic", "title_miss"}:
        streaks[bucket] = 0
        return
    streaks[bucket] = streaks.get(bucket, 0) + 1
    if streaks[bucket] >= MAX_SLOT_MISSES:
        dead.add(bucket)


def _demand_threshold(items: Sequence[RfqGapItem]) -> int:
    """Median demand in this book's pool — at or above counts as demanding."""
    demands = sorted(item.demand for item in items)
    if not demands:
        return 0
    return demands[len(demands) // 2]


def _is_close(kick: date | None, today: date) -> bool:
    """True when kickoff is today or within CLOSE_MAX_DAYS."""
    bucket, days = _kick_rank(kick, today)
    return bucket == 0 and days <= CLOSE_MAX_DAYS


def _priority_tier(item: RfqGapItem, today: date, demand_floor: int) -> int:
    """0=close (next 3 days), 1=demanding, 2=remainder."""
    kick = _kickoff_date(item.book, item.key)
    if _is_close(kick, today):
        return 0
    if item.demand >= demand_floor:
        return 1
    return 2


def _rank_key(
    item: RfqGapItem, today: date, demand_floor: int,
) -> tuple[int | str, ...]:
    """Close first (high demand, then soonest), then demanding, then rest."""
    kick = _kickoff_date(item.book, item.key)
    bucket, days = _kick_rank(kick, today)
    tier = _priority_tier(item, today, demand_floor)
    if tier == 0:
        return (tier, -item.demand, days, item.book, item.key)
    if tier == 1:
        # Future demanding before unknown/past of the same demand.
        return (tier, -item.demand, bucket, days, item.book, item.key)
    return (tier, bucket, days, -item.demand, item.book, item.key)


def _kick_rank(kick: date | None, today: date) -> tuple[int, int]:
    """0=today/future (soonest first), 1=unknown date, 2=already started."""
    if kick is None:
        return 1, _UNKNOWN_DAYS
    delta = (kick - today).days
    if delta >= 0:
        return 0, delta
    return 2, -delta


def _kickoff_date(book: str, key: str) -> date | None:
    """Kickoff day from a crypto symbol; else None (Kalshi tickers are opaque)."""
    if book == "crypto":
        matched = _CRYPTO_YYMMDD.match(key.strip())
        return _from_yymmdd(matched.group(1)) if matched else None
    return None


def _from_yymmdd(raw: str) -> date | None:
    """Parse crypto YYMMDD into a date, or None if invalid."""
    try:
        return datetime.strptime(f"20{raw}", "%Y%m%d").date()
    except ValueError:
        return None


def fetch_rfq_inventory(
    store: Any,
    *,
    project: str | None = None,
    limit: int = INVENTORY_PAGE,
    query_fn: Any | None = None,
    exclude_keys: set[tuple[str, str]] | None = None,
    terminal_query_fn: Any | None = None,
    fail_closed_ledger: bool = False,
) -> list[RfqGapItem]:
    """Top RFQ true gaps: close (high demand first), then demanding, then rest."""
    from mappers.control_plane.gap_inventory_bq import fetch_rfq_inventory_bq

    return fetch_rfq_inventory_bq(
        store,
        project=project,
        limit=limit,
        query_fn=query_fn,
        exclude_keys=exclude_keys,
        terminal_query_fn=terminal_query_fn,
        fail_closed_ledger=fail_closed_ledger,
    )


def _inventory_meta(row: Any) -> dict[str, str]:
    """Optional BQ columns carried into harvest walkers."""
    meta: dict[str, str] = {}
    market_ticker = str(getattr(row, "market_ticker", "") or "").strip()
    if market_ticker:
        meta["market_ticker"] = market_ticker
    px_event = str(getattr(row, "px_event_id", "") or "").strip()
    px_line = str(getattr(row, "px_line_id", "") or "").strip()
    if px_event:
        meta["px_event_id"] = px_event
    if px_line:
        meta["px_line_id"] = px_line
    market_name = str(getattr(row, "market_name", "") or "").strip()
    if market_name:
        meta["market_name"] = market_name
    for key in ("rules_primary", "contract_terms_url", "yes_sub_title"):
        value = str(getattr(row, key, "") or "").strip()
        if value:
            meta[key] = value
    return meta
