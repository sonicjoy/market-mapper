"""Structured alias verify for Rules → Entry propose-change (no paste)."""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane import entry as entry_mod
from mappers.control_plane.alias_ok import signed_alias_ok
from mappers.control_plane.dry_run import thin_dry_run
from mappers.control_plane.entity_types import match_entity_type, match_entity_type_for_league
from mappers.control_plane.entry import ACK_RULES_WRITE, league_label
from mappers.control_plane.live_evidence import apply_evidence_fn
from mappers.control_plane.models import EntityAliasPayload
from mappers.control_plane.pin_flow import verify_remove_payload
from mappers.control_plane.store import EntityRow

_BOOK = {"crypto.com": "crypto.com", "optic": "Optic"}
_ABSENT: str | None = None  # nosec B105


def _ensure_labels(store: Any | None = None) -> None:
    """Load league display labels once (delegates to entry tip cache)."""
    entry_mod._register_league_labels(store)


def _fail(blockers: list[str], warnings: list[str], *, needs_name: bool = False) -> dict[str, Any]:
    """Blocked structured-verify response."""
    return {
        "ok": False,
        "blockers": blockers,
        "warnings": warnings,
        "preview": _ABSENT,
        "preview_token": _ABSENT,
        "needs_name": needs_name,
        "needs_live_ack": bool(warnings),
        "needs_league": False,
        "disambiguation_choices": [],
    }


def _resolve_key_and_name(
    *,
    league: str,
    entity_type: str,
    canonical_key: str | None,
    name: str,
    entities: list[EntityRow],
) -> tuple[str, str]:
    """Pick canonical_key for a structured pin; prefer name match then prior key."""
    league_ents = [e for e in entities if e.league == league and e.entity_type == entity_type]
    by_name = [
        e for e in league_ents if (e.canonical_name or e.canonical_key).casefold() == name.casefold()
    ]
    if by_name:
        ent = by_name[0]
        return ent.canonical_key, ent.canonical_name or ent.canonical_key
    key = (canonical_key or "").strip()
    if key:
        return key, name
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "ENTITY"
    return slug, name


def _ok_card(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    key: str,
    name: str,
    note: str | None,
    warnings: list[str],
    evidence_refs: list[str] | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Build signed preview for a valid structured pin."""
    book_label = _BOOK.get(sportsbook, sportsbook)
    ll = league_label(league)
    if remove:
        summary = f"Remove {book_label} {alias_kind} `{alias_value}` from **{name}** in **{ll}**"
        raw = f"structured:remove:{sportsbook}:{alias_kind}:{alias_value}"
    else:
        summary = f"Pin {book_label} {alias_kind} `{alias_value}` to **{name}** in **{ll}**"
        raw = f"structured:{sportsbook}:{alias_kind}:{alias_value}"
    return signed_alias_ok(
        sportsbook=sportsbook,
        league=league,
        league_label_text=ll,
        alias_kind=alias_kind,
        alias_value=alias_value,
        entity_type=entity_type,
        canonical_key=key,
        canonical_name=name,
        raw_paste=raw,
        note=note,
        summary=summary,
        warnings=warnings,
        reassign=not remove,
        remove=remove,
        evidence_refs=list(evidence_refs or []),
    )


def _collect_blockers(
    *,
    league: str,
    sportsbook: str,
    alias_value: str,
    name: str,
    acknowledge_shadow: bool,
) -> list[str]:
    """Field validation blockers for structured alias verify."""
    blockers: list[str] = []
    if not league.strip():
        blockers.append("League is required.")
    if not sportsbook.strip():
        blockers.append("Sportsbook is required.")
    if not alias_value.strip():
        blockers.append("Alias code is required.")
    if not acknowledge_shadow:
        blockers.append(ACK_RULES_WRITE)
    return blockers


def _preview_or_remove(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    key: str,
    name: str,
    note: str | None,
    warnings: list[str],
    entities: list[EntityRow],
) -> dict[str, Any]:
    """Block when this alias is not live on the target canonical."""
    payload = EntityAliasPayload.model_validate(
        {
            "league": league,
            "canonical_key": key,
            "entity_type": entity_type,
            "canonical_name": name,
            "aliases": [
                {
                    "sportsbook": sportsbook,
                    "alias_kind": alias_kind,
                    "alias_value": alias_value,
                    "remove": True,
                }
            ],
        }
    )
    dry = thin_dry_run(entities, payload)
    blockers = verify_remove_payload(entities, payload)
    if blockers:
        return _fail(blockers, warnings + list(dry.get("warnings") or []))
    return _ok_card(
        league=league,
        sportsbook=sportsbook,
        alias_kind=alias_kind,
        alias_value=alias_value,
        entity_type=entity_type,
        key=key,
        name=name,
        note=note,
        warnings=warnings,
        remove=True,
    )


def _preview_or_live_block(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    key: str,
    name: str,
    note: str | None,
    warnings: list[str],
    entities: list[EntityRow],
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Block when this pin already maps to the same canonical on the tip."""
    dry = thin_dry_run(
        entities,
        EntityAliasPayload.model_validate(
            {
                "league": league,
                "canonical_key": key,
                "entity_type": entity_type,
                "canonical_name": name,
                "aliases": [
                    {
                        "sportsbook": sportsbook,
                        "alias_kind": alias_kind,
                        "alias_value": alias_value,
                    }
                ],
            }
        ),
    )
    if dry.get("blockers"):
        return _fail(list(dry["blockers"]), warnings + list(dry.get("warnings") or []))
    return _ok_card(
        league=league,
        sportsbook=sportsbook,
        alias_kind=alias_kind,
        alias_value=alias_value,
        entity_type=entity_type,
        key=key,
        name=name,
        note=note,
        warnings=warnings,
        evidence_refs=evidence_refs,
    )


def _pin_entity_type(
    entities: list[EntityRow],
    store: Any,
    league: str,
    requested: str,
    canonical_key: str | None,
    name: str,
) -> str:
    """Reuse an existing entity's type; otherwise the league's match-side type."""
    want = (requested or "").strip().lower()
    keyed = (canonical_key or "").strip()
    name_l = name.casefold()
    league_ents = [e for e in entities if e.league == league]
    if want in ("team", "player", "fighter") and _type_claimed(
        league_ents, want, keyed, name_l,
    ):
        return want
    for ent in league_ents:
        if keyed and ent.canonical_key == keyed:
            return ent.entity_type
        shown = (ent.canonical_name or ent.canonical_key).casefold()
        if name_l and shown == name_l:
            return ent.entity_type
    if store is not None:
        return match_entity_type_for_league(store, league)
    return match_entity_type(league)


def _type_claimed(
    ents: list[EntityRow], want: str, keyed: str, name_l: str,
) -> bool:
    """True when an entity of ``want`` already owns this key or name."""
    typed = [e for e in ents if e.entity_type == want]
    if keyed and any(e.canonical_key == keyed for e in typed):
        return True
    return bool(name_l) and any(
        (e.canonical_name or e.canonical_key).casefold() == name_l for e in typed
    )


def verify_structured_alias(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    canonical_key: str | None,
    provided_name: str | None,
    note: str | None,
    acknowledge_shadow: bool,
    entities: list[EntityRow],
    store: Any = None,
    evidence_fn: Any = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Verify a Rules-driven pin (no paste) and return a signed preview."""
    _ensure_labels(store)
    name = (provided_name or "").strip()
    warnings = ["Approve/activate updates live classify from the BQ tip."]
    if not name:
        return _fail(["Who is this? Enter the team, player, or fighter name."], warnings, needs_name=True)
    blockers = _collect_blockers(
        league=league, sportsbook=sportsbook, alias_value=alias_value,
        name=name, acknowledge_shadow=acknowledge_shadow,
    )
    if blockers:
        return _fail(blockers, warnings)
    entity_type = _pin_entity_type(
        entities, store, league, entity_type, canonical_key, name,
    )
    key, name = _resolve_key_and_name(
        league=league, entity_type=entity_type, canonical_key=canonical_key,
        name=name, entities=entities,
    )
    if remove:
        return _preview_or_remove(
            league=league, sportsbook=sportsbook, alias_kind=alias_kind,
            alias_value=alias_value, entity_type=entity_type, key=key, name=name,
            note=note, warnings=warnings, entities=entities,
        )
    return _structured_add(
        league=league, sportsbook=sportsbook, alias_kind=alias_kind,
        alias_value=alias_value, entity_type=entity_type, key=key, name=name,
        note=note, warnings=warnings, entities=entities, store=store,
        evidence_fn=evidence_fn,
    )


def _structured_add(
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    entity_type: str,
    key: str,
    name: str,
    note: str | None,
    warnings: list[str],
    entities: list[EntityRow],
    store: Any,
    evidence_fn: Any,
) -> dict[str, Any]:
    """Live-name gate then preview for an add pin."""
    refs, live_block = apply_evidence_fn(
        evidence_fn, store, league=league, sportsbook=sportsbook,
        alias_kind=alias_kind, alias_value=alias_value, canonical_name=name,
        raw_paste=f"structured:{sportsbook}:{alias_kind}:{alias_value}",
    )
    if live_block:
        return _fail(live_block, warnings)
    return _preview_or_live_block(
        league=league, sportsbook=sportsbook, alias_kind=alias_kind,
        alias_value=alias_value, entity_type=entity_type, key=key, name=name,
        note=note, warnings=warnings, entities=entities, evidence_refs=refs,
    )
