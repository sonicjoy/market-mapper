"""BQ read helpers for Mapper Chat tools (tip-scoped)."""

from __future__ import annotations

from typing import Any


def lookup_leagues(store: Any, q: str, limit: int = 20) -> dict[str, Any]:
    """Search tip leagues by slug / optic id / sport."""
    rid = store.current_rule_set_id
    needle = q.strip().lower()
    if not rid or not needle:
        return {"count": 0, "leagues": []}
    rows: list[dict[str, Any]] = []
    for row in store.leagues_for(rid):
        blob = " ".join([row.league, row.sport, row.optic_league_id]).lower()
        if needle not in blob:
            continue
        rows.append(
            {
                "league": row.league,
                "sport": row.sport,
                "optic_league_id": row.optic_league_id,
                "enabled": row.enabled,
                "exchanges": [
                    {
                        "sportsbook": e.get("sportsbook"),
                        "enabled": e.get("enabled"),
                        "source_league_id": e.get("source_league_id"),
                    }
                    for e in (row.exchanges or [])
                ],
            }
        )
        if len(rows) >= max(1, min(limit, 50)):
            break
    return {"count": len(rows), "leagues": rows}


def lookup_market_rules(store: Any, q: str, limit: int = 20) -> dict[str, Any]:
    """Search tip market rules by league / book / source_key."""
    rid = store.current_rule_set_id
    needle = q.strip().lower()
    if not rid or not needle:
        return {"count": 0, "market_rules": []}
    rows: list[dict[str, Any]] = []
    for mr in store.market_rules_for(rid):
        blob = " ".join(
            [
                mr.league,
                mr.sportsbook,
                mr.source_key,
                mr.action,
                mr.canonical_market_type or "",
            ]
        ).lower()
        if needle not in blob:
            continue
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
        if len(rows) >= max(1, min(limit, 50)):
            break
    return {"count": len(rows), "market_rules": rows}


def parity_summary(store: Any, limit: int = 20) -> dict[str, Any]:
    """Recent dual-read parity audits (OK and mismatch)."""
    if not hasattr(store, "list_parity_events"):
        return {"count": 0, "events": []}
    events = store.list_parity_events(limit=max(1, min(limit, 50)))
    slim = [
        {
            "event_id": e.get("event_id"),
            "event_type": e.get("event_type"),
            "occurred_at": e.get("occurred_at"),
            "rule_set_id": e.get("rule_set_id"),
            "mismatch_count": e.get("mismatch_count"),
            "summary": (e.get("summary") or e.get("message") or "")[:200],
        }
        for e in events
    ]
    return {"count": len(slim), "events": slim}
