"""Propose tools that append league / market / alias lines to the pending cart."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_cart import (
    append_cart_item,
    checklist_markdown,
    confirm_buttons,
    set_awaiting_ignores,
)
from mappers.control_plane.chat_catalog import SPORTSBOOKS, optic_id_for, sport_for_slug
from mappers.control_plane.chat_profiles import all_platform_exchanges, enabled_sportsbooks
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.gap_fix import _cart_item
from mappers.control_plane.gap_market_bind import live_optic_census
from mappers.control_plane.harvest_league_ids import harvest_exchange_batch
from mappers.control_plane.pin_flow_ignore_flip import ignore_flip_cart_items
from mappers.control_plane.pin_flow_markets import MarketRuleObservation, draft_and_verify_market_rules
from mappers.control_plane.rof_before_rule import mentions_rof_before, rof_before_ignore_observation
from mappers.control_plane.suggest_markets import _BOOK_COLUMNS, suggest_market_rules

_ALL_BOOKS = frozenset({"all", "*", "every"})


def _harvested_exchanges(
    store: Any,
    league: str,
    sport: str,
    optic: str,
    evidence: list[str] | None,
) -> list[dict[str, Any]]:
    """Enable requested books; fill source ids from harvest, never invent."""
    pins = all_platform_exchanges(optic_league_id=optic, evidence_books=evidence)
    books = evidence or [str(pin.get("sportsbook") or "") for pin in pins]
    probes = harvest_exchange_batch(
        store,
        league=league,
        sport=sport,
        optic_league_id=optic,
        sportsbooks=[b for b in books if b],
        skip_wired=True,
    )
    by_book = {str(row.get("book") or ""): row for row in probes}
    return [_apply_probe(pin, by_book.get(str(pin.get("sportsbook") or ""))) for pin in pins]


def _apply_probe(pin: dict[str, Any], probe: dict[str, Any] | None) -> dict[str, Any]:
    if not pin.get("enabled") or not probe or not probe.get("evidence"):
        return pin
    source = str(probe.get("source") or "").strip()
    settings = dict(probe.get("settings") or {})
    if not source and not settings:
        return pin
    out = dict(pin)
    if source:
        out["source_league_id"] = source
    if settings:
        merged = dict(pin.get("settings") or {})
        merged.update(settings)
        out["settings"] = merged
    return out


def propose_league(
    store: Any,
    bag: ChatSession,
    *,
    league: str,
    sportsbook: str,
    sport: str = "",
    optic_league_id: str = "",
) -> dict[str, Any]:
    """Stage a league onboard/enable for a named book, or all console books."""
    slug = league.strip()
    book = sportsbook.strip().lower()
    if not slug:
        return {"ok": False, "error": "league required"}
    if book and book not in _ALL_BOOKS and not _known_book(book):
        return {"ok": False, "error": "league and sportsbook required"}
    tip = _league_on_tip(store, slug)
    if book and book not in _ALL_BOOKS and tip is not None and _book_enabled(tip, book):
        return {
            "ok": True,
            "already_on": True,
            "message": f"**{slug}** already has **{book}** enabled.",
            "ui_actions": _rules("leagues", slug),
            "checklist": checklist_markdown(bag),
        }
    sport_out = sport or (tip.sport if tip else "") or sport_for_slug(slug, store)
    optic = optic_league_id or (tip.optic_league_id if tip else "") or optic_id_for(slug, store)
    evidence = None if (not book or book in _ALL_BOOKS) else [book, "optic"]
    exchanges = _harvested_exchanges(store, slug, sport_out, optic, evidence)
    item = _league_item(slug, sport_out, optic, exchanges, book)
    status = append_cart_item(bag, item)
    out: dict[str, Any] = {
        "ok": True,
        "staged": status,
        "checklist": checklist_markdown(bag),
        "reply_buttons": [{"id": b.id, "label": b.label, "send": b.send} for b in confirm_buttons()],
    }
    if status == "added":
        out["appended"] = item["label"]
    elif status == "merged":
        out["message"] = f"Merged **{book}** into the already-staged **{slug}** line."
    else:
        out["message"] = f"**{slug}** ({book}) is already staged — nothing new added."
    return out


def propose_markets(
    store: Any,
    bag: ChatSession,
    *,
    league: str,
    sportsbook: str,
    market: str = "",
    flip_ignores: bool = False,
) -> dict[str, Any]:
    """Stage market pins for one book; ask before flipping ignores."""
    slug = league.strip()
    book = sportsbook.strip().lower()
    if not slug or not book:
        return {"ok": False, "error": "league and sportsbook required"}
    tip = _league_on_tip(store, slug)
    tip_rules = _tip_market_rows(store, slug, book)
    live = live_optic_census(store, slug) if tip is not None else set()
    observations = _market_observations(store, tip, slug, book, market.strip().lower(), live)
    drafted, _skipped = draft_and_verify_market_rules(store, observations)
    suggestions = [_cart_item(pin) for pin in drafted]
    return _stage_markets(
        bag,
        store=store,
        slug=slug,
        book=book,
        market=market.strip().lower(),
        tip_rules=tip_rules,
        suggestions=suggestions,
        flip_ignores=flip_ignores,
        live=live,
    )


def offer_pin(
    bag: ChatSession,
    *,
    league: str,
    sportsbook: str,
    code: str,
    canonical_key: str = "",
    canonical_name: str = "",
    entity_type: str = "team",
) -> dict[str, Any]:
    """Stage one entity_alias cart line."""
    if not (league and sportsbook and code):
        return {"ok": False, "error": "league, sportsbook, and code required"}
    key = (canonical_key or code).strip()
    name = (canonical_name or key).strip()
    item = {
        "kind": "entity_alias",
        "label": f"{sportsbook} {code} → {league}/{key}",
        "payload": {
            "kind": "entity_alias",
            "league": league,
            "canonical_key": key,
            "entity_type": entity_type,
            "canonical_name": name,
            "aliases": [
                {
                    "sportsbook": sportsbook,
                    "alias_kind": "code",
                    "alias_value": code,
                }
            ],
            "reassign": False,
        },
    }
    append_cart_item(bag, item)
    return {
        "ok": True,
        "appended": item["label"],
        "checklist": checklist_markdown(bag),
        "reply_buttons": [{"id": b.id, "label": b.label, "send": b.send} for b in confirm_buttons()],
    }


def _stage_markets(
    bag: ChatSession,
    *,
    store: Any,
    slug: str,
    book: str,
    market: str,
    tip_rules: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    flip_ignores: bool,
    live: set[str],
) -> dict[str, Any]:
    mapped_keys = {str(r.get("source_key") or "").lower() for r in tip_rules if str(r.get("action") or "") != "ignore"}
    ignored = [r for r in tip_rules if str(r.get("action") or "") == "ignore"]
    pins = _missing_pins(suggestions, mapped_keys, market, slug)
    flip_items = ignore_flip_cart_items(store, slug, ignored, market, live)
    if flip_items and not flip_ignores:
        set_awaiting_ignores(bag, flip_items)
        for pin in pins:
            append_cart_item(bag, pin)
        return {
            "ok": True,
            "mapped_skipped": len(mapped_keys),
            "appended": [p["label"] for p in pins],
            "needs_ignore_confirm": [f["label"] for f in flip_items],
            "message": (
                f"{len(flip_items)} tip rule(s) are **ignored**. "
                "Reply **yes** to queue map flips, or ask for something else."
            ),
            "checklist": checklist_markdown(bag),
            "reply_buttons": [{"id": b.id, "label": b.label, "send": b.send} for b in confirm_buttons()],
        }
    for item in pins + (flip_items if flip_ignores else []):
        append_cart_item(bag, item)
    return {
        "ok": True,
        "mapped_skipped": len(mapped_keys),
        "appended": [p["label"] for p in pins + (flip_items if flip_ignores else [])],
        "checklist": checklist_markdown(bag),
        "reply_buttons": [{"id": b.id, "label": b.label, "send": b.send} for b in confirm_buttons()],
    }


def _market_observations(
    store: Any,
    tip: Any,
    slug: str,
    book: str,
    market: str,
    live: set[str],
) -> list[MarketRuleObservation]:
    """Spine keys as observations; kernel unique-binds against live Optic census."""
    rid = store.current_rule_set_id
    tip_leagues = store.leagues_for(rid) if rid else []
    result = suggest_market_rules(
        league=slug,
        optic_league_id=str(tip.optic_league_id if tip else ""),
        sport=str(tip.sport if tip else ""),
        sportsbooks=[book],
        tip_leagues=tip_leagues,
        store=store,
    )
    meta = _BOOK_COLUMNS.get(book)
    if meta is None:
        return []
    source_key_type, _column = meta
    out: list[MarketRuleObservation] = []
    if mentions_rof_before(slug, book, market):
        out.append(rof_before_ignore_observation())
    for sug in list(result.get("suggestions") or []):
        pin = dict(sug.get("pin") or {})
        source_key = str(pin.get("source_key") or "").strip()
        if not source_key:
            continue
        canonical = str(pin.get("canonical_market_type") or "")
        if market and market not in source_key.lower() and market not in canonical.lower():
            continue
        out.append(
            {
                "league": slug,
                "sportsbook": book,
                "source_key": source_key,
                "source_key_type": source_key_type,
                "demand": 0,
                "evidence_refs": [f"chat:propose_markets:{source_key}"],
                "live_optic_market_ids": live,
            },
        )
    return out


def _missing_pins(
    suggestions: list[dict[str, Any]],
    mapped_keys: set[str],
    market: str,
    league: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in suggestions:
        payload = dict(item.get("payload") or {})
        rules = list(payload.get("rules") or [])
        book_rule = next((r for r in rules if str(r.get("sportsbook") or "") != "optic"), None)
        if book_rule is None:
            continue
        key = str(book_rule.get("source_key") or "").lower()
        if not key or key in mapped_keys:
            continue
        canonical = str(book_rule.get("canonical_market_type") or "").lower()
        operator = str(book_rule.get("match_operator") or "")
        if market and not _text_hits_rule(key, canonical, market, operator):
            continue
        out.append(item)
    return out


def _text_hits_rule(key: str, canonical: str, market: str, operator: str) -> bool:
    """Exact/substring hit, or a prefix rule whose key starts the typed market."""
    if market in key or market in canonical:
        return True
    return operator == "prefix" and bool(key) and market.startswith(key)


def _league_item(league: str, sport: str, optic: str, exchanges: list, book: str) -> dict[str, Any]:
    payload = {
        "kind": "mapping_league",
        "league": league,
        "sport": sport,
        "optic_league_id": optic,
        "fixture_source": "api",
        "enabled": True,
        "exchanges": exchanges,
        "evidence_refs": [f"optic:id:{optic}"] if optic else [],
    }
    books = enabled_sportsbooks(exchanges)
    if not book or book in _ALL_BOOKS:
        label = f"League {league} ({len(books)} books)"
    else:
        label = f"League {league} ({book}+optic)"
    return {"kind": "mapping_league", "label": label, "payload": payload}


def _known_book(book: str) -> bool:
    return book in SPORTSBOOKS


def _league_on_tip(store: Any, league: str) -> Any:
    rid = store.current_rule_set_id
    if not rid:
        return None
    key = league.strip().lower()
    for row in store.leagues_for(rid):
        if row.league.lower() == key:
            return row
    return None


def _book_enabled(tip: Any, book: str) -> bool:
    return any(str(ex.get("sportsbook") or "").lower() == book and ex.get("enabled") for ex in tip.exchanges or [])


def _tip_market_rows(store: Any, league: str, book: str) -> list[dict[str, Any]]:
    rid = store.current_rule_set_id
    if not rid:
        return []
    out: list[dict[str, Any]] = []
    for mr in store.market_rules_for(rid):
        if mr.league.lower() != league.lower():
            continue
        if str(mr.sportsbook or "").lower() != book:
            continue
        out.append(
            {
                "league": mr.league,
                "sportsbook": mr.sportsbook,
                "source_key": mr.source_key,
                "source_key_type": mr.source_key_type,
                "action": mr.action,
                "canonical_market_type": mr.canonical_market_type,
            }
        )
    return out


def _rules(kind: str, q: str) -> list[dict[str, str]]:
    path = f"/rules?kind={kind}&q={q}" if q else f"/rules?kind={kind}"
    return [{"type": "navigate", "path": path}, {"type": "rules_filter", "kind": kind, "q": q}]
