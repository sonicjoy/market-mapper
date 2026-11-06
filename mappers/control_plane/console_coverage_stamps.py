"""Shape published market_mapping rows for Coverage stamps panel."""

from __future__ import annotations

import json
from typing import Any

from mappers.control_plane.league_review import book_label

_GRID_BOOK_ALIASES: dict[str, str] = {
    "kalshi": "kalshi",
    "crypto.com": "crypto.com",
    "optic": "optic",
    "polymarket": "polymarket",
    "polymarket (usa)": "polymarket_usa",
    "polymarket_usa": "polymarket_usa",
    "px": "px",
    "prophet x": "px",
    "prophetx": "px",
    "novig": "novig",
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _grid_book(sportsbook: str) -> str:
    key = _norm(sportsbook).lower()
    return _GRID_BOOK_ALIASES.get(key, key)


def _parse_source_ids(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def format_stamp_source_id(sportsbook: str, source_ids: Any) -> str:
    """Book-specific primary id for the stamps table."""
    ids = _parse_source_ids(source_ids)
    book = _grid_book(sportsbook)
    if book == "kalshi":
        return _norm(ids.get("market_id"))
    if book == "crypto.com":
        return _norm(ids.get("symbol"))
    if book in {"polymarket", "polymarket_usa", "novig"}:
        return _norm(ids.get("selection_id"))
    if book == "px":
        event_id = _norm(ids.get("event_id"))
        line_id = _norm(ids.get("line_id") or ids.get("selection_id"))
        if event_id and line_id:
            return f"{event_id} / {line_id}"
        return event_id or line_id
    market_id = _norm(ids.get("market_id"))
    if market_id:
        return market_id
    selection_id = _norm(ids.get("selection_id"))
    if selection_id:
        return selection_id
    return _norm(ids.get("symbol"))


def stamp_entity_label(row: dict[str, Any]) -> str:
    selection = _norm(row.get("selection"))
    if selection:
        return selection
    return _norm(row.get("entity"))


def stamp_line_label(row: dict[str, Any]) -> str:
    for key in ("line", "points"):
        val = row.get(key)
        if val is None or val == "":
            continue
        text = _norm(val)
        if text:
            return text
    return "—"


def stamp_side_label(row: dict[str, Any]) -> str:
    for key in ("side", "selection_line"):
        text = _norm(row.get(key))
        if text:
            return text
    return "—"


def stamp_contract_side(source_ids: Any) -> str:
    """Yes/no on the sportsbook contract, when source_ids stores one.

    Kalshi moneyline complements share a ticker across both teams. The team
    lives in ``side``; yes versus no lives in ``selection_id``. Token ids
    (Polymarket, Novig) stay out of this column.
    """
    side = _norm(_parse_source_ids(source_ids).get("selection_id")).lower()
    if side in {"yes", "no"}:
        return side
    return ""


def coverage_stamp_row(row: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing stamp row for Coverage detail."""
    book = _grid_book(_norm(row.get("sportsbook")))
    return {
        "sportsbook": book,
        "sportsbook_label": book_label(book),
        "market_type": _norm(row.get("market_type")),
        "market_id": _norm(row.get("market_id")),
        "entity": stamp_entity_label(row),
        "line": stamp_line_label(row),
        "side": stamp_side_label(row),
        "contract_side": stamp_contract_side(row.get("source_ids")),
        "source_id": format_stamp_source_id(book, row.get("source_ids")),
        "last_updated": row.get("last_updated"),
    }
