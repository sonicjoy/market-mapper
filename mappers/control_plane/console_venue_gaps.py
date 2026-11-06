"""Explore → Venue gaps: the venue's live catalogue vs published market_mapping.

The reverse of Unmapped: start from everything the venue lists (not RFQ
demand) and show what has no mapping row, league → fixture → market →
selection. One memoised selection-level catalogue read (~47k crypto.com
symbols) plus one memoised demand read serve both the league × fixture
rollup and every fixture expand, so browsing the tree never re-scans BigQuery.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from mappers.control_plane.console_fixture_phase import row_matches_phase
from mappers.control_plane.console_missing import (
    contract_type_set,
    parse_window_bound,
)
from mappers.control_plane.console_unmapped import _as_utc, _ttko_hours
from mappers.control_plane.console_venue_gaps_league import crypto_league_index, league_status
from mappers.control_plane.console_venue_gaps_sql import (
    CATALOG_SQL,
    DEMAND_SQL,
    VenueGapQueryFn,
    default_venue_gap_query,
)

SUPPORTED_PLATFORMS = ("crypto",)
NO_LEAGUE = "(no league)"


def _unsupported(platform: str) -> dict[str, Any]:
    """Empty response for a venue the tab does not read yet."""
    return {
        "platform": platform,
        "leagues": [],
        "totals": _totals([]),
        "market_options": [],
        "error": f"Venue gaps does not cover {platform!r} yet (crypto only).",
    }


def _no_league() -> dict[str, Any]:
    """Symbols crypto.com publishes without a LEAGUE: nothing to pin them to."""
    return {"status": "not_in_tip", "league": None, "league_label": None, "sport": None, "candidates": [], "fix": None}


def _fixture_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Rollup row → fixture node with kickoff, ttko and counts."""
    start = _as_utc(raw.get("start_at"))
    total = int(raw.get("total") or 0)
    mapped = int(raw.get("mapped") or 0)
    return {
        "fixture_key": str(raw.get("fixture_key") or ""),
        "name": str(raw.get("fixture_name") or raw.get("fixture_key") or ""),
        "start_date": start.isoformat() if start else None,
        "ttko_hours": _ttko_hours(start),
        "total": total,
        "mapped": mapped,
        "unmapped": total - mapped,
        "demand": int(raw.get("demand") or 0),
    }


def _matches_q(needle: str, meta_league: str, tip: dict[str, Any], fixture: dict[str, Any]) -> bool:
    """Case-insensitive search over league codes, tip slug/label and fixture."""
    if not needle:
        return True
    hay = " ".join(
        [
            meta_league,
            str(tip.get("league") or ""),
            str(tip.get("league_label") or ""),
            fixture["name"],
            fixture["fixture_key"],
        ]
    ).casefold()
    return needle in hay


def _league_node(meta_league: str, sport_grouping: str, tip: dict[str, Any]) -> dict[str, Any]:
    """Empty league node; counts accumulate as fixtures are added."""
    return {
        "meta_league": meta_league,
        "sport_grouping": sport_grouping or None,
        "tip": tip,
        "total": 0,
        "mapped": 0,
        "unmapped": 0,
        "demand": 0,
        "fixtures": [],
    }


def _add_fixture(node: dict[str, Any], fixture: dict[str, Any]) -> None:
    """Attach a fixture and add its counts to the league totals."""
    node["fixtures"].append(fixture)
    for field in ("total", "mapped", "unmapped", "demand"):
        node[field] += fixture[field]


def _totals(leagues: list[dict[str, Any]]) -> dict[str, int]:
    """Page-level summary tiles over the filtered tree."""
    fixtures = [fx for league in leagues for fx in league["fixtures"]]
    return {
        "selections": sum(league["total"] for league in leagues),
        "mapped": sum(league["mapped"] for league in leagues),
        "leagues": len(leagues),
        "leagues_not_in_tip": sum(1 for league in leagues if league["tip"]["status"] != "in_tip"),
        "fixtures": len(fixtures),
        "fixtures_unmapped": sum(1 for fx in fixtures if fx["total"] and not fx["mapped"]),
    }


def _in_window(start: str | None, kickoff_from: datetime | None, kickoff_to: datetime | None) -> bool:
    """Fixture kickoff inside [from, to]; no kickoff fails once a bound is set."""
    if kickoff_from is None and kickoff_to is None:
        return True
    if not start:
        return False
    at = datetime.fromisoformat(start)
    return (kickoff_from is None or at >= kickoff_from) and (kickoff_to is None or at <= kickoff_to)


def _fold_fixtures(rows: Iterable[dict[str, Any]], markets: set[str]) -> list[dict[str, Any]]:
    """Per-contract rollup rows -> one row per league x fixture, keeping only picked markets."""
    folded: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        contract = str(raw.get("contract_type") or "").strip().lower()
        if markets and contract not in markets:
            continue
        key = (str(raw.get("meta_league") or ""), str(raw.get("fixture_key") or ""))
        hit = folded.get(key)
        if hit is None:
            folded[key] = {**raw, "total": int(raw.get("total") or 0), "mapped": int(raw.get("mapped") or 0)}
            folded[key]["demand"] = int(raw.get("demand") or 0)
            continue
        for field in ("total", "mapped", "demand"):
            hit[field] += int(raw.get(field) or 0)
        start = _as_utc(raw.get("start_at"))
        prev = _as_utc(hit.get("start_at"))
        if start is not None and (prev is None or start < prev):
            hit["start_at"] = raw.get("start_at")
    return list(folded.values())


def _market_options(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Market names (contract_type) with selection counts, biggest unmapped gap first."""
    acc: dict[str, dict[str, Any]] = {}
    for raw in rows:
        name = str(raw.get("contract_type") or "").strip()
        if not name:
            continue
        slot = acc.setdefault(name, {"name": name, "total": 0, "unmapped": 0, "fixtures": 0})
        total = int(raw.get("total") or 0)
        slot["total"] += total
        slot["unmapped"] += total - int(raw.get("mapped") or 0)
        slot["fixtures"] += 1
    return sorted(acc.values(), key=lambda o: (-o["unmapped"], -o["total"], o["name"].lower()))


def _visible_rows(
    rows: list[dict[str, Any]],
    store: Any | None,
    *,
    phase: str,
    q: str | None,
    kickoff_from: datetime | None,
    kickoff_to: datetime | None,
) -> list[dict[str, Any]]:
    """Rollup rows that pass phase, search and the kickoff window (market filter not applied)."""
    index = crypto_league_index(store)
    needle = (q or "").strip().casefold()
    tips: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for raw in rows:
        meta = str(raw.get("meta_league") or "").strip() or NO_LEAGUE
        fixture = _fixture_row(raw)
        if not row_matches_phase({"ttko_hours": fixture["ttko_hours"]}, phase):
            continue
        if not _in_window(fixture["start_date"], kickoff_from, kickoff_to):
            continue
        tip = tips.get(meta)
        if tip is None:
            grouping = str(raw.get("sport_grouping") or "")
            tip = league_status(meta, grouping, index) if meta != NO_LEAGUE else _no_league()
            tips[meta] = tip
        if _matches_q(needle, meta, tip, fixture):
            out.append(raw)
    return out


def build_venue_gap_tree(
    rows: list[dict[str, Any]],
    store: Any | None,
    *,
    phase: str = "live",
    q: str | None = None,
    kickoff_from: datetime | None = None,
    kickoff_to: datetime | None = None,
    markets: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Group rollup rows into leagues, filter by phase / search / window / market, biggest gap first."""
    visible = _visible_rows(rows, store, phase=phase, q=q, kickoff_from=kickoff_from, kickoff_to=kickoff_to)
    return _tree(_fold_fixtures(visible, contract_type_set(markets)), store)


def _tree(rows: list[dict[str, Any]], store: Any | None) -> list[dict[str, Any]]:
    """Fixture-level rows (already filtered) -> league nodes, biggest gap first."""
    index = crypto_league_index(store)
    leagues: dict[str, dict[str, Any]] = {}
    for raw in rows:
        meta = str(raw.get("meta_league") or "").strip() or NO_LEAGUE
        fixture = _fixture_row(raw)
        node = leagues.get(meta)
        if node is None:
            grouping = str(raw.get("sport_grouping") or "")
            tip = league_status(meta, grouping, index) if meta != NO_LEAGUE else _no_league()
            node = _league_node(meta, grouping, tip)
        leagues[meta] = node
        _add_fixture(node, fixture)
    out = list(leagues.values())
    for node in out:
        node["fixtures"].sort(key=lambda fx: (fx["start_date"] is None, fx["start_date"] or ""))
    out.sort(key=lambda node: (-node["unmapped"], node["meta_league"]))
    return out


def load_catalogue(fetch: VenueGapQueryFn) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Selection-level catalogue rows and failed-RFQ demand per symbol."""
    rows = fetch(CATALOG_SQL, {})
    demand = {str(r.get("symbol") or ""): int(r.get("demand") or 0) for r in fetch(DEMAND_SQL, {})}
    return rows, demand


def rollup_rows(
    rows: list[dict[str, Any]], demand: dict[str, int], *, by_contract: bool = False
) -> list[dict[str, Any]]:
    """League x fixture counts from catalogue rows; ``by_contract`` splits each fixture per contract type.

    The per-contract rows let the page filter and facet on market name; ``_fold_fixtures``
    folds them back to one row per fixture.
    """
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        meta = str(row.get("meta_league") or "")
        contract = str(row.get("contract_type") or "") if by_contract else ""
        key = (meta, str(row.get("fixture_key") or ""), contract)
        agg = out.get(key)
        if agg is None:
            agg = out[key] = {
                "meta_league": meta,
                "sport_grouping": row.get("sport_grouping"),
                "fixture_key": key[1],
                "contract_type": contract,
                "fixture_name": row.get("fixture_name"),
                "start_at": row.get("event_at"),
                "total": 0,
                "mapped": 0,
                "demand": 0,
            }
        start = row.get("event_at")
        if start is not None and (agg["start_at"] is None or start < agg["start_at"]):
            agg["start_at"] = start
        agg["total"] += 1
        agg["mapped"] += 1 if row.get("is_mapped") else 0
        agg["demand"] += demand.get(str(row.get("symbol") or ""), 0)
    return list(out.values())


def list_venue_gaps(
    *,
    platform: str = "crypto",
    phase: str = "live",
    q: str | None = None,
    kickoff_from: str | None = None,
    kickoff_to: str | None = None,
    markets: str | list[str] | None = None,
    store: Any | None = None,
    query_fn: VenueGapQueryFn | None = None,
) -> dict[str, Any]:
    """League x fixture rollup for one venue.

    ``markets`` keeps only those market names (contract_type, any of).
    ``market_options`` lists every market name left after the other filters,
    ranked by unmapped selections, so the picker doubles as a biggest-gap list.
    """
    plat = (platform or "crypto").strip().lower()
    if plat not in SUPPORTED_PLATFORMS:
        return _unsupported(plat)
    try:
        window_from = parse_window_bound(kickoff_from, "kickoff_from")
        window_to = parse_window_bound(kickoff_to, "kickoff_to")
    except ValueError as exc:
        return {**_unsupported(plat), "error": str(exc)}
    try:
        rows, demand = load_catalogue(query_fn or default_venue_gap_query)
    except Exception as exc:  # noqa: BLE001 — surfaced on the page, not a 500
        return {**_unsupported(plat), "error": str(exc)}
    contract_rows = rollup_rows(rows, demand, by_contract=True)
    visible = _visible_rows(contract_rows, store, phase=phase, q=q, kickoff_from=window_from, kickoff_to=window_to)
    leagues = _tree(_fold_fixtures(visible, contract_type_set(markets)), store)
    return {
        "platform": plat,
        "leagues": leagues,
        "totals": _totals(leagues),
        "market_options": _market_options(visible),
        "error": None,
    }


_FULL_GAME = frozenset({"", "full-game", "full game", "full-match", "full match"})


def _market_label(head: dict[str, Any], selections: list[dict[str, Any]]) -> str:
    """``Contract type · period``, prefixed by the player for single-player props."""
    label = str(head.get("contract_type") or "") or "(no contract type)"
    period = str(head.get("period_type") or "").strip()
    if period.casefold() not in _FULL_GAME:
        label = f"{label} · {period}"
    people = {str(s.get("participant") or "") for s in selections}
    if "prop" in str(head.get("market_group") or "").casefold() and len(people) == 1 and "" not in people:
        return f"{people.pop()} · {label}"
    return label


def _selection(raw: dict[str, Any]) -> dict[str, Any]:
    """Catalogue row → selection leaf."""
    return {
        "key": str(raw.get("symbol") or ""),
        "outcome": str(raw.get("outcome") or raw.get("symbol") or ""),
        "participant": raw.get("participant") or None,
        "mapped": bool(raw.get("is_mapped")),
        "demand": int(raw.get("demand") or 0),
    }


def _markets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a fixture's selections by crypto.com market id."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        grouped[str(raw.get("market_id") or raw.get("contract_type") or "")].append(raw)
    out: list[dict[str, Any]] = []
    for market_id, raws in grouped.items():
        head = raws[0]
        group = str(head.get("market_group") or "")
        contract = str(head.get("contract_type") or "")
        selections = [_selection(raw) for raw in raws]
        mapped = sum(1 for s in selections if s["mapped"])
        out.append(
            {
                "market_id": market_id,
                "market_group": group,
                "contract_type": contract,
                "period_type": head.get("period_type") or None,
                "label": _market_label(head, raws),
                "total": len(selections),
                "mapped": mapped,
                "unmapped": len(selections) - mapped,
                "demand": sum(s["demand"] for s in selections),
                "selections": selections,
            }
        )
    return out


def get_venue_gap_fixture(
    *,
    platform: str = "crypto",
    fixture_key: str,
    store: Any | None = None,
    query_fn: VenueGapQueryFn | None = None,
) -> dict[str, Any]:
    """Markets and selections for one catalogue fixture (from the memoised catalogue)."""
    plat = (platform or "crypto").strip().lower()
    key = fixture_key.strip()
    empty = {"platform": plat, "fixture_key": key, "markets": [], "error": None}
    if plat not in SUPPORTED_PLATFORMS:
        return {**empty, "error": _unsupported(plat)["error"]}
    try:
        catalogue, demand = load_catalogue(query_fn or default_venue_gap_query)
    except Exception as exc:  # noqa: BLE001 — surfaced on the page, not a 500
        return {**empty, "error": str(exc)}
    rows = sorted(
        (
            {**row, "demand": demand.get(str(row.get("symbol") or ""), 0)}
            for row in catalogue
            if row.get("fixture_key") == key
        ),
        key=lambda r: tuple(str(r.get(f) or "") for f in ("market_group", "contract_type", "market_id", "symbol")),
    )
    if not rows:
        return empty
    head = rows[0]
    meta = str(head.get("meta_league") or "").strip()
    tip = league_status(meta, str(head.get("sport_grouping") or ""), crypto_league_index(store))
    return {
        **empty,
        "name": str(head.get("fixture_name") or key),
        "meta_league": meta or None,
        "league": tip["league"] if tip["status"] == "in_tip" else None,
        "sport": tip["sport"],
        "markets": _markets(rows),
    }
