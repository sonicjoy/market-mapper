"""Mappable-item badges and cart staging for console unmapped legs."""

from __future__ import annotations

from typing import Any

from mappers.alias_kinds import CRYPTO_ID_KINDS
from mappers.control_plane.console_unmapped_explain import explain_unmapped_leg
from mappers.control_plane.console_unmapped_markets import market_rule_badge
from mappers.control_plane.console_unmapped_poly import poly_team_labels
from mappers.control_plane.entity_types import match_entity_type, match_entity_type_for_league
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_fix import _cart_item
from mappers.control_plane.pin_flow import draft_and_verify
from mappers.handicap_name_crumb import is_selection_alias

_PLATFORM_BOOK = {
    "crypto": "crypto.com",
    "polymarket": "polymarket",
    "prophetx": "px",
}


def why_unmapped_leg(row: dict[str, Any], store: Any | None) -> dict[str, Any]:
    """On-demand mapping breakdown for one inventory row."""
    items = summarize_mappable_items(row, store)
    has_fixes = has_fixable_items(items)
    return {
        "mappable_items": items,
        "has_fixes": has_fixes,
        "reasons": explain_unmapped_leg(row, items, has_fixes=has_fixes, store=store),
    }


def summarize_mappable_items(row: dict[str, Any], store: Any | None) -> list[dict[str, Any]]:
    """League, alias, and market-rule badges from the live tip."""
    platform = str(row.get("platform") or "").lower()
    league = str(row.get("league") or "").strip()
    book = _PLATFORM_BOOK.get(platform, platform)
    items: list[dict[str, Any]] = []
    if league:
        mapped = _league_in_tip(store, league)
        items.append(
            _item(
                item_id=f"league:{league}",
                kind="league",
                label=row.get("league_label") or league_label(league),
                mapped=mapped,
                fixable=False,
            )
        )
    if platform == "polymarket":
        items.extend(_poly_alias_items(row, store, league, book))
    elif platform == "crypto":
        items.extend(_crypto_alias_items(row, store, league, book))
    items.extend(_market_rule_items(row, store, league, book))
    return items


def has_fixable_items(items: list[dict[str, Any]]) -> bool:
    return any(not item.get("mapped") and item.get("fixable") for item in items)


def stage_unmapped_cart(
    row: dict[str, Any],
    store: Any | None,
    item_ids: list[str],
    *,
    probe_fn: Any | None = None,
    evidence_fn: Any | None = None,
) -> dict[str, Any]:
    """Draft cart lines for selected grey badges on one inventory row."""
    items = summarize_mappable_items(row, store)
    wanted = {str(item_id).strip() for item_id in item_ids if str(item_id).strip()}
    selected = [item for item in items if item["id"] in wanted and not item.get("mapped") and item.get("fixable")]
    if not selected:
        return {"ok": False, "error": "no fixable items selected", "cart_items": []}
    cart_items: list[dict[str, Any]] = []
    probe_pins = _probe_pins(row, store, probe_fn=probe_fn, evidence_fn=evidence_fn)
    for item in selected:
        if item.get("cart"):
            cart_items.append(item["cart"])
            continue
        if item["kind"] == "alias":
            pin = _pin_for_alias(item, probe_pins)
            if pin is not None:
                cart_items.append(_cart_item(pin))
            elif item.get("prefill"):
                cart_items.append(_prefill_cart_item(item))
        elif item["kind"] == "market_rule" and item.get("cart"):
            cart_items.append(item["cart"])
    if not cart_items:
        return {"ok": False, "error": "could not draft cart items", "cart_items": []}
    return {"ok": True, "cart_items": cart_items}


def _item(
    *,
    item_id: str,
    kind: str,
    label: str,
    mapped: bool,
    fixable: bool,
    cart: dict[str, Any] | None = None,
    prefill: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item_id,
        "kind": kind,
        "label": label,
        "mapped": mapped,
        "fixable": fixable and not mapped,
    }
    if cart is not None:
        out["cart"] = cart
    if prefill is not None:
        out["prefill"] = prefill
    if meta:
        out.update(meta)
    return out


def _league_in_tip(store: Any | None, league: str) -> bool:
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if not rid or store is None or not hasattr(store, "leagues_for"):
        return False
    return any(
        str(row.league or "") == league and not getattr(row, "tombstone", False) for row in store.leagues_for(rid)
    )


def _poly_alias_items(
    row: dict[str, Any],
    store: Any | None,
    league: str,
    book: str,
) -> list[dict[str, Any]]:
    labels = poly_team_labels(row)
    if not labels:
        return []
    league_on_tip = _league_in_tip(store, league)
    out: list[dict[str, Any]] = []
    for label in labels:
        mapped = _poly_alias_mapped(store, league, book, label)
        residual = is_selection_alias(label)
        out.append(
            _item(
                item_id=f"alias:{label.casefold()}",
                kind="alias",
                label=label,
                mapped=mapped,
                fixable=bool(league and label and league_on_tip and not residual),
                prefill={
                    "tab": "alias",
                    "league": league,
                    "sportsbook": book,
                    "code": label,
                    "alias_kind": "name",
                    "entity_name": label,
                    "entity_type": _match_type(store, league),
                },
                meta={"code": label, "alias_kind": "name"},
            )
        )
    return out


def _crypto_alias_items(
    row: dict[str, Any],
    store: Any | None,
    league: str,
    book: str,
) -> list[dict[str, Any]]:
    symbol = str(row.get("key") or "").strip()
    if not symbol:
        return []
    ids = _crypto_ids(symbol, row)
    if not ids:
        return []
    tip = _tip_codes(store, league, ids, book="crypto.com", alias_kind="crypto_id")
    out: list[dict[str, Any]] = []
    for cid in ids:
        mapped = bool(tip.get(cid))
        out.append(
            _item(
                item_id=f"alias:{cid}",
                kind="alias",
                label=cid,
                mapped=mapped,
                fixable=bool(league and cid),
                prefill={
                    "tab": "alias",
                    "league": league,
                    "sportsbook": book,
                    "code": cid,
                    "alias_kind": "crypto_id",
                    "entity_type": _match_type(store, league),
                },
                meta={"code": cid, "alias_kind": "crypto_id"},
            )
        )
    return out


def _market_rule_items(
    row: dict[str, Any],
    store: Any | None,
    league: str,
    book: str,
) -> list[dict[str, Any]]:
    badge = market_rule_badge(row, store, league, book)
    if badge is None:
        return []
    canonical = str(badge["canonical"])
    pin = badge["pin"]
    return [
        _item(
            item_id=f"rule:{canonical}",
            kind="market_rule",
            label=canonical.replace("_", " "),
            mapped=bool(badge["mapped"]),
            fixable=pin is not None,
            cart=_cart_item(pin) if pin is not None else None,
        ),
    ]


def _tip_codes(
    store: Any | None,
    league: str,
    codes: list[str],
    *,
    book: str,
    alias_kind: str = "code",
) -> dict[str, list[str]]:
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if not rid or store is None or not league or not hasattr(store, "entities_for"):
        return {}
    ents = [ent for ent in store.entities_for(rid) if ent.league == league and not getattr(ent, "tombstone", False)]
    out: dict[str, list[str]] = {}
    for code in codes:
        key = code.upper() if alias_kind == "code" else code
        owners = [
            ent.canonical_key
            for ent in ents
            if any(
                str(alias.get("sportsbook") or "").lower() == book
                and _same_alias_kind(str(alias.get("alias_kind") or ""), alias_kind)
                and str(alias.get("alias_value") or "") == (code if alias_kind != "code" else code.upper())
                and alias.get("enabled", True)
                for alias in ent.aliases
            )
        ]
        if owners:
            out[key] = owners
    return out


def _same_alias_kind(tip_kind: str, wanted: str) -> bool:
    """crypto.com ids are stored as ``external_id`` or ``crypto_id``; the mapper reads both."""
    if wanted in CRYPTO_ID_KINDS:
        return tip_kind in CRYPTO_ID_KINDS
    return tip_kind == wanted


def _poly_alias_mapped(
    store: Any | None,
    league: str,
    book: str,
    label: str,
) -> bool:
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if not rid or store is None or not league:
        return False
    needle = label.casefold()
    for ent in store.entities_for(rid):
        if ent.league != league or getattr(ent, "tombstone", False):
            continue
        for alias in ent.aliases:
            if str(alias.get("sportsbook") or "").lower() != book:
                continue
            if str(alias.get("alias_value") or "").casefold() == needle:
                return True
        if needle in {str(ent.canonical_name or "").casefold(), str(ent.canonical_key or "").casefold()}:
            return True
    return False


def _crypto_ids(symbol: str, row: dict[str, Any]) -> list[str]:
    """Participant crypto_id values only — never the NX contract symbol."""
    raw = row.get("crypto_ids")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(value) for value in raw if value]
    return []


def _probe_pins(
    row: dict[str, Any],
    store: Any | None,
    *,
    probe_fn: Any | None,
    evidence_fn: Any | None = None,
) -> list[dict[str, Any]]:
    if store is None or probe_fn is None:
        return []
    platform = str(row.get("platform") or "").lower()
    key = str(row.get("key") or "")
    if not key or platform != "crypto":
        return []
    probe = probe_fn(platform, key, str(row.get("league") or ""))
    rows = list(probe.get("results") or [])
    staged = draft_and_verify(store, rows, "crypto.com", probe=evidence_fn)
    return list(staged.get("pins") or [])


def _pin_for_alias(item: dict[str, Any], pins: list[dict[str, Any]]) -> dict[str, Any] | None:
    raw_meta = item.get("meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    raw_code = str(meta.get("code") or item.get("code") or "")
    alias_kind = str(meta.get("alias_kind") or item.get("alias_kind") or "code")
    code = raw_code.upper() if alias_kind == "code" else raw_code
    for pin in pins:
        aliases = pin.get("aliases") or []
        if not aliases:
            continue
        alias = aliases[0]
        if str(alias.get("alias_kind") or "") != alias_kind:
            continue
        value = str(alias.get("alias_value") or "")
        if alias_kind == "code" and value.upper() == code:
            return pin
        if alias_kind != "code" and value.casefold() == code.casefold():
            return pin
    return None


def _prefill_cart_item(item: dict[str, Any]) -> dict[str, Any]:
    prefill = dict(item.get("prefill") or {})
    code = str(prefill.get("code") or item.get("code") or "")
    league = str(prefill.get("league") or "")
    book = str(prefill.get("sportsbook") or "")
    alias_kind = str(prefill.get("alias_kind") or item.get("alias_kind") or "code")
    return {
        "kind": "entity_alias",
        "label": f"Pin {code} ({league})",
        "payload": {
            "kind": "entity_alias",
            "league": league,
            "canonical_key": code.upper() if alias_kind == "code" else code,
            "canonical_name": code,
            "entity_type": str(prefill.get("entity_type") or "team"),
            "aliases": [
                {
                    "sportsbook": book,
                    "alias_kind": alias_kind,
                    "alias_value": code.upper() if alias_kind == "code" else code,
                }
            ],
            "reassign": False,
            "evidence_refs": [],
        },
    }


def _match_type(store: Any | None, league: str) -> str:
    """Match-side entity_type for unmapped alias prefills."""
    if store is not None:
        return match_entity_type_for_league(store, league)
    return match_entity_type(league)
