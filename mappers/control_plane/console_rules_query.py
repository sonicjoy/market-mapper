"""Human-readable rules explorer: search, filter, sort, paginate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from mappers.control_plane.entity_types import match_entity_type_for_row
from mappers.control_plane.entry import league_label
from mappers.control_plane.market_rule_card import market_rule_card, served_words

CANONICAL_NONE = "__none__"

_KIND_KEYS = {
    "entities": "entities",
    "leagues": "leagues",
    "market_rules": "market_rules",
}


@dataclass(frozen=True)
class RulesQuery:
    """Console rules explorer request (no rule_set_id)."""

    q: str | None = None
    kind: str = "entities"
    limit: int = 100
    offset: int = 0
    at: str | None = None
    league: tuple[str, ...] = ()
    sportsbook: tuple[str, ...] = ()
    canonical: tuple[str, ...] = ()
    action: tuple[str, ...] = ()
    sort: str | None = None
    sort_dir: str = "asc"


def _values(raw: list[str] | None) -> tuple[str, ...]:
    """Flatten repeated and comma-separated query values."""
    out: list[str] = []
    for item in raw or []:
        for part in str(item).split(","):
            value = part.strip()
            if value:
                out.append(value)
    return tuple(out)


def parse_rules_query(
    *,
    q: str | None = None,
    kind: str = "entities",
    limit: int = 100,
    offset: int = 0,
    at: str | None = None,
    league: list[str] | None = None,
    sportsbook: list[str] | None = None,
    canonical: list[str] | None = None,
    action: list[str] | None = None,
    sort: str | None = None,
    sort_dir: str = "asc",
) -> RulesQuery:
    """Normalize explorer query params."""
    return RulesQuery(
        q=q,
        kind=kind or "entities",
        limit=limit,
        offset=offset,
        at=at,
        league=_values(league),
        sportsbook=_values(sportsbook),
        canonical=_values(canonical),
        action=_values(action),
        sort=(sort or "").strip() or None,
        sort_dir="desc" if (sort_dir or "").lower() == "desc" else "asc",
    )


def _page(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    key: str,
    lim: int,
    off: int,
) -> dict[str, Any]:
    """Package a filtered rules list into a paginated console response."""
    return {
        "kind": kind,
        "count": len(rows),
        "limit": lim,
        "offset": off,
        key: rows[off : off + lim],
    }


def _match(needle: str, row: dict[str, Any]) -> bool:
    """True when needle is empty or appears in any row value."""
    if not needle:
        return True
    return needle in " ".join(str(v) for v in row.values()).lower()


def _league_rule_rows(store: Any, rid: str | None, needle: str) -> list[dict[str, Any]]:
    """Build human-readable league rows for the rules explorer."""
    rows: list[dict[str, Any]] = []
    for lg in store.leagues_for(rid) if rid else []:
        row = {
            "league": lg.league,
            "league_label": league_label(lg.league),
            "sport": lg.sport,
            "optic_league_id": lg.optic_league_id,
            "fixture_source": lg.fixture_source,
            "fixture_horizon_hours": lg.fixture_horizon_hours,
            "enabled": lg.enabled,
            "entity_type": match_entity_type_for_row(lg),
            "exchanges": list(lg.exchanges),
        }
        searchable = {k: v for k, v in row.items() if k != "exchanges"}
        searchable["sportsbooks"] = " ".join(str(ex.get("sportsbook", "")) for ex in lg.exchanges)
        if _match(needle, searchable):
            rows.append(row)
    return rows


def _market_rule_rows(store: Any, rid: str | None, needle: str) -> list[dict[str, Any]]:
    """Build human-readable market-rule rows for the rules explorer."""
    rows: list[dict[str, Any]] = []
    for mr in store.market_rules_for(rid) if rid else []:
        if str(mr.sportsbook or "").lower() == "kalshi":
            # Kalshi maps from its own typed fields; old tip rows are inert.
            continue
        row = {
            "league": mr.league or "",
            "league_label": league_label(mr.league or ""),
            "sportsbook_label": mr.sportsbook,
            "sportsbook": mr.sportsbook,
            "rule_kind": mr.rule_kind,
            "source_key_type": mr.source_key_type,
            "source_key": mr.source_key,
            "action": mr.action,
            "canonical_market_type": mr.canonical_market_type,
            "priority": mr.priority,
            "enabled": mr.enabled,
            "match_operator": mr.match_operator,
            "line_offset": mr.line_offset,
            "yes_side": mr.yes_side,
            "side_swap": mr.side_swap,
            "official_description": mr.official_description,
            "citation_url": mr.citation_url,
            "notes": mr.notes,
        }
        if not _match(needle, row):
            continue
        words = served_words(mr)
        card = market_rule_card(mr, league=str(mr.league or ""))
        row["offset_text"] = words["offset"]
        row["yes_side_text"] = words["yes_side"]
        row["side_swap_text"] = words["side_swap"]
        row["venue"] = card["venue"]
        row["transform"] = card["transform"]
        row["optic"] = card["optic"]
        row["card_label"] = card["label"]
        rows.append(row)
    return rows


def _alias_pin(alias: dict[str, Any]) -> dict[str, str]:
    book = str(alias.get("sportsbook") or "")
    return {
        "sportsbook": book,
        "sportsbook_label": book,
        "alias_kind": str(alias.get("alias_kind") or "code"),
        "code": str(alias.get("alias_value") or ""),
    }


def _entity_searchable(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested aliases so q matches any pin on the canonical."""
    pins = row.get("aliases") or []
    return {
        "league": row.get("league"),
        "league_label": row.get("league_label"),
        "entity_name": row.get("entity_name"),
        "entity_type": row.get("entity_type"),
        "canonical_key": row.get("canonical_key"),
        "sportsbooks": " ".join(str(p.get("sportsbook") or "") for p in pins),
        "codes": " ".join(str(p.get("code") or "") for p in pins),
        "kinds": " ".join(str(p.get("alias_kind") or "") for p in pins),
    }


def _entity_group_row(ent: Any) -> dict[str, Any]:
    """One canonical entity with every sportsbook pin kept together."""
    return {
        "league": ent.league,
        "league_label": league_label(ent.league),
        "entity_name": ent.canonical_name or ent.canonical_key,
        "entity_type": ent.entity_type,
        "canonical_key": ent.canonical_key,
        "aliases": [_alias_pin(alias) for alias in (ent.aliases or [])],
    }


def _entity_group_rows(store: Any, rid: str | None, needle: str) -> list[dict[str, Any]]:
    """Build canonical-grouped entity rows for the rules explorer."""
    rows: list[dict[str, Any]] = []
    for ent in store.entities_for(rid) if rid else []:
        row = _entity_group_row(ent)
        if _match(needle, _entity_searchable(row)):
            rows.append(row)
    return rows


def _rows_for_kind(store: Any, rid: str | None, kind: str, needle: str) -> list[dict[str, Any]]:
    """Select explorer rows for one kind after free-text match."""
    if kind == "leagues":
        return _league_rule_rows(store, rid, needle)
    if kind == "market_rules":
        return _market_rule_rows(store, rid, needle)
    return _entity_group_rows(store, rid, needle)


def _sportsbook_hit(row: dict[str, Any], kind: str, books: set[str]) -> bool:
    """True when the row's sportsbook(s) intersect the selected set."""
    if kind == "leagues":
        names = {str(ex.get("sportsbook") or "") for ex in (row.get("exchanges") or [])}
        return bool(names & books)
    if kind == "entities":
        names = {str(pin.get("sportsbook") or "") for pin in (row.get("aliases") or [])}
        return bool(names & books)
    return (row.get("sportsbook") or "") in books


def _canonical_hit(row: dict[str, Any], selected: set[str]) -> bool:
    """True when canonical type (or empty) is in the selected set."""
    raw = row.get("canonical_market_type")
    token = CANONICAL_NONE if not raw else str(raw)
    return token in selected


def _row_matches(
    row: dict[str, Any],
    kind: str,
    leagues: set[str],
    books: set[str],
    cans: set[str],
    actions: set[str],
) -> bool:
    """AND across fields; unused fields are ignored for this kind."""
    if leagues and row.get("league") not in leagues:
        return False
    if books and not _sportsbook_hit(row, kind, books):
        return False
    if kind != "market_rules":
        return True
    if cans and not _canonical_hit(row, cans):
        return False
    return not actions or (row.get("action") or "") in actions


def _apply_filters(rows: list[dict[str, Any]], query: RulesQuery) -> list[dict[str, Any]]:
    """Keep rows matching every non-empty multi-select field."""
    leagues = set(query.league)
    books = set(query.sportsbook)
    cans = set(query.canonical)
    actions = set(query.action)
    if not (leagues or books or cans or actions):
        return rows
    return [
        r for r in rows
        if _row_matches(r, query.kind, leagues, books, cans, actions)
    ]


def _league_books_sort(row: dict[str, Any]) -> str:
    names = sorted(str(ex.get("sportsbook") or "") for ex in (row.get("exchanges") or []))
    return " ".join(names)


_SORT_KEYS: dict[str, dict[str, Callable[[dict[str, Any]], Any]]] = {
    "entities": {
        "league": lambda r: (r.get("league_label") or "", r.get("league") or ""),
        "entity": lambda r: r.get("entity_name") or "",
        "sportsbook": lambda r: " ".join(
            sorted(str(p.get("sportsbook") or "") for p in (r.get("aliases") or []))
        ),
        "code": lambda r: " ".join(
            sorted(str(p.get("code") or "") for p in (r.get("aliases") or []))
        ),
    },
    "leagues": {
        "league": lambda r: (r.get("league_label") or "", r.get("league") or ""),
        "sport": lambda r: r.get("sport") or "",
        "sportsbooks": _league_books_sort,
        "optic_league_id": lambda r: r.get("optic_league_id") or "",
        "fixture_source": lambda r: r.get("fixture_source") or "",
        "enabled": lambda r: 0 if r.get("enabled") else 1,
    },
    "market_rules": {
        "league": lambda r: (r.get("league_label") or "", r.get("league") or ""),
        "sportsbook": lambda r: r.get("sportsbook_label") or r.get("sportsbook") or "",
        "source_key": lambda r: r.get("source_key") or "",
        "action": lambda r: r.get("action") or "",
        "canonical": lambda r: r.get("canonical_market_type") or "",
        "line_offset": lambda r: (
            r.get("line_offset") if isinstance(r.get("line_offset"), (int, float)) else 10**9
        ),
        "yes_side": lambda r: r.get("yes_side") or "",
        "side_swap": lambda r: (
            1 if r.get("side_swap") is True else 0 if r.get("side_swap") is False else 2
        ),
        "official_description": lambda r: r.get("official_description") or "",
        "citation_url": lambda r: r.get("citation_url") or "",
        "notes": lambda r: r.get("notes") or "",
    },
}


def _sort_value(fn: Callable[[dict[str, Any]], Any], row: dict[str, Any]) -> Any:
    """Case-fold string keys so sort is case-insensitive."""
    val = fn(row)
    if isinstance(val, str):
        return val.lower()
    if isinstance(val, tuple):
        return tuple(x.lower() if isinstance(x, str) else x for x in val)
    return val


def _sort_rows(rows: list[dict[str, Any]], query: RulesQuery) -> list[dict[str, Any]]:
    """Stable-sort by a kind-specific column; unknown columns keep order."""
    fn = (_SORT_KEYS.get(query.kind) or {}).get(query.sort or "")
    if fn is None:
        return rows
    reverse = query.sort_dir == "desc"
    return sorted(rows, key=lambda row: _sort_value(fn, row), reverse=reverse)


def filtered_rule_rows(store: Any, query: RulesQuery) -> list[dict[str, Any]]:
    """All explorer rows for q + dropdowns, before sort/page."""
    if query.kind not in _KIND_KEYS:
        query = replace(query, kind="entities")
    rid = store.rule_set_as_of(query.at) if query.at else store.current_rule_set_id
    needle = (query.q or "").strip().lower()
    rows = _rows_for_kind(store, rid, query.kind, needle)
    return _apply_filters(rows, query)


def search_human_rules(store: Any, query: RulesQuery) -> dict[str, Any]:
    """Search/filter/sort the human rules explorer without exposing rule_set_id."""
    if query.kind not in _KIND_KEYS:
        query = replace(query, kind="entities")
    lim = max(1, min(int(query.limit), 500))
    off = max(0, int(query.offset))
    rows = _sort_rows(filtered_rule_rows(store, query), query)
    return _page(rows, kind=query.kind, key=_KIND_KEYS[query.kind], lim=lim, off=off)
