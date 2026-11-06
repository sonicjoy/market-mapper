"""Skill-specific chat tools: parser gate, exchange probe, stage_pin."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.chat_cart import append_cart_item, cart_items
from mappers.control_plane.chat_catalog import optic_id_for, sport_for_slug
from mappers.control_plane.chat_console import read_console_snapshot
from mappers.control_plane.chat_profiles import CHAT_SPORTSBOOKS, parser_profile
from mappers.control_plane.chat_tools_propose import offer_pin
from mappers.control_plane.dry_run_league import _known_profile
from mappers.control_plane.harvest_league_ids import harvest_exchange_source_id
from mappers.control_plane.harvest_league_ids_common import wired_probe_row
from mappers.control_plane.league_review import probe_evidence_refs
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.pin_flow import (
    draft_and_verify,
    draft_and_verify_remove,
    verify_pins,
)

_PROBE_BOOKS = tuple(CHAT_SPORTSBOOKS)


def check_parser_profiles(store: Any, league: str, sportsbooks: list[str] | None) -> dict[str, Any]:
    """needs_code gate: which books have a registered parser profile."""
    slug = league.strip()
    books = [b.strip().lower() for b in (sportsbooks or list(_PROBE_BOOKS)) if b.strip()]
    missing: list[str] = []
    ok: list[str] = []
    for book in books:
        profile = parser_profile(book)
        if _known_profile(slug, book, profile):
            ok.append(book)
        else:
            missing.append(book)
    needs = bool(missing)
    return {
        "ok": not needs,
        "needs_code": needs,
        "league": slug,
        "ready_books": ok,
        "missing_books": missing,
        "message": (
            f"needs_code: build parser profile for {missing} before onboard."
            if needs
            else "All requested books have known parser profiles."
        ),
    }


def probe_exchange_league(
    store: Any,
    league: str,
    sportsbook: str,
    *,
    optic_league_id: str = "",
    sport: str = "",
) -> dict[str, Any]:
    """One live-evidence probe for a single book."""
    slug = league.strip()
    book = sportsbook.strip().lower()
    optic = (optic_league_id or optic_id_for(slug, store)).strip()
    sport_out = (sport or sport_for_slug(slug, store)).strip()
    tip_row = _tip_row(store, slug)
    if tip_row is not None:
        wired = wired_probe_row(tip_row, book)
        if wired is not None:
            return wired
    return harvest_exchange_source_id(
        store,
        league=slug,
        sport=sport_out,
        optic_league_id=optic,
        sportsbook=book,
    )


def probe_all_books_parallel(
    store: Any,
    league: str,
    *,
    optic_league_id: str = "",
    sport: str = "",
    deadline_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Probe every console book in parallel; books past the deadline stay unevidenced."""
    slug = league.strip()
    optic = (optic_league_id or optic_id_for(slug, store)).strip()
    sport_out = (sport or sport_for_slug(slug, store)).strip()
    tip_row = _tip_row(store, slug)
    rows: list[dict[str, Any]] = []
    pending: list[str] = []
    for book in _PROBE_BOOKS:
        if tip_row is not None:
            wired = wired_probe_row(tip_row, book)
            if wired is not None:
                rows.append(wired)
                continue
        pending.append(book)
    if not pending:
        return rows
    with ThreadPoolExecutor(max_workers=len(pending)) as pool:
        futures = {
            pool.submit(
                harvest_exchange_source_id,
                store,
                league=slug,
                sport=sport_out,
                optic_league_id=optic,
                sportsbook=book,
            ): book
            for book in pending
        }
        rows.extend(_drain(futures, deadline_sec))
    return rows


def _drain(futures: dict[Any, str], deadline_sec: float | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    done: set[str] = set()
    try:
        for fut in as_completed(futures, timeout=deadline_sec):
            book = futures[fut]
            done.add(book)
            try:
                rows.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                rows.append({"ok": False, "book": book, "evidence": False, "error": str(exc)[:160]})
    except TimeoutError:
        pass
    for fut, book in futures.items():
        if book in done:
            continue
        fut.cancel()
        rows.append(
            {"ok": False, "book": book, "evidence": False, "note": "probe deadline exceeded"}
        )
    return rows


def stage_pin(
    ctx: Any,
    *,
    league: str,
    sportsbook: str,
    code: str,
    canonical_key: str = "",
    canonical_name: str = "",
    entity_type: str = "team",
    alias_kind: str = "code",
    evidence_refs: list[str] | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Stage entity_alias with evidence_refs on the pending cart."""
    if remove:
        return _stage_remove(
            ctx,
            league=league,
            sportsbook=sportsbook,
            code=code,
            canonical_key=canonical_key,
            canonical_name=canonical_name,
            entity_type=entity_type,
            alias_kind=alias_kind,
            evidence_refs=evidence_refs,
        )
    return _stage_add(
        ctx,
        league=league,
        sportsbook=sportsbook,
        code=code,
        canonical_key=canonical_key,
        canonical_name=canonical_name,
        entity_type=entity_type,
        alias_kind=alias_kind,
        evidence_refs=evidence_refs,
    )


def _stage_add(
    ctx: Any,
    *,
    league: str,
    sportsbook: str,
    code: str,
    canonical_key: str,
    canonical_name: str,
    entity_type: str,
    alias_kind: str,
    evidence_refs: list[str] | None,
) -> dict[str, Any]:
    """Stage an add pin onto the pending cart."""
    bag = ctx.bag
    if bag is None:
        return {"ok": False, "error": "session bag required"}
    key = canonical_key.strip() or code.strip().upper()
    name = canonical_name.strip() or key
    out = offer_pin(
        bag,
        league=league.strip(),
        sportsbook=sportsbook.strip().lower(),
        code=code.strip(),
        canonical_key=key,
        canonical_name=name,
        entity_type=entity_type.strip() or "team",
    )
    staged = cart_items(bag)
    if evidence_refs and staged:
        for item in staged:
            payload = item.get("payload") or {}
            if payload.get("kind") == "entity_alias":
                payload["evidence_refs"] = list(evidence_refs)
                payload.setdefault("aliases", [])
                if payload["aliases"]:
                    payload["aliases"][0]["alias_kind"] = alias_kind
    return out


def _stage_remove(
    ctx: Any,
    *,
    league: str,
    sportsbook: str,
    code: str,
    canonical_key: str,
    canonical_name: str,
    entity_type: str,
    alias_kind: str,
    evidence_refs: list[str] | None,
) -> dict[str, Any]:
    """Verify then cart one live alias delete (same gate as Editor)."""
    bag = ctx.bag
    if bag is None:
        return {"ok": False, "error": "session bag required"}
    key = canonical_key.strip()
    if not key:
        return {"ok": False, "error": "canonical_key required to remove"}
    pin = alias_payload(
        league.strip(),
        key,
        canonical_name.strip() or key,
        entity_type.strip() or "team",
        [
            {
                "sportsbook": sportsbook.strip().lower(),
                "alias_kind": alias_kind.strip() or "code",
                "alias_value": code.strip(),
                "remove": True,
            }
        ],
        list(evidence_refs or []),
    )
    staged = draft_and_verify_remove(ctx.store, pin)
    pins = list(staged.get("pins") or [])
    if not pins:
        return {
            "ok": False,
            "blockers": staged.get("blockers") or [],
            "error": staged.get("error") or "no actionable pin",
        }
    item = _cart_pin(pins[0])
    append_cart_item(bag, item)
    return {"ok": True, "pin": pins[0], "pins": pins, "payload": item["payload"]}


def stage_pin_from_probe(ctx: Any, row: dict[str, Any], *, book: str) -> dict[str, Any]:
    """Draft evidence-backed pins from one crypto gap probe row."""
    return stage_pins_from_rows(ctx, [row], book=book)


def stage_alias_pins(ctx: Any, pins: list[dict[str, Any]]) -> dict[str, Any]:
    """Cart pins that already passed harvest-shaped draft + Cart Verify."""
    kept, blockers = verify_pins(
        ctx.store, pins, probe=getattr(ctx, "evidence_fn", None),
    )
    if not kept:
        return {
            "ok": False,
            "blockers": blockers,
            "error": blockers[0] if blockers else "no actionable pin",
        }
    bag = ctx.bag
    if bag is None:
        return {"ok": False, "error": "session bag required"}
    payloads = [_cart_pin(pin) for pin in kept]
    for item in payloads:
        append_cart_item(bag, item)
    return {
        "ok": True,
        "pin": kept[0],
        "pins": kept,
        "payload": payloads[0]["payload"],
    }


def stage_pins_from_rows(
    ctx: Any, rows: list[dict[str, Any]], *, book: str,
) -> dict[str, Any]:
    """Draft pins that pass Cart Verify onto the pending cart."""
    staged = draft_and_verify(
        ctx.store, rows, book, probe=getattr(ctx, "evidence_fn", None),
    )
    pins = list(staged.get("pins") or [])
    if not pins:
        return {
            "ok": False,
            "skipped": staged.get("skipped") or [],
            "blockers": staged.get("blockers") or [],
            "error": staged.get("error") or "no actionable pin",
        }
    bag = ctx.bag
    if bag is None:
        return {"ok": False, "error": "session bag required"}
    payloads = [_cart_pin(pin) for pin in pins]
    for item in payloads:
        append_cart_item(bag, item)
    return {
        "ok": True,
        "pin": pins[0],
        "pins": pins,
        "payload": payloads[0]["payload"],
    }


def _cart_pin(pin: dict[str, Any]) -> dict[str, Any]:
    """Pending-cart line from a drafted alias payload."""
    payload = alias_payload(
        pin["league"],
        pin["canonical_key"],
        pin["canonical_name"],
        pin["entity_type"],
        pin["aliases"],
        list(pin.get("evidence_refs") or []),
    )
    first = pin["aliases"][0]
    code = first["alias_value"]
    key = pin["canonical_key"]
    label = (
        f"Remove {code} from {key}"
        if first.get("remove")
        else f"Pin {code} → {key}"
    )
    return {
        "kind": "entity_alias",
        "label": label,
        "payload": payload,
    }


def read_console_tool(page: Any) -> dict[str, Any]:
    """Return page snapshot for skills."""
    return read_console_snapshot(page)


def _tip_row(store: Any, league: str) -> Any | None:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return None
    for row in store.leagues_for(rid):
        if str(row.league) == league:
            return row
    return None


def _probe_settings(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    settings = dict(row.get("settings") or {})
    book = str(row.get("book") or "").strip().lower()
    source = str(row.get("source") or "").strip()
    if book in {"polymarket", "polymarket_usa"} and not settings.get("slug_prefix"):
        slug = str(row.get("slug_prefix") or source).strip()
        if slug:
            settings["slug_prefix"] = slug
    if book == "novig" and not settings.get("league"):
        code = str(row.get("league") or source).strip()
        if code:
            settings["league"] = code
    if book in {"underdog", "dkex"} and not settings.get("league"):
        code = str(row.get("league") or source).strip().upper()
        if code:
            settings["league"] = code
    if book == "crypto.com" and not settings.get("league") and source:
        settings["league"] = source
    if book == "px" and settings.get("tournament_id") is None:
        tid = row.get("tournament_id")
        if tid is None and source:
            try:
                tid = int(source)
            except ValueError:
                tid = None
        if tid is not None:
            settings["tournament_id"] = tid
    return settings


def _probe_source(row: dict[str, Any] | None, book: str, optic_id: str) -> str | None:
    if row is None:
        return None
    source = str(row.get("source") or row.get("prefix") or "").strip()
    if source:
        return source
    if book == "optic":
        return optic_id.strip() or None
    return None


def league_payload_from_evidence(
    store: Any,
    league: str,
    sport: str,
    optic_id: str,
    probes: list[dict[str, Any]],
) -> MappingLeaguePayload:
    """Build mapping_league payload with only evidenced books enabled."""
    exchanges: list[ExchangePin] = []
    for book in _PROBE_BOOKS:
        row = next((p for p in probes if p.get("book") == book), None)
        has = bool(row and row.get("evidence"))
        source = _probe_source(row, book, optic_id) if has else None
        settings = _probe_settings(row) if has and row else {}
        exchanges.append(
            ExchangePin(
                sportsbook=book,
                enabled=has,
                parser_profile=parser_profile(book),
                source_league_id=source,
                settings=settings,
            )
        )
    optic = optic_id.strip() or optic_id_for(league, store)
    return MappingLeaguePayload(
        league=league.strip(),
        sport=sport.strip() or sport_for_slug(league, store),
        optic_league_id=optic,
        exchanges=exchanges,
        evidence_refs=probe_evidence_refs(probes, optic),
    )
