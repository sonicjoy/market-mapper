"""One-pass tip index so harvest/probe/verify stay O(1) per side.

Split out of gap_fix_keys so the store walk and the hash maps each stay
under the file size gate. Leaf of that module: it never imports keys.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from mappers.alias_kinds import alias_value, is_crypto_id, is_optic_id
from mappers.canonical_codes import fallback_code, names_close, names_fit, person_league
from mappers.control_plane.gap_fix_optic_merge import OpticDrafted, optic_draft_key
from mappers.px_name_bind import orientation_pair_ok, side_fits_player
from mappers.seed.poly_usa_exchange import POLY_BOOK, POLY_USA_BOOK


@dataclass
class TipLeagueIndex:
    """Per-league tip maps so harvest is O(1) after one entities_for pass."""

    optic: dict[str, str] = field(default_factory=dict)
    optic_on: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    optic_clash: set[str] = field(default_factory=set)
    has_optic: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    used: set[str] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)
    crypto: set[str] = field(default_factory=set)
    crypto_owner: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    px: dict[str, str] = field(default_factory=dict)
    usa_on: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    usa_owner: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    poly_on: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def index_tip_leagues(
    store: Any, leagues: set[str] | None = None,
) -> dict[str, TipLeagueIndex]:
    """One COW coalesce, split by league. Never call entities_for per side."""
    rid = getattr(store, "current_rule_set_id", None)
    out: dict[str, TipLeagueIndex] = (
        {league: TipLeagueIndex() for league in leagues} if leagues is not None else {}
    )
    if leagues is not None and not leagues:
        return out
    if not rid or not hasattr(store, "entities_for"):
        return out
    return index_entity_rows(store.entities_for(rid), leagues)


def index_entity_rows(
    entities: Any, leagues: set[str] | None = None,
) -> dict[str, TipLeagueIndex]:
    """Build the harvest index from an already-coalesced entity list."""
    out: dict[str, TipLeagueIndex] = (
        {league: TipLeagueIndex() for league in leagues} if leagues is not None else {}
    )
    if leagues is not None and not leagues:
        return out
    for ent in entities:
        if ent.tombstone:
            continue
        league = str(ent.league or "")
        if leagues is not None and league not in out:
            continue
        _index_entity(out.setdefault(league, TipLeagueIndex()), ent)
    return out


def _index_entity(tip: TipLeagueIndex, ent: Any) -> None:
    """Record one tip entity onto optic/crypto/px maps."""
    key = str(ent.canonical_key or "")
    if not key:
        return
    tip.keys.add(key)
    tip.used.add(key.upper())
    tip.names[key] = str(ent.canonical_name or key)
    if ent.entity_type:
        tip.types[key] = str(ent.entity_type)
    for alias in ent.aliases or []:
        _index_alias(tip, key, alias)


def _index_alias(tip: TipLeagueIndex, key: str, alias: dict[str, Any]) -> None:
    """Record one tip alias onto the league index."""
    if is_optic_id(alias):
        oid = alias_value(alias)
        prior = tip.optic.get(oid)
        if prior and prior != key:
            tip.optic_clash.add(oid)
        tip.optic[oid] = key
        tip.optic_on[key].add(oid)
        tip.has_optic.add(key.upper())
        return
    if is_crypto_id(alias):
        cid = alias_value(alias)
        tip.crypto.add(cid)
        tip.crypto_owner[cid].add(key)
        return
    book = str(alias.get("sportsbook") or "").strip().lower()
    value = str(alias.get("alias_value") or "").strip()
    if not value:
        return
    if book == POLY_USA_BOOK and str(alias.get("alias_kind") or "") == "code":
        fold = value.casefold()
        tip.usa_on[key].add(fold)
        tip.usa_owner[fold].add(key)
        return
    if book == POLY_BOOK and str(alias.get("alias_kind") or "") == "name":
        tip.poly_on[key].add(value.casefold())
        return
    if book == "px":
        tip.px[value.upper()] = key


def name_hit_indexed(tip: TipLeagueIndex, name: str, *, player: bool) -> str:
    """Sole indexed canonical whose name matches, else empty."""
    hits = [
        key for key, shown in tip.names.items()
        if names_close(str(shown or ""), name, player=player)
    ]
    return hits[0] if len(hits) == 1 else ""


def canonical_from_index(
    tip: TipLeagueIndex,
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
    hit = name_hit_indexed(tip, name, player=player)
    if hit:
        shown = tip.names.get(hit, hit)
        return hit if names_fit(name, shown, player=player) else ""
    try:
        return fallback_code(name, used, oid)
    except ValueError:
        return ""


def league_tip(
    store: Any,
    league: str,
    tips: dict[str, TipLeagueIndex] | None,
) -> TipLeagueIndex:
    """Reuse a harvest-wide index, or build one league map (tests / Chat)."""
    if tips is not None:
        return tips.get(league, TipLeagueIndex())
    return index_tip_leagues(store, {league}).get(league, TipLeagueIndex())


def indexed_name(tip: TipLeagueIndex, key: str) -> str:
    """Canonical display name from the index, else the key."""
    if key in tip.names:
        return tip.names[key]
    want = key.upper()
    for cand, shown in tip.names.items():
        if cand.upper() == want:
            return shown
    return key


def indexed_optic_key(tip: TipLeagueIndex, oid: str) -> str:
    """Canonical that owns this Optic id, or empty on a clash."""
    if not oid or oid in tip.optic_clash:
        return ""
    return tip.optic.get(oid, "")


def indexed_has_optic(tip: TipLeagueIndex, key: str, oid: str) -> bool:
    """True when this canonical already carries this Optic competitor id."""
    return bool(oid) and oid in tip.optic_on.get(key, set())


def indexed_has_usa(tip: TipLeagueIndex, key: str, code: str) -> bool:
    """True when this canonical already has the polymarket_usa code."""
    return code.casefold() in tip.usa_on.get(key, set())


def indexed_usa_owners(tip: TipLeagueIndex, code: str) -> list[str]:
    """Canonical keys that already carry this US code."""
    return list(tip.usa_owner.get(code.casefold(), set()))


def indexed_owner_has_optic(tip: TipLeagueIndex, owners: list[str], oid: str) -> bool:
    """True when a listed owner already carries this Optic competitor id."""
    key = indexed_optic_key(tip, oid)
    if not key:
        return False
    wanted = {o.upper() for o in owners}
    return key.upper() in wanted


def indexed_owner_has_any_optic(tip: TipLeagueIndex, owners: list[str]) -> bool:
    """True when a listed owner already has some Optic id."""
    if not owners:
        return False
    wanted = {o.upper() for o in owners}
    return any(owner in tip.has_optic for owner in wanted)


def indexed_crypto_owners(tip: TipLeagueIndex, cid: str) -> list[str]:
    """Canonical keys that already carry this crypto.com id."""
    return list(tip.crypto_owner.get(cid, ()))


def indexed_has_poly_name(tip: TipLeagueIndex, key: str, name: str) -> bool:
    """True when this canonical already has the polymarket/name alias."""
    return name.casefold() in tip.poly_on.get(key, set())


def fold_harvest(harvest: dict[str, str]) -> dict[str, str]:
    """casefold feed name → crypto_id for O(1) exact harvest_cid hits."""
    return {
        name.casefold(): str(cid).strip()
        for name, cid in harvest.items()
        if str(name).strip() and str(cid).strip()
    }


def harvest_cid(
    harvest: dict[str, str],
    name: str,
    *,
    player: bool,
    folded: dict[str, str] | None = None,
    optic_counterpart: str | None = None,
) -> str:
    """Catalogue participant id for a FIX feed name, or empty."""
    text = name.strip()
    if not text or not harvest:
        return ""
    index = folded if folded is not None else fold_harvest(harvest)
    exact = index.get(text.casefold())
    if exact:
        return exact
    other = str(optic_counterpart or "").strip()
    if player and other:
        hit = _harvest_cid_fixture_pair(harvest, text, other)
        if hit:
            return hit
    hits = [
        str(cid).strip()
        for feed_name, cid in harvest.items()
        if names_fit(text, feed_name, player=player)
    ]
    if len(hits) == 1:
        return hits[0]
    return ""


def _harvest_cid_fixture_pair(
    harvest: dict[str, str], optic_a: str, optic_b: str,
) -> str:
    """Unique crypto id for optic_a when the pair binds to catalogue feeds."""
    cids: list[str] = []
    for feed_a, cid_a in harvest.items():
        for feed_b, cid_b in harvest.items():
            if str(cid_a).strip() == str(cid_b).strip():
                continue
            if not orientation_pair_ok(feed_a, feed_b, optic_a, optic_b, player=True):
                continue
            if side_fits_player(feed_a, optic_a, feed_b, optic_b):
                cids.append(str(cid_a).strip())
            elif side_fits_player(feed_b, optic_a, feed_a, optic_b):
                cids.append(str(cid_b).strip())
    uniq = list(dict.fromkeys(c for c in cids if c))
    return uniq[0] if len(uniq) == 1 else ""


def key_for_code_from_index(
    tip: TipLeagueIndex,
    league: str,
    oid: str,
    name: str,
    used: set[str],
    owners: list[str],
    *,
    optic_drafted: OpticDrafted | None,
) -> tuple[str, bool]:
    """Same as key_for_code, using the O(1) league index."""
    owner_set = {o.upper() for o in owners}
    if indexed_owner_has_optic(tip, owners, oid):
        return "", False
    drafted = optic_draft_key(optic_drafted, league, oid)
    if drafted:
        return drafted, has_other_owners(owner_set, drafted)
    existing = indexed_optic_key(tip, oid)
    if existing:
        return existing, has_other_owners(owner_set, existing)
    player = person_league(league)
    sole = _sole_unoptic_owner_indexed(tip, owners, name, player=player)
    if sole:
        return sole, has_other_owners(owner_set, sole)
    hit = name_hit_indexed(tip, name, player=player)
    if hit:
        return hit, has_other_owners(owner_set, hit)
    key = fallback_code(name, used, oid)
    return key, has_other_owners(owner_set, key)


def has_other_owners(owners: set[str], key: str) -> bool:
    """True when some other canonical still claims the book code."""
    return bool(owners - {key.upper()})


def _sole_unoptic_owner_indexed(
    tip: TipLeagueIndex,
    owners: list[str],
    name: str,
    *,
    player: bool,
) -> str:
    """Sole owner with no optic id whose name matches, else empty."""
    if len(owners) != 1 or indexed_owner_has_any_optic(tip, owners):
        return ""
    owner = owners[0]
    shown = indexed_name(tip, owner)
    if not names_close(str(shown or ""), name, player=player):
        return ""
    return owner
