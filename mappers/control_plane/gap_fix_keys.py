"""Canonical-key selection for Fix-gaps harvest pins."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mappers.alias_kinds import crypto_pin, is_crypto_id, is_optic_id, optic_pin
from mappers.canonical_codes import fallback_code, names_close, names_fit, person_league
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted, optic_draft_key
from mappers.control_plane.gap_fix_tip import (
    TipLeagueIndex,
    has_other_owners,
    key_for_code_from_index,
)
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK

_REMOVED_HOPS = 8
CryptoAssigned = set[tuple[str, str]]


def key_for_code(
    store: Any,
    league: str,
    oid: str,
    name: str,
    used: set[str],
    owners: list[str],
    *,
    optic_drafted: OpticDrafted | None = None,
    tip: TipLeagueIndex | None = None,
) -> tuple[str, bool]:
    """Reuse optic/name match, else invent. Collide if others still claim."""
    if tip is not None:
        return key_for_code_from_index(
            tip, league, oid, name, used, owners, optic_drafted=optic_drafted,
        )
    owner_set = {o.upper() for o in owners}
    if owner_has_optic(store, league, owners, oid):
        return "", False
    drafted = optic_draft_key(optic_drafted, league, oid)
    if drafted:
        return drafted, has_other_owners(owner_set, drafted)
    existing = optic_key(store, league, oid)
    if existing:
        return existing, has_other_owners(owner_set, existing)
    player = person_league(league)
    sole = _sole_unoptic_owner(store, league, owners, name, player=player)
    if sole:
        return sole, has_other_owners(owner_set, sole)
    hit = name_hit(store, league, name, player=player)
    if hit:
        return hit, has_other_owners(owner_set, hit)
    key = fallback_code(name, used, oid)
    return key, has_other_owners(owner_set, key)


def tip_has_key(store: Any, league: str, key: str) -> bool:
    """True when the activated tip already owns this canonical."""
    return _entity_exists(store, league, key)


def _entity_exists(store: Any, league: str, key: str) -> bool:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return False
    return any(
        ent.league == league and ent.canonical_key == key and not ent.tombstone
        for ent in store.entities_for(rid)
    )


def crypto_owned(
    store: Any,
    league: str,
    cid: str,
    assigned: CryptoAssigned | None = None,
) -> bool:
    """True when the tip or this harvest pass already pins this crypto.com id."""
    if not cid:
        return False
    if assigned and (league, cid) in assigned:
        return True
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return False
    for ent in store.entities_for(rid):
        if ent.league != league or ent.tombstone:
            continue
        for alias in ent.aliases or []:
            if is_crypto_id(alias, cid):
                return True
    return False


def entity_has_crypto(
    store: Any, league: str, key: str, cid: str | None = None,
) -> bool:
    """True when this canonical already carries a crypto.com id."""
    return _entity_has_alias(
        store,
        league,
        key,
        lambda a: is_crypto_id(a, cid) if cid else is_crypto_id(a),
    )


def canonical_for_missing_side(
    store: Any,
    league: str,
    oid: str,
    name: str,
    used: set[str],
    *,
    player: bool,
    optic_drafted: OpticDrafted | None = None,
) -> str:
    """Reuse a sole name match, else invent. Skip when the name is a clash."""
    drafted = optic_draft_key(optic_drafted, league, oid)
    if drafted:
        return drafted
    hit = name_hit(store, league, name, player=player)
    if hit:
        return hit if names_fit(
            name, entity_name_for(store, league, hit), player=player,
        ) else ""
    try:
        return fallback_code(name, used, oid)
    except ValueError:
        return ""


def crypto_aliases(
    cid: str,
    oid: str,
    *,
    include_optic: bool = True,
) -> list[dict[str, str]]:
    """Crypto.com id plus Optic competitor id when the canonical is new.

    Empty-abbr Optic sides join MatchKey via abbr_overrides[optic_id].
    A crypto_id-only pin mints a canonical the mapper cannot attach.
    """
    aliases: list[dict[str, str]] = []
    if include_optic:
        aliases.append(optic_pin(oid))
    aliases.append(crypto_pin(cid))
    return aliases


def name_hit(store: Any, league: str, name: str, *, player: bool) -> str:
    """Sole existing canonical whose name matches, else empty."""
    rid = store.current_rule_set_id
    if not rid:
        return ""
    hits = [
        e.canonical_key
        for e in store.entities_for(rid)
        if e.league == league
        and not e.tombstone
        and names_close(str(e.canonical_name or ""), name, player=player)
    ]
    return hits[0] if len(hits) == 1 else ""


def entity_name_for(store: Any, league: str, key: str) -> str:
    """Canonical display name for an existing tip entity, else the key."""
    rid = store.current_rule_set_id
    if not rid:
        return key
    want = key.upper()
    for ent in store.entities_for(rid):
        if ent.league == league and ent.canonical_key.upper() == want and not ent.tombstone:
            return str(ent.canonical_name or ent.canonical_key)
    return key


def entity_type_for(store: Any, league: str, key: str) -> str:
    """Reuse the tip entity_type when the canonical already exists."""
    rid = store.current_rule_set_id
    if not rid:
        return ""
    matches = [
        ent
        for ent in store.entities_for(rid)
        if ent.league == league and ent.canonical_key == key and not ent.tombstone
    ]
    if not matches:
        return ""
    if len(matches) == 1:
        return str(matches[0].entity_type or "")
    with_aliases = [ent for ent in matches if ent.aliases]
    if len(with_aliases) == 1:
        return str(with_aliases[0].entity_type or "")
    from mappers.control_plane.entity_types import match_entity_type_for_league

    want = match_entity_type_for_league(store, league)
    for ent in matches:
        if ent.entity_type == want:
            return want
    return str(matches[0].entity_type or "")


def entity_has_optic(store: Any, league: str, key: str, oid: str) -> bool:
    """True when this canonical already carries this Optic competitor id."""
    return _entity_has_alias(store, league, key, lambda a: is_optic_id(a, oid))


def entity_has_usa(store: Any, league: str, key: str, code: str) -> bool:
    """True when this canonical already has the polymarket_usa code."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return False
    wanted = code.casefold()
    for ent in store.entities_for(rid):
        if ent.league == league and ent.canonical_key == key and not ent.tombstone:
            return _has_usa_on(ent, wanted)
    return False


def usa_owners(store: Any, league: str, code: str) -> list[str]:
    """Canonical keys in this league that already carry the US code."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return []
    wanted = code.casefold()
    return [
        ent.canonical_key for ent in store.entities_for(rid)
        if ent.league == league and not ent.tombstone and _has_usa_on(ent, wanted)
    ]


def entity_has_pin(store: Any, league: str, key: str, alias: dict[str, Any]) -> bool:
    """True when this canonical already carries this harvest alias."""
    book, kind, value = _pin_parts(alias)
    if not value:
        return False
    if book == "optic":
        return entity_has_optic(store, league, key, value)
    if book == "crypto.com":
        return _entity_has_alias(store, league, key, lambda a: is_crypto_id(a, value))
    return _entity_has_alias(store, league, key, lambda a: _same_pin(a, book, kind, value))


def alias_was_removed(store: Any, league: str, key: str, alias: dict[str, Any]) -> bool:
    """True when an ancestor tip carried this alias on this canonical."""
    if entity_has_pin(store, league, key, alias):
        return False
    get_receipt = getattr(store, "get_receipt", None)
    rid = getattr(store, "current_rule_set_id", None)
    if get_receipt is None or not rid:
        return False
    return _alias_on_ancestor(store, get_receipt, str(rid), league, key, alias)


def _alias_on_ancestor(
    store: Any,
    get_receipt: Any,
    rid: str,
    league: str,
    key: str,
    alias: dict[str, Any],
) -> bool:
    """Walk parent receipts looking for the alias on this canonical."""
    seen: set[str] = set()
    cur = rid
    for _ in range(_REMOVED_HOPS):
        if cur in seen:
            return False
        seen.add(cur)
        receipt = get_receipt(cur)
        parent = getattr(receipt, "parent_rule_set_id", None) if receipt else None
        if not parent:
            return False
        if _entity_carries(store, str(parent), league, key, alias):
            return True
        cur = str(parent)
    return False


def _entity_carries(
    store: Any, rid: str, league: str, key: str, alias: dict[str, Any],
) -> bool:
    """True when this rule set's canonical has ``alias``."""
    for ent in store.entities_for(rid):
        if ent.league != league or ent.canonical_key != key or ent.tombstone:
            continue
        return any(_pin_matches(row, alias) for row in ent.aliases)
    return False


def _pin_matches(existing: dict[str, Any], alias: dict[str, Any]) -> bool:
    """True when ``existing`` is the same harvest pin as ``alias``."""
    book, kind, value = _pin_parts(alias)
    if book == "optic":
        return is_optic_id(existing, value)
    if book == "crypto.com":
        return is_crypto_id(existing, value)
    return _same_pin(existing, book, kind, value)


def _pin_parts(alias: dict[str, Any]) -> tuple[str, str, str]:
    """sportsbook, alias_kind, alias_value from a pin dict."""
    return (
        str(alias.get("sportsbook") or "").strip().lower(),
        str(alias.get("alias_kind") or "").strip().lower(),
        str(alias.get("alias_value") or "").strip(),
    )


def _same_pin(alias: dict[str, Any], book: str, kind: str, value: str) -> bool:
    """True when ``alias`` is the same book/kind/value (Poly names casefold)."""
    if str(alias.get("sportsbook") or "").lower() != book:
        return False
    if str(alias.get("alias_kind") or "").lower() != kind:
        return False
    got = str(alias.get("alias_value") or "").strip()
    if book == "polymarket" and kind == "name":
        return got.casefold() == value.casefold()
    return got == value


def owner_has_any_optic(store: Any, league: str, owners: list[str]) -> bool:
    """True when an existing owner already has some optic id."""
    return _owners_match(store, league, owners, lambda a: is_optic_id(a))


def owner_has_optic(store: Any, league: str, owners: list[str], oid: str) -> bool:
    """True when an existing owner already carries this Optic competitor id."""
    return _owners_match(store, league, owners, lambda a: is_optic_id(a, oid))


def optic_key(store: Any, league: str, oid: str) -> str:
    """Canonical that already owns this Optic id, else empty."""
    rid = store.current_rule_set_id
    if not rid:
        return ""
    for ent in store.entities_for(rid):
        if ent.league != league or ent.tombstone:
            continue
        if any(is_optic_id(alias, oid) for alias in ent.aliases):
            return ent.canonical_key
    return ""


def optic_owner(store: Any, league: str, oid: str) -> Any | None:
    """Sole tip entity that already owns this Optic competitor id."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return None
    hits = [
        ent for ent in store.entities_for(rid)
        if ent.league == league and not ent.tombstone
        and any(is_optic_id(alias, oid) for alias in ent.aliases)
    ]
    return hits[0] if len(hits) == 1 else None


def used_keys(store: Any, league: str) -> set[str]:
    """Canonical keys already on the tip for this league."""
    rid = store.current_rule_set_id
    if not rid:
        return set()
    return {
        e.canonical_key.upper()
        for e in store.entities_for(rid)
        if e.league == league and not e.tombstone
    }


def _sole_unoptic_owner(
    store: Any,
    league: str,
    owners: list[str],
    name: str,
    *,
    player: bool,
) -> str:
    """Sole owner with no optic id whose name matches, else empty."""
    if len(owners) != 1 or owner_has_any_optic(store, league, owners):
        return ""
    if not _owner_name_matches(store, league, owners, name, player=player):
        return ""
    return owners[0]


def _owner_name_matches(
    store: Any, league: str, owners: list[str], name: str, *, player: bool,
) -> bool:
    """True when a listed owner’s canonical name matches the Optic competitor."""
    rid = store.current_rule_set_id
    if not rid:
        return False
    wanted = {o.upper() for o in owners}
    for ent in store.entities_for(rid):
        if ent.league != league or ent.canonical_key.upper() not in wanted:
            continue
        if names_close(str(ent.canonical_name or ""), name, player=player):
            return True
    return False


def _entity_has_alias(
    store: Any,
    league: str,
    key: str,
    match: Callable[[dict[str, Any]], bool],
) -> bool:
    """True when this canonical has an alias matching ``match``."""
    rid = store.current_rule_set_id
    if not rid:
        return False
    for ent in store.entities_for(rid):
        if ent.league != league or ent.canonical_key != key or ent.tombstone:
            continue
        if any(match(alias) for alias in ent.aliases):
            return True
    return False


def _owners_match(
    store: Any,
    league: str,
    owners: list[str],
    match: Callable[[dict[str, Any]], bool],
) -> bool:
    """True when a listed owner has an alias matching ``match``."""
    rid = store.current_rule_set_id
    if not rid or not owners:
        return False
    wanted = {o.upper() for o in owners}
    for ent in store.entities_for(rid):
        if ent.league != league or ent.canonical_key.upper() not in wanted:
            continue
        if any(match(alias) for alias in ent.aliases):
            return True
    return False


def _has_usa_on(ent: Any, wanted: str) -> bool:
    """True when the entity row carries this polymarket_usa code."""
    for alias in ent.aliases:
        if str(alias.get("sportsbook") or "").lower() != POLY_USA_BOOK:
            continue
        if str(alias.get("alias_kind") or "") != "code":
            continue
        if str(alias.get("alias_value") or "").casefold() == wanted:
            return True
    return False
