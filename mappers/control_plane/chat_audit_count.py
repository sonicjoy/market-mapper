"""Count helpers for Mapper Chat audit "how many" questions."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.console_rules_query import RulesQuery, filtered_rule_rows

_KIND_LABEL = {
    "entities": "entities",
    "leagues": "leagues",
    "market_rules": "market rules",
}


def audit_rule_counts(store: Any, query: RulesQuery) -> dict[str, int]:
    """Count tip rules matching the Rules explorer filter (full list, not paged)."""
    rows = filtered_rule_rows(store, query)
    if query.kind == "market_rules":
        ignored = sum(1 for row in rows if row.get("action") == "ignore")
        return {"total": len(rows), "ignored": ignored}
    return {"total": len(rows)}


def format_audit_count_reply(
    query: RulesQuery,
    counts: dict[str, int],
    *,
    wants_ignored: bool,
) -> str:
    """Build a markdown reply that states the count(s)."""
    kind = query.kind
    label = _KIND_LABEL.get(kind, kind)
    who = _scope_label(query)
    total = counts.get("total", 0)
    if kind == "market_rules" and wants_ignored:
        ignored = counts.get("ignored", 0)
        return f"{who} has **{total}** {label} (**{ignored}** ignored)."
    if wants_ignored:
        return (
            f"There's no 'ignored' status on {label}; "
            f"{who} has **{total}** {label}."
        )
    return f"{who} has **{total}** {label}."


def _scope_label(query: RulesQuery) -> str:
    bits: list[str] = []
    if query.q:
        bits.append(f"`{query.q}`")
    bits.extend(query.league)
    bits.extend(query.sportsbook)
    bits.extend(query.action)
    return " ".join(bits) if bits else "Tip"


def audit_opening_reply(kind: str, q: str) -> str:
    """Non-count audit navigation blurb (unchanged behaviour)."""
    return f"Opening Rules ({kind}){f' for `{q}`' if q else ''}."
