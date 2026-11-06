"""Console page snapshot for Mapper Chat skills (structured UI state)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from mappers.control_plane.chat_prefill import normalize_entry_prefill
from mappers.control_plane.console_rules_query import RulesQuery, parse_rules_query

# SPA paths (nav labels: Editor, Cart, Proposed, Rules, Coverage, Unmapped).
EDITOR_PATH = "/entry"
CART_PATH = "/cart"
PROPOSED_PATH = "/review"
RULES_PATH = "/rules"
COVERAGE_PATH = "/coverage"
UNMAPPED_PATH = "/unmapped"
_NAV_PREFIXES = (
    EDITOR_PATH,
    CART_PATH,
    PROPOSED_PATH,
    RULES_PATH,
    COVERAGE_PATH,
    UNMAPPED_PATH,
    "/api-docs",
    "/inbox",
)


@dataclass
class ConsolePage:
    """Trader console view sent from the dock each turn."""

    path: str = ""
    tab: str = ""
    entry: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    unmapped: dict[str, Any] = field(default_factory=dict)
    cart: list[dict[str, Any]] = field(default_factory=list)
    review_ref: str = ""


def parse_page_context(raw: dict[str, Any] | None) -> ConsolePage:
    """Normalize client page_context into a ConsolePage."""
    if not raw:
        return ConsolePage()
    cart_raw = raw.get("cart") or raw.get("cart_items") or []
    cart: list[dict[str, Any]] = (
        [c for c in cart_raw if isinstance(c, dict)] if isinstance(cart_raw, list) else []
    )
    entry = _as_dict(raw.get("entry"))
    tab = str(raw.get("tab") or entry.get("tab") or "").strip()
    return ConsolePage(
        path=str(raw.get("path") or "").strip(),
        tab=tab,
        entry=entry,
        rules=_as_dict(raw.get("rules")),
        coverage=_as_dict(raw.get("coverage")),
        unmapped=_as_dict(raw.get("unmapped")),
        cart=cart,
        review_ref=str(raw.get("review_ref") or "").strip(),
    )


def entry_field(page: ConsolePage, key: str) -> str:
    """Read one Editor form field from the page snapshot."""
    val = page.entry.get(key)
    return str(val).strip() if val is not None else ""


def rules_list(page: ConsolePage, key: str) -> list[str]:
    """Multi-select Rules dropdown values (league / sportsbook / canonical / action)."""
    raw = page.rules.get(key)
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def rules_kind(page: ConsolePage) -> str:
    kind = str(page.rules.get("kind") or "").strip()
    return kind if kind in {"entities", "leagues", "market_rules"} else ""


def page_league(page: ConsolePage) -> str:
    """League from the active Explore page, else Editor, else Rules."""
    path = page.path.split("?", 1)[0]
    if path.startswith(COVERAGE_PATH):
        return _explore_field(page.coverage, "league") or entry_field(page, "league")
    if path.startswith(UNMAPPED_PATH):
        # Browse filters only. Empty All must not inherit Editor leftover league.
        return _explore_field(page.unmapped, "league")
    return entry_field(page, "league") or _first(rules_list(page, "league"))


def page_sportsbook(page: ConsolePage) -> str:
    """Sportsbook from Unmapped platform, else Editor, else Rules."""
    path = page.path.split("?", 1)[0]
    if path.startswith(UNMAPPED_PATH):
        plat = _explore_field(page.unmapped, "platform")
        if plat:
            return plat
    return entry_field(page, "sportsbook") or _first(rules_list(page, "sportsbook"))


def slot_from_page_or_message(page: ConsolePage, message: str, key: str) -> str:
    """Prefer console entry field, else empty (caller extracts from message)."""
    return entry_field(page, key)


def merge_rules_view(page: ConsolePage, **overrides: Any) -> dict[str, Any]:
    """Console Rules URL plus skill overrides (q/kind from the message)."""
    out: dict[str, Any] = {
        "kind": rules_kind(page) or "entities",
        "q": str(page.rules.get("q") or "").strip(),
        "league": rules_list(page, "league"),
        "sportsbook": rules_list(page, "sportsbook"),
        "canonical": rules_list(page, "canonical"),
        "action": rules_list(page, "action"),
        "sort": str(page.rules.get("sort") or "").strip(),
        "dir": str(page.rules.get("dir") or "asc"),
    }
    for key, value in overrides.items():
        if value is not None:
            out[key] = value
    return out


def rules_query_from_page(page: ConsolePage, **overrides: Any) -> RulesQuery:
    """Same RulesQuery the explorer table uses, from the dock snapshot."""
    view = merge_rules_view(page, **overrides)
    return parse_rules_query(
        q=str(view.get("q") or "") or None,
        kind=str(view.get("kind") or "entities"),
        league=_as_str_list(view.get("league")),
        sportsbook=_as_str_list(view.get("sportsbook")),
        canonical=_as_str_list(view.get("canonical")),
        action=_as_str_list(view.get("action")),
        sort=str(view.get("sort") or "") or None,
        sort_dir=str(view.get("dir") or "asc"),
    )


def read_console_snapshot(page: ConsolePage) -> dict[str, Any]:
    """Tool-shaped snapshot of what the trader sees."""
    return {
        "path": page.path,
        "tab": page.tab,
        "entry": page.entry,
        "rules": page.rules,
        "coverage": page.coverage,
        "unmapped": page.unmapped,
        "cart": page.cart,
        "review_ref": page.review_ref,
    }


def coverage_href(*, league: str = "", sport: str = "", fixture: str = "") -> str:
    """Coverage URL with optional league/sport/fixture query."""
    return _href(COVERAGE_PATH, league=league, sport=sport, fixture=fixture)


def unmapped_href(*, league: str = "", sport: str = "", platform: str = "") -> str:
    """Unmapped URL with optional league/sport/platform query."""
    return _href(UNMAPPED_PATH, league=league, sport=sport, platform=platform)


def show_on_console(
    *,
    navigate: str | None = None,
    tab: str | None = None,
    prefill: dict[str, Any] | None = None,
    rules_kind: str | None = None,
    rules_q: str | None = None,
    rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build ui_actions for navigate + tab/prefill or rules_filter."""
    actions: list[dict[str, Any]] = []
    path = _safe_navigate(navigate)
    if path:
        actions.append({"type": "navigate", "path": path})
    if tab:
        actions.append({"type": "switch_tab", "tab": tab})
    if prefill:
        fields = normalize_entry_prefill(prefill, tab) or prefill
        actions.append(
            {
                "type": "prefill_form",
                "tab": fields.get("tab") or tab or "alias",
                "fields": fields,
            }
        )
    filt = dict(rules or {})
    if rules_kind:
        filt["kind"] = rules_kind
    if rules_q is not None:
        filt["q"] = rules_q
    if filt.get("kind"):
        action = _rules_filter_action(filt)
        actions.append(action)
        if not path:
            actions.append({"type": "navigate", "path": _rules_path(action)})
    return actions


def _rules_filter_action(filt: dict[str, Any]) -> dict[str, Any]:
    action: dict[str, Any] = {
        "type": "rules_filter",
        "kind": str(filt.get("kind") or "entities"),
        "q": str(filt.get("q") or "").strip(),
    }
    for key in ("league", "sportsbook", "canonical", "action"):
        values = _as_str_list(filt.get(key))
        if values:
            action[key] = values
    sort = str(filt.get("sort") or "").strip()
    if sort:
        action["sort"] = sort
        action["dir"] = str(filt.get("dir") or "asc")
    return action


def _rules_path(action: dict[str, Any]) -> str:
    parts = [f"kind={action['kind']}"]
    if action.get("q"):
        parts.append(f"q={action['q']}")
    for key in ("league", "sportsbook", "canonical", "action"):
        for value in action.get(key) or []:
            parts.append(f"{key}={value}")
    return "/rules?" + "&".join(parts)


def _as_str_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _as_dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _explore_field(view: dict[str, Any], key: str) -> str:
    val = view.get(key)
    return str(val).strip() if val is not None else ""


def _href(path: str, **params: str) -> str:
    q = {k: v.strip() for k, v in params.items() if v and v.strip()}
    return path + ("?" + urlencode(q) if q else "")


def _safe_navigate(path: str | None) -> str | None:
    """Allow only console SPA paths (Editor URL stays /entry)."""
    raw = (path or "").strip()
    if not raw or "://" in raw or raw.startswith("//"):
        return None
    if raw == "/":
        return raw
    root = raw.split("?", 1)[0]
    for prefix in _NAV_PREFIXES:
        if root == prefix or root.startswith(prefix + "/"):
            return raw
    return None


def _first(values: list[str]) -> str:
    return values[0] if values else ""


def console_has_context(page: ConsolePage) -> bool:
    """True when Editor, Explore filters, Proposed, or the cart already frame the turn."""
    return bool(
        page.entry.get("league")
        or page.rules.get("q")
        or rules_kind(page)
        or rules_list(page, "league")
        or rules_list(page, "sportsbook")
        or _explore_field(page.coverage, "league")
        or _explore_field(page.unmapped, "league")
        or _explore_field(page.unmapped, "q")
        or page.review_ref
        or page.cart
    )
