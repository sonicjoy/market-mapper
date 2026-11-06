"""Editor `/entry` prefill for Mapper Chat `show_on_console`."""

from __future__ import annotations

from typing import Any

_IGNORE = frozenset({"ignored", "ignore"})


def market_rule_prefill(
    *,
    league: str,
    sportsbook: str,
    source_key: str,
    action: str = "map",
    canonical_market_type: str | None = None,
    source_key_type: str = "",
    mode: str = "create",
) -> dict[str, Any]:
    """Market-tab fields the Editor dropdowns actually read."""
    ignore = action.strip().lower() == "ignore"
    out: dict[str, Any] = {
        "tab": "market",
        "mode": mode,
        "league": league,
        "sportsbook": sportsbook,
        "source_key": source_key,
        "action": "ignore" if ignore else "map",
        "canonical_market_type": None if ignore else canonical_market_type,
    }
    if source_key_type.strip():
        out["source_key_type"] = source_key_type.strip()
    return out


def market_prefill_from_cart(
    items: list[dict[str, Any]],
    *,
    league: str,
    sportsbook: str,
    market: str,
) -> dict[str, Any]:
    """Prefill Editor from the latest staged market pin, else the named market."""
    pin = _latest_market_pin(items)
    fallback = market.strip() or "moneyline"
    canonical = str(pin.get("canonical_market_type") or fallback).strip() or None
    return market_rule_prefill(
        league=str(pin.get("league") or league),
        sportsbook=str(pin.get("sportsbook") or sportsbook),
        source_key=str(pin.get("source_key") or fallback),
        action=str(pin.get("action") or "map"),
        canonical_market_type=canonical,
        source_key_type=str(pin.get("source_key_type") or ""),
    )


def normalize_entry_prefill(
    prefill: dict[str, Any] | None,
    tab: str | None = None,
) -> dict[str, Any] | None:
    """Lift alias-shaped market fields onto canonical_market_type / source_key."""
    if not prefill:
        return prefill
    out = dict(prefill)
    tab_n = str(out.get("tab") or tab or "").strip()
    if tab_n:
        out["tab"] = tab_n
    if tab_n != "market":
        return out
    return _normalize_market(out)


def _latest_market_pin(items: list[dict[str, Any]]) -> dict[str, Any]:
    pin: dict[str, Any] = {}
    for item in items:
        if item.get("kind") != "mapping_market_rules":
            continue
        rules = (item.get("payload") or {}).get("rules") or []
        if isinstance(rules, list) and rules and isinstance(rules[0], dict):
            pin = dict(rules[0])
    return pin


def _normalize_market(out: dict[str, Any]) -> dict[str, Any]:
    ignore = _is_ignore(out)
    out["action"] = "ignore" if ignore else (str(out.get("action") or "map").strip() or "map")
    if not str(out.get("source_key") or "").strip():
        code = str(out.get("code") or "").strip()
        if code:
            out["source_key"] = code
    if ignore:
        out["canonical_market_type"] = None
        return out
    if str(out.get("canonical_market_type") or "").strip():
        return out
    for key in ("entity_name", "canonical_key", "canonical"):
        val = str(out.get(key) or "").strip()
        if val and val.lower() not in _IGNORE:
            out["canonical_market_type"] = val
            break
    return out


def _is_ignore(out: dict[str, Any]) -> bool:
    action = str(out.get("action") or "").strip().lower()
    name = str(out.get("entity_name") or "").strip().lower()
    return action == "ignore" or name in _IGNORE
