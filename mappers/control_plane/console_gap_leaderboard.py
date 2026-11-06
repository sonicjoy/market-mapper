"""Explore -> Gap leaderboard: the biggest mapping gaps on every venue, ranked.

The grouped query (``console_gap_leaderboard_sql``) returns three row levels
per venue: platform, fixture and market (``g_fixture`` / ``g_market`` are the
SQL ``grouping()`` flags). This module resolves leagues, applies the page
filters, and builds platform -> league -> fixture -> market.

Counts:
* ``demand`` - distinct failed RFQs in the window touching the node. Platform
  and fixture rows are distinct counts from SQL; a league is the sum of its
  fixtures. With a market filter a fixture is the sum of its picked markets,
  so an RFQ with legs in two picked markets counts twice (``demand_is_sum``).
* ``unmapped`` - distinct unmapped selections: catalogue selections with no
  mapping where a catalogue is wired (crypto.com), else distinct failed legs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.console_gap_leaderboard_rows import (
    PLATFORM_LABELS,
    build_indexes,
    fix_link,
    fixture_name,
    kickoff_fields,
    resolve_league,
)
from mappers.control_plane.console_gap_leaderboard_sql import (
    DEFAULT_WINDOW_HOURS,
    gap_leaderboard_sql,
    leaderboard_cached_at,
    leaderboard_query,
)
from mappers.control_plane.console_venue_gaps_sql import VenueGapQueryFn

SORTS = ("demand", "unmapped")


def _window_bound(raw: str | None, name: str) -> datetime | None:
    """One kickoff bound (ISO; naive means UTC); ValueError names the bad param."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is not an ISO datetime: {text!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _market_set(markets: list[str] | None) -> set[str]:
    """Lower-cased picked market names; empty means all."""
    return {m.strip().lower() for m in markets or [] if m and m.strip()}


def _int(value: Any) -> int:
    """BQ INT64 / None / str -> int."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unmapped(row: dict[str, Any]) -> int:
    """Catalogue unmapped when the venue has a catalogue, else distinct failed legs."""
    if row.get("catalogue_unmapped") is not None:
        return _int(row.get("catalogue_unmapped"))
    return _int(row.get("legs"))


def _counts(row: dict[str, Any]) -> dict[str, Any]:
    """Shared count fields for any node."""
    return {
        "demand": _int(row.get("demand")),
        "legs": _int(row.get("legs")),
        "unmapped": _unmapped(row),
        "catalogue_total": row.get("catalogue_total"),
        "last_seen": str(row["last_seen"]) if row.get("last_seen") else None,
    }


def _split(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """SQL rows -> (platform rows by book, fixture rows, market rows)."""
    platforms: dict[str, dict[str, Any]] = {}
    fixtures: list[dict[str, Any]] = []
    markets: list[dict[str, Any]] = []
    for row in rows:
        if _int(row.get("g_fixture")):
            platforms[str(row.get("book") or "")] = row
        elif _int(row.get("g_market")):
            fixtures.append(row)
        else:
            markets.append(row)
    return platforms, fixtures, markets


def _fixture_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Identity of a fixture across fixture and market rows."""
    return (str(row.get("book") or ""), str(row.get("league_hint") or ""), str(row.get("fixture_key") or ""))


def _in_window(start: str | None, lo: datetime | None, hi: datetime | None) -> bool:
    """Kickoff inside [lo, hi]; unknown kickoff fails once a bound is set."""
    if lo is None and hi is None:
        return True
    if not start:
        return False
    at = datetime.fromisoformat(start)
    return (lo is None or at >= lo) and (hi is None or at <= hi)


def _fixture_node(row: dict[str, Any], markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixture payload with its market children (not yet market-filtered)."""
    book = str(row.get("book") or "")
    kick = kickoff_fields(book, row)
    key = str(row.get("fixture_key") or "")
    children = [
        {
            "market": str(m.get("market") or "") or "(no market)",
            **_counts(m),
            "fix_link": fix_link(book, key, kick["ttko_hours"], str(m.get("market") or "") or None),
        }
        for m in markets
    ]
    return {
        "fixture_key": key,
        "name": fixture_name(book, row),
        **kick,
        **_counts(row),
        "fix_link": fix_link(book, key, kick["ttko_hours"]),
        "markets": children,
    }


def _pick_markets(node: dict[str, Any], wanted: set[str]) -> dict[str, Any] | None:
    """Keep only picked markets; fixture counts become the sum of those markets."""
    if not wanted:
        return node
    kept = [m for m in node["markets"] if m["market"].strip().lower() in wanted]
    if not kept:
        return None
    summed = {f: sum(_int(m[f]) for m in kept) for f in ("demand", "legs", "unmapped")}
    return {**node, **summed, "markets": kept, "demand_is_sum": True}


def _sort_key(sort: str):
    """Ranking key for any node: biggest first, the other metric breaks ties."""
    if sort == "unmapped":
        return lambda n: (-_int(n["unmapped"]), -_int(n["demand"]))
    return lambda n: (-_int(n["demand"]), -_int(n["unmapped"]))


def _market_options(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Market names over the (window-filtered) fixtures, biggest demand first."""
    acc: dict[str, dict[str, Any]] = {}
    for fx in fixtures:
        for m in fx["markets"]:
            slot = acc.setdefault(m["market"], {"name": m["market"], "demand": 0, "unmapped": 0, "fixtures": 0})
            slot["demand"] += _int(m["demand"])
            slot["unmapped"] += _int(m["unmapped"])
            slot["fixtures"] += 1
    return sorted(acc.values(), key=lambda o: (-o["demand"], -o["unmapped"], o["name"].lower()))


def _leagues(fixtures: list[tuple[dict[str, Any], dict[str, Any]]], sort: str) -> list[dict[str, Any]]:
    """(league, fixture) pairs -> ranked league nodes with summed counts."""
    by_key: dict[str, dict[str, Any]] = {}
    for league, fx in fixtures:
        node = by_key.setdefault(league["key"], {**league, "demand": 0, "legs": 0, "unmapped": 0, "fixtures": []})
        node["fixtures"].append(fx)
        for field in ("demand", "legs", "unmapped"):
            node[field] += _int(fx[field])
    key = _sort_key(sort)
    for node in by_key.values():
        node["fixtures"].sort(key=key)
        for fx in node["fixtures"]:
            fx["markets"].sort(key=key)
    return sorted(by_key.values(), key=key)


def _platform_node(
    book: str, sql_row: dict[str, Any] | None, leagues: list[dict[str, Any]], exact: bool
) -> dict[str, Any]:
    """Platform tile + its leagues. ``exact`` uses the SQL distinct counts."""
    if exact and sql_row is not None:
        counts = _counts(sql_row)
    else:
        counts = {f: sum(_int(lg[f]) for lg in leagues) for f in ("demand", "legs", "unmapped")}
    return {
        "id": book,
        "label": PLATFORM_LABELS.get(book, book),
        **counts,
        "demand_is_sum": not (exact and sql_row is not None),
        "leagues_not_in_tip": sum(1 for lg in leagues if not lg["in_tip"]),
        "leagues": leagues,
    }


def build_leaderboard(
    rows: list[dict[str, Any]],
    store: Any | None,
    *,
    platforms: list[str] | None = None,
    kickoff_from: datetime | None = None,
    kickoff_to: datetime | None = None,
    markets: list[str] | None = None,
    sort: str = "demand",
) -> dict[str, Any]:
    """Grouped SQL rows -> ``{platforms, market_options}`` for the page."""
    sort = sort if sort in SORTS else "demand"
    wanted_books = {p.strip().lower() for p in platforms or [] if p.strip()}
    wanted_markets = _market_set(markets)
    plat_rows, fixture_rows, market_rows = _split(rows)
    by_fixture: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for m in market_rows:
        by_fixture[_fixture_key(m)].append(m)
    indexes = build_indexes(store)
    kept: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    windowed: list[dict[str, Any]] = []
    for row in fixture_rows:
        book = str(row.get("book") or "")
        if wanted_books and book not in wanted_books:
            continue
        node = _fixture_node(row, by_fixture.get(_fixture_key(row), []))
        if not _in_window(node["start_date"], kickoff_from, kickoff_to):
            continue
        windowed.append(node)
        picked = _pick_markets(node, wanted_markets)
        if picked is not None:
            kept[book].append((resolve_league(book, str(row.get("league_hint") or ""), indexes), picked))
    exact = not (kickoff_from or kickoff_to or wanted_markets)
    books = [b for b in plat_rows if not wanted_books or b in wanted_books]
    nodes = [_platform_node(b, plat_rows.get(b), _leagues(kept.get(b, []), sort), exact) for b in books]
    nodes.sort(key=_sort_key(sort))
    return {"platforms": nodes, "market_options": _market_options(windowed)}


def list_gap_leaderboard(
    *,
    hours: int = DEFAULT_WINDOW_HOURS,
    platforms: list[str] | None = None,
    kickoff_from: str | None = None,
    kickoff_to: str | None = None,
    markets: list[str] | None = None,
    sort: str = "demand",
    store: Any | None = None,
    query_fn: VenueGapQueryFn | None = None,
) -> dict[str, Any]:
    """Every venue's mapping gaps, ranked by failed RFQs (or unmapped selections)."""
    base: dict[str, Any] = {"hours": hours, "sort": sort, "platforms": [], "market_options": [], "error": None}
    try:
        sql = gap_leaderboard_sql(int(hours))
        lo = _window_bound(kickoff_from, "kickoff_from")
        hi = _window_bound(kickoff_to, "kickoff_to")
    except (TypeError, ValueError) as exc:
        return {**base, "error": str(exc)}
    fetch = query_fn or leaderboard_query
    try:
        rows = fetch(sql, {})
    except Exception as exc:  # noqa: BLE001 - surfaced on the page, not a 500
        return {**base, "error": str(exc)}
    built = build_leaderboard(
        rows, store, platforms=platforms, kickoff_from=lo, kickoff_to=hi, markets=markets, sort=sort
    )
    return {**base, **built, "cached_at": leaderboard_cached_at(sql) if query_fn is None else None}
