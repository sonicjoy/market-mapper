"""One alias draft+verify path for Chat, gap-propose, Unmapped Why, and Cart."""

from __future__ import annotations

from typing import Any, Literal

from mappers.control_plane.dry_run import resolve_alias, thin_dry_run
from mappers.control_plane.gap_fix_ai_suggest import is_ai_suggest_pin
from mappers.control_plane.gap_fix_draft import collect_crypto_probe_pins
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted
from mappers.control_plane.gap_fix_tip import index_tip_leagues
from mappers.control_plane.live_evidence import collect_pins_evidence
from mappers.control_plane.models import EntityAliasPayload
from mappers.control_plane.pin_flow_markets import is_market_pin, verify_market_pins
from mappers.control_plane.store import EntityRow


def draft_pins(
    store: Any, rows: list[dict[str, Any]], book: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Walk probe rows and draft unique alias pins (no live-name gate yet)."""
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if book != "crypto.com":
        # Only crypto.com probe rows draft alias pins; Kalshi takes none.
        skipped.extend({"reason": "unsupported_book", "book": book} for _ in rows)
        return pins, skipped
    seen: set[tuple[str, str, str]] = set()
    optic_drafted: OpticDrafted = {}
    tips = index_tip_leagues(store)
    used_by_league: dict[str, set[str]] = {}
    for row in rows:
        collect_crypto_probe_pins(
            store, row, pins, skipped, seen, optic_drafted,
            tips=tips, used_by_league=used_by_league,
        )
    return pins, skipped


def is_league_pin(pin: dict[str, Any]) -> bool:
    """True when this harvest pin is a mapping_league payload."""
    return str(pin.get("kind") or "") == "mapping_league"


def alias_from_pin(pin: dict[str, Any]) -> EntityAliasPayload:
    """Strip harvest-only fields into an alias payload."""
    raw = str(pin.get("entity_type") or "team")
    entity_type: Literal["team", "player", "fighter"]
    if raw == "player":
        entity_type = "player"
    elif raw == "fighter":
        entity_type = "fighter"
    else:
        entity_type = "team"
    return EntityAliasPayload(
        league=str(pin.get("league") or ""),
        canonical_key=str(pin.get("canonical_key") or ""),
        entity_type=entity_type,
        canonical_name=str(pin.get("canonical_name") or pin.get("canonical_key") or ""),
        aliases=list(pin.get("aliases") or []),
        reassign=bool(pin.get("reassign")),
        evidence_refs=[str(r) for r in (pin.get("evidence_refs") or []) if r],
    )


def verify_pins(
    store: Any,
    pins: list[dict[str, Any]],
    *,
    probe: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep pins that pass the same live evidence Cart Verify uses."""
    market_pins = [pin for pin in pins if is_market_pin(pin)]
    alias_pins = [pin for pin in pins if not is_market_pin(pin)]
    kept_market, skipped_market = verify_market_pins(store, market_pins)
    kept_alias, skipped_alias = _verify_alias_pins(store, alias_pins, probe)
    return kept_market + kept_alias, skipped_market + skipped_alias


def _verify_alias_pins(
    store: Any,
    pins: list[dict[str, Any]],
    probe: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Alias + league pins only."""
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []
    entities = _entities(store)
    for pin in pins:
        trimmed = _drop_live_aliases(pin, entities)
        if trimmed is None:
            continue
        extra = _verify_one(store, trimmed, probe, entities)
        if extra is None:
            continue
        if extra:
            skipped.extend(extra)
            continue
        kept.append(trimmed)
    return _drop_unpaired_removes(kept), skipped


def _drop_unpaired_removes(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a correction delete when its reassign claim did not survive verify."""
    claimed = {_alias_key(pin) for pin in kept if pin.get("reassign")}
    out: list[dict[str, Any]] = []
    for pin in kept:
        need = str(pin.get("requires_claim") or "")
        if need and (str(pin.get("league") or ""), need) not in claimed:
            continue
        out.append(pin)
    return out


def _alias_key(pin: dict[str, Any]) -> tuple[str, str]:
    """League plus the first alias value on a pin."""
    aliases = pin.get("aliases") or []
    value = str(aliases[0].get("alias_value") or "") if aliases else ""
    return str(pin.get("league") or ""), value


def _drop_live_aliases(
    pin: dict[str, Any], entities: list[EntityRow],
) -> dict[str, Any] | None:
    """Drop triples already on this canonical. None when nothing remains."""
    if is_league_pin(pin) or is_market_pin(pin) or is_remove_pin(pin):
        return pin
    aliases = list(pin.get("aliases") or [])
    if not aliases:
        return None
    league = str(pin.get("league") or "")
    key = str(pin.get("canonical_key") or "")
    kept: list[Any] = []
    for alias in aliases:
        if alias.get("remove"):
            kept.append(alias)
            continue
        hits = resolve_alias(
            entities,
            league=league,
            sportsbook=str(alias.get("sportsbook") or ""),
            alias_kind=str(alias.get("alias_kind") or ""),
            alias_value=str(alias.get("alias_value") or ""),
        )
        if key in hits:
            continue
        kept.append(alias)
    if not kept:
        return None
    return {**pin, "aliases": kept}


def _verify_one(
    store: Any, pin: dict[str, Any], probe: Any, entities: list[EntityRow],
) -> list[str] | None:
    """None drops silently; empty keeps; otherwise blockers."""
    if is_league_pin(pin):
        return [] if pin.get("exchanges") else None
    if not pin.get("aliases"):
        return None
    if is_remove_pin(pin):
        return verify_remove_payload(entities, alias_from_pin(pin))
    if is_ai_suggest_pin(pin) or probe is None:
        return []
    _refs, blockers = collect_pins_evidence(
        store, [alias_from_pin(pin)], probe=probe,
    )
    return blockers


def is_remove_pin(pin: dict[str, Any]) -> bool:
    """True when every alias on this pin is a deletion."""
    aliases = pin.get("aliases") or []
    return bool(aliases) and all(bool(a.get("remove")) for a in aliases)


def verify_remove_payload(
    entities: list[EntityRow], payload: EntityAliasPayload,
) -> list[str]:
    """Same gate Editor/Cart use: live on target, dry-run ok. No live-name probe."""
    for pin in payload.aliases:
        if not pin.remove:
            continue
        hits = resolve_alias(
            entities,
            league=payload.league,
            sportsbook=pin.sportsbook,
            alias_kind=pin.alias_kind,
            alias_value=pin.alias_value,
        )
        if payload.canonical_key not in hits:
            who = payload.canonical_name or payload.canonical_key
            return [f"This alias is not on {who} on the live tip."]
    dry = thin_dry_run(entities, payload)
    return [str(b) for b in (dry.get("blockers") or [])]


def draft_and_verify_remove(
    store: Any, pin: dict[str, Any],
) -> dict[str, Any]:
    """Verify one delete pin; never auto-Approve."""
    kept, blockers = verify_pins(store, [pin], probe=None)
    error = blockers[0] if blockers else ("" if kept else "no actionable pin")
    return {
        "ok": bool(kept),
        "pins": kept,
        "skipped": [],
        "blockers": blockers,
        "error": error,
    }


def _entities(store: Any) -> list[EntityRow]:
    """Activated tip entities, or empty when the store has no tip."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return []
    return list(store.entities_for(rid))


def draft_and_verify(
    store: Any,
    rows: list[dict[str, Any]],
    book: str,
    *,
    probe: Any = None,
) -> dict[str, Any]:
    """Draft from probe rows, then drop pins Cart Verify would block."""
    pins, skipped = draft_pins(store, rows, book)
    kept, blockers = verify_pins(store, pins, probe=probe)
    error = ""
    if not kept:
        error = _stage_error(blockers, skipped)
    return {
        "ok": bool(kept),
        "pins": kept,
        "skipped": skipped,
        "blockers": blockers,
        "error": error,
    }


def _stage_error(blockers: list[str], skipped: list[dict[str, str]]) -> str:
    """First live-name blocker, else first harvest skip, else empty."""
    if blockers:
        return blockers[0]
    if skipped:
        return str(skipped[0].get("reason") or "")
    return "no actionable pin"
