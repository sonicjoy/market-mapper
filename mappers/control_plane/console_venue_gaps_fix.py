"""Why + stage for a Venue gaps node (fixture / market / selection).

A node's rules are drafted from a bounded sample of its unmapped selections,
each run through the same Why / cart pipeline as Explore → Unmapped, then
merged by item id. A market rule is league-scoped, so one selection per
contract type is enough; alias pins come from the fixture's crypto ids.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mappers.alias_kinds import ID_KIND
from mappers.control_plane.console_unmapped import build_unmapped_tip_index, enrich_unmapped_row
from mappers.control_plane.console_unmapped_fixes import stage_unmapped_cart, summarize_mappable_items
from mappers.control_plane.console_unmapped_why_api import unmapped_probe_fn
from mappers.control_plane.gap_crypto_catalogue import prefetch_crypto_catalogue
from mappers.control_plane.league_cfg_memo import league_cfg_memo

MAX_NODE_ROWS = 12

CatalogueFn = Callable[[Sequence[str]], dict[str, dict[str, Any]]]


def _crypto_names(cat: dict[str, Any] | None) -> dict[str, str]:
    """``crypto_id → team name`` from the security_def seed (home / away)."""
    if not cat:
        return {}
    pairs = ((cat.get("home_id"), cat.get("home_name")), (cat.get("away_id"), cat.get("away_name")))
    return {str(cid): str(name or "") for cid, name in pairs if cid}


def leg_rows(
    rows: Sequence[dict[str, Any]],
    store: Any | None,
    *,
    catalogue_fn: CatalogueFn | None = None,
) -> list[dict[str, Any]]:
    """Client node rows → enriched Unmapped inventory rows with real crypto ids."""
    picked = [row for row in rows if str(row.get("key") or "").strip()][:MAX_NODE_ROWS]
    keys = [str(row["key"]).strip() for row in picked]
    lookup = catalogue_fn or (lambda syms: prefetch_crypto_catalogue(syms))
    catalogue = lookup(keys) if keys else {}
    index = build_unmapped_tip_index(store)
    out: list[dict[str, Any]] = []
    for row, key in zip(picked, keys, strict=True):
        raw = {
            "platform": "crypto",
            "key": key,
            "platform_leg_description": str(row.get("description") or key),
            "league": str(row.get("league") or "") or None,
            "fixture": str(row.get("fixture") or "") or None,
            "sport": str(row.get("sport") or "") or None,
            "contract_type": str(row.get("contract_type") or ""),
            "market_group": str(row.get("market_group") or ""),
        }
        names = _crypto_names(catalogue.get(key))
        raw["crypto_ids"] = list(names)
        leg = enrich_unmapped_row(raw, index)
        leg["crypto_names"] = names
        out.append(leg)
    return out


def _usable(item: dict[str, Any], row: dict[str, Any]) -> bool:
    """Drop the symbol-as-alias fallback: it would pin ``NX.F.OPT…`` as an entity."""
    return not (item.get("kind") == "alias" and item.get("label") == row.get("key"))


def _named(item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Show ``Arsenal FC · 90002148`` rather than a bare crypto id."""
    name = (row.get("crypto_names") or {}).get(str(item.get("label") or ""))
    if item.get("kind") != "alias" or not name:
        return item
    return {**item, "label": f"{name} · {item['label']}"}


def _row_items(rows: list[dict[str, Any]], store: Any | None) -> list[list[dict[str, Any]]]:
    """Mappable items per leg, alias ids named and symbol fallbacks dropped."""
    return [[_named(i, row) for i in summarize_mappable_items(row, store) if _usable(i, row)] for row in rows]


def _merge(per_row: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Union items across legs by id; fixable if any leg can draft it."""
    merged: dict[str, dict[str, Any]] = {}
    for items in per_row:
        for item in items:
            prev = merged.get(item["id"])
            public = {k: v for k, v in item.items() if k not in {"cart", "prefill"}}
            if prev is None:
                merged[item["id"]] = {**public, "sources": 1}
                continue
            prev["sources"] += 1
            prev["mapped"] = prev["mapped"] and item["mapped"]
            prev["fixable"] = prev["fixable"] or item["fixable"]
    return list(merged.values())


def _reasons(items: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One operator-facing line on what the node needs."""
    fixable = [item for item in items if item["fixable"]]
    if not rows:
        return [_reason("nothing_sampled", "No unmapped selections under this node.")]
    if fixable:
        return [_reason("draftable", f"{len(fixable)} rule(s) drafted from {len(rows)} selection(s).", True)]
    if not any(row.get("league") for row in rows):
        return [_reason("league_not_in_tip", "League is not on the tip for crypto.com — fix the league first.")]
    if items and all(item["mapped"] for item in items):
        return [
            _reason(
                "rules_complete",
                "Every rule these selections need is already on the tip. The gap is the "
                "line or player not being offered by Optic, or the mapper run — not a missing rule.",
            )
        ]
    return [
        _reason(
            "no_cart_fix",
            "No rule to draft: the market has no live Optic canonical, needs code, "
            "or the line is not offered by Optic.",
        )
    ]


def _reason(code: str, text: str, actionable: bool = False) -> dict[str, Any]:
    """Reason dict in the Unmapped Why shape."""
    return {"code": code, "text": text, "actionable": actionable}


def why_venue_gap_node(
    store: Any | None,
    rows: Sequence[dict[str, Any]],
    *,
    catalogue_fn: CatalogueFn | None = None,
) -> dict[str, Any]:
    """Merged mappable items + reasons for a node's sampled selections."""
    legs = leg_rows(rows, store, catalogue_fn=catalogue_fn)
    with league_cfg_memo():
        items = _merge(_row_items(legs, store))
    return {
        "mappable_items": items,
        "has_fixes": any(item["fixable"] for item in items),
        "reasons": _reasons(items, legs),
        "sampled": len(legs),
    }


def _dedupe(cart_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop cart items drafted twice from different legs."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in cart_items:
        key = (str(item.get("kind") or ""), repr(item.get("payload")))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _blind_alias(item: dict[str, Any]) -> dict[str, Any] | None:
    """The Unmapped prefill fallback: an entity named after its own id, not a real pin."""
    payload = item.get("payload") or {}
    aliases = payload.get("aliases") or []
    if item.get("kind") != "entity_alias" or len(aliases) != 1:
        return None
    value = str(aliases[0].get("alias_value") or "")
    return aliases[0] if value and payload.get("canonical_key") == value else None


def _editor_state(alias: dict[str, Any], league: str, names: dict[str, str]) -> dict[str, Any]:
    """Editor alias-form state for an id the probe could not resolve."""
    code = str(alias.get("alias_value") or "")
    return {
        "tab": "alias",
        "league": league,
        "sportsbook": str(alias.get("sportsbook") or "crypto.com"),
        "code": code,
        "alias_kind": ID_KIND,
        "entity_name": names.get(code, ""),
    }


def _split_blind(cart: list[dict[str, Any]], legs: list[dict[str, Any]]) -> tuple[list, list]:
    """Separate real cart pins from blind self-named ones (sent to the Editor)."""
    names = {cid: name for leg in legs for cid, name in (leg.get("crypto_names") or {}).items()}
    real: list[dict[str, Any]] = []
    editor: list[dict[str, Any]] = []
    for item in _dedupe(cart):
        alias = _blind_alias(item)
        if alias is None:
            real.append(item)
            continue
        league = str((item.get("payload") or {}).get("league") or "")
        code = str(alias.get("alias_value") or "")
        label = f"{names.get(code) or code} · {code}"
        editor.append({"label": label, "entry_state": _editor_state(alias, league, names)})
    return real, editor


def _stage_rows(
    legs: list[dict[str, Any]],
    store: Any | None,
    wanted: set[str],
    probe: Any | None,
    evidence_fn: Any | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Stage each wanted id once, from the first leg that offers it."""
    covered: set[str] = set()
    cart: list[dict[str, Any]] = []
    for leg, items in zip(legs, _row_items(legs, store), strict=True):
        need = {i["id"] for i in items if i["fixable"] and i["id"] in wanted} - covered
        if not need:
            continue
        staged = stage_unmapped_cart(leg, store, sorted(need), probe_fn=probe, evidence_fn=evidence_fn)
        if staged.get("ok"):
            covered |= need
            cart.extend(staged["cart_items"])
    return cart, covered


def stage_venue_gap_node(
    store: Any | None,
    rows: Sequence[dict[str, Any]],
    item_ids: Sequence[str],
    *,
    evidence_fn: Any | None = None,
    catalogue_fn: CatalogueFn | None = None,
) -> dict[str, Any]:
    """Cart items for the chosen merged ids; each id is drafted from the first row offering it.

    Alias pins the probe could not resolve to a tip entity come back under
    ``needs_editor`` (Editor alias-form state) instead of as blind cart items.
    """
    wanted = {str(item_id).strip() for item_id in item_ids if str(item_id).strip()}
    if not wanted:
        return {"ok": False, "error": "no items selected", "cart_items": [], "needs_editor": []}
    legs = leg_rows(rows, store, catalogue_fn=catalogue_fn)
    probe = unmapped_probe_fn(store) if store is not None else None
    with league_cfg_memo():
        cart, covered = _stage_rows(legs, store, wanted, probe, evidence_fn)
    real, editor = _split_blind(cart, legs)
    if not real and not editor:
        return {"ok": False, "error": "could not draft cart items", "cart_items": [], "needs_editor": []}
    return {"ok": True, "cart_items": real, "needs_editor": editor, "not_drafted": sorted(wanted - covered)}
