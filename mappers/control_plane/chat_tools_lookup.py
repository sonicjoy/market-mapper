"""Composite lookup tools: tip search + rules_filter ui_actions."""

from __future__ import annotations

from typing import Any

from mappers.control_plane import chat_tools_bq as bq


def lookup_entities(store: Any, q: str, limit: int = 20) -> dict[str, Any]:
    """Search tip entities and open Rules (entities) with the same q."""
    needle = (q or "").strip()
    result = _entity_rows(store, needle, limit)
    result["ui_actions"] = _rules_actions("entities", needle)
    if result["count"] == 0 and needle:
        result["offer_pin"] = {
            "hint": "unmapped",
            "q": needle,
            "message": f"No tip alias matched `{needle}`. Call offer_pin to stage a pin.",
        }
    return result


def lookup_leagues(store: Any, q: str, limit: int = 20) -> dict[str, Any]:
    """Search tip leagues and open Rules (leagues)."""
    needle = (q or "").strip()
    result = bq.lookup_leagues(store, needle, limit)
    result["ui_actions"] = _rules_actions("leagues", needle)
    return result


def lookup_rules(
    store: Any,
    kind: str,
    q: str,
    *,
    sportsbook: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Unified tip lookup by Rules tab kind."""
    k = (kind or "entities").strip().lower()
    if k == "leagues":
        return lookup_leagues(store, q, limit)
    if k == "market_rules":
        return lookup_market_rules(store, q, sportsbook=sportsbook, limit=limit)
    return lookup_entities(store, q, limit)


def lookup_market_rules(
    store: Any,
    q: str,
    *,
    sportsbook: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search tip market rules; open Rules; flag ignored rows."""
    needle = (q or "").strip()
    book = (sportsbook or "").strip().lower()
    rows = _market_rows(store, needle=needle, book=book, limit=max(limit, 50))
    ignored = [r for r in rows if str(r.get("action") or "") == "ignore"]
    mapped = [r for r in rows if str(r.get("action") or "") != "ignore"]
    q_out = needle or book
    return {
        "count": len(rows),
        "mapped": len(mapped),
        "ignored": len(ignored),
        "market_rules": rows[:limit],
        "ignored_rows": ignored[:limit],
        "ui_actions": _rules_actions("market_rules", q_out),
    }


def _market_rows(
    store: Any, *, needle: str, book: str, limit: int
) -> list[dict[str, Any]]:
    """Tip market rules filtered by optional q and sportsbook."""
    if needle:
        raw = bq.lookup_market_rules(store, needle, limit=limit)
        rows = list(raw.get("market_rules") or [])
    else:
        rows = _all_market_rows(store, limit=limit)
    if book:
        rows = [r for r in rows if str(r.get("sportsbook") or "").lower() == book]
    return rows


def _all_market_rows(store: Any, limit: int) -> list[dict[str, Any]]:
    rid = store.current_rule_set_id
    if not rid:
        return []
    rows: list[dict[str, Any]] = []
    for mr in store.market_rules_for(rid):
        rows.append(
            {
                "league": mr.league,
                "sportsbook": mr.sportsbook,
                "source_key": mr.source_key,
                "source_key_type": mr.source_key_type,
                "action": mr.action,
                "canonical_market_type": mr.canonical_market_type,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _rules_actions(kind: str, q: str) -> list[dict[str, str]]:
    params_q = q.strip()
    path = f"/rules?kind={kind}&q={params_q}" if params_q else f"/rules?kind={kind}"
    return [
        {"type": "navigate", "path": path},
        {"type": "rules_filter", "kind": kind, "q": params_q},
    ]


def _entity_rows(store: Any, q: str, limit: int) -> dict[str, Any]:
    rid = store.current_rule_set_id
    needle = q.strip().lower()
    rows: list[dict[str, Any]] = []
    if not rid or not needle:
        return {"count": 0, "entities": []}
    for ent in store.entities_for(rid):
        for alias in ent.aliases:
            blob = " ".join(
                [
                    ent.league,
                    ent.canonical_key,
                    ent.canonical_name or "",
                    str(alias.get("alias_value", "")),
                    str(alias.get("sportsbook", "")),
                ]
            ).lower()
            if needle not in blob:
                continue
            rows.append(
                {
                    "league": ent.league,
                    "canonical_key": ent.canonical_key,
                    "entity_name": ent.canonical_name or ent.canonical_key,
                    "entity_type": ent.entity_type,
                    "sportsbook": alias.get("sportsbook"),
                    "code": alias.get("alias_value"),
                    "alias_kind": alias.get("alias_kind", "code"),
                }
            )
            if len(rows) >= max(1, min(limit, 50)):
                return {"count": len(rows), "entities": rows}
    return {"count": len(rows), "entities": rows}
