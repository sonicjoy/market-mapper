"""Read-only crypto_id sweep: harvest vs tip entities (no TOML / BQ writes)."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Any

from fetch.crypto_com_aliases import resolve_feed_name_to_code
from mappers.alias_kinds import crypto_pin, is_crypto_id, is_optic_id
from mappers.control_plane.gap_fix_keys import person_league
from mappers.control_plane.rows import EntityRow
from mappers.control_plane.suggest_aliases import competitors_from_fixtures, fetch_optic_fixtures
from mappers.crypto_meta import (
    crypto_meta_code,
    harvest_name_exceptions,
    harvest_team_ids_from_fix,
)

MAX_CRYPTO_SWEEP = 25
DEFAULT_HARVEST_DAYS = 30


def build_crypto_id_suggestions(
    *,
    league: str,
    harvest: dict[str, str],
    entities: Sequence[EntityRow],
    optic_competitors: Sequence[dict[str, str]] | None = None,
    extra_name_index: dict[str, str] | None = None,
    cap: int = MAX_CRYPTO_SWEEP,
) -> dict[str, Any]:
    """Match harvested feed names onto existing tip entities; skip already-pinned ids."""
    league_ents = [e for e in entities if e.league == league and not e.tombstone]
    by_key = {e.canonical_key: e for e in league_ents}
    name_index = _name_index(league_ents, extra_name_index)
    optic_id_to_key = _optic_id_to_key(league_ents)
    _index_optic_competitor_names(name_index, optic_competitors or [], optic_id_to_key)
    cid_owner = _crypto_id_owners(league_ents)
    limit = max(1, min(int(cap), 50))
    suggestions, warnings, assigned, unmatched, already = _match_harvest(
        harvest, name_index, by_key, cid_owner, limit, player=person_league(league)
    )
    if unmatched:
        warnings.append(f"{unmatched} harvest name(s) had no tip entity")
    return {
        "ok": bool(suggestions),
        "warnings": warnings,
        "count": len(suggestions),
        "already_pinned": already,
        "unmatched": unmatched,
        "truncated": max(0, len(assigned) - len(suggestions)),
        "suggestions": suggestions,
    }


def harvest_window_days(days: int | None) -> int:
    """Chat recency cap is 30d; ``<= 0`` means the full catalogue."""
    if days is None:
        return DEFAULT_HARVEST_DAYS
    n = int(days)
    if n <= 0:
        return 0
    return max(1, min(n, DEFAULT_HARVEST_DAYS))


def run_sweep_crypto_ids(
    store: Any,
    league: str,
    *,
    days: int = DEFAULT_HARVEST_DAYS,
    cap: int = MAX_CRYPTO_SWEEP,
    harvest_fn: Callable[[str, int], dict[str, str]] | None = None,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None = None,
    keys: Collection[str] | None = None,
    entities: Sequence[EntityRow] | None = None,
) -> dict[str, Any]:
    """Harvest FIX ids for one tip league and return missing crypto_id pins."""
    slug = league.strip()
    if not slug:
        return _fail(["league is required"])
    rid = store.current_rule_set_id
    if not rid:
        return _fail(["no active tip"])
    tip = next((row for row in store.leagues_for(rid) if row.league == slug), None)
    if tip is None:
        return _fail([f"league not on tip: {slug}"])

    meta = crypto_meta_code(tip)
    if not meta:
        return _fail([f"{slug} has no crypto.com meta on the tip"])
    extra = harvest_name_exceptions(meta)

    harvest_days = harvest_window_days(days)
    harvest, harvest_err = _load_harvest(meta, harvest_days, harvest_fn)
    if harvest_err:
        return _fail([harvest_err])
    competitors, warnings = _load_tip_optic_competitors(tip, fixtures_fn)
    ents = list(entities) if entities is not None else list(store.entities_for(rid))
    if keys is not None:
        want = {str(k) for k in keys if str(k)}
        ents = [row for row in ents if row.canonical_key in want]
    built = build_crypto_id_suggestions(
        league=slug,
        harvest=harvest,
        entities=ents,
        optic_competitors=competitors,
        extra_name_index=extra,
        cap=cap,
    )
    built["warnings"] = [*warnings, *built.get("warnings", [])]
    built["ok"] = bool(built.get("suggestions"))
    return built


def _load_harvest(
    meta: str,
    days: int,
    harvest_fn: Callable[[str, int], dict[str, str]] | None,
) -> tuple[dict[str, str], str | None]:
    harvest_impl = harvest_fn or _default_harvest
    try:
        harvest = harvest_impl(meta, days)
    except Exception as exc:  # noqa: BLE001 — chat tools soft-fail
        return {}, f"crypto harvest failed: {exc}"
    if not harvest:
        if days <= 0:
            return {}, f"no FIX ids for {meta} in catalogue"
        return {}, f"no FIX ids for {meta} in last {days} days"
    return harvest, None


def _load_tip_optic_competitors(
    tip: Any,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Primary plus extra Optic leagues for harvest name matching."""
    horizon = float(tip.fixture_horizon_hours or 96)
    extra = [str(x).strip() for x in (tip.extra_optic_league_ids or [])]
    ids = [str(tip.optic_league_id or "").strip(), *extra]
    competitors: list[dict[str, str]] = []
    warnings: list[str] = []
    for oid in ids:
        if not oid:
            continue
        rows, row_warnings = _load_optic_competitors(oid, horizon, fixtures_fn)
        competitors.extend(rows)
        warnings.extend(row_warnings)
    return competitors, warnings


def _load_optic_competitors(
    optic_id: str,
    horizon_hours: float,
    fixtures_fn: Callable[..., list[dict[str, Any]]] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    if not optic_id:
        return [], []
    fetch = fixtures_fn or fetch_optic_fixtures
    try:
        fixtures = fetch(optic_id, horizon_hours=horizon_hours)
        return competitors_from_fixtures(fixtures), []
    except Exception as exc:  # noqa: BLE001 — name match can still work
        return [], [f"Optic fetch failed: {exc}"]


def _match_harvest(
    harvest: dict[str, str],
    name_index: dict[str, str],
    by_key: dict[str, EntityRow],
    cid_owner: dict[str, str],
    limit: int,
    *,
    player: bool,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str], int, int]:
    suggestions: list[dict[str, Any]] = []
    warnings: list[str] = []
    assigned: dict[str, str] = {}
    unmatched = 0
    already = 0
    for name, cid in sorted(harvest.items(), key=lambda kv: kv[0].casefold()):
        cid = str(cid).strip()
        if not cid:
            continue
        key = resolve_feed_name_to_code(name, name_index, player=player)
        hit = _apply_harvest_hit(
            name, cid, key, by_key, cid_owner, assigned, warnings
        )
        if hit == "unmatched":
            unmatched += 1
        elif hit == "already":
            already += 1
        elif hit == "assigned" and key is not None and len(suggestions) < limit:
            suggestions.append(_suggestion(by_key[key], cid))
    return suggestions, warnings, assigned, unmatched, already


def _apply_harvest_hit(
    name: str,
    cid: str,
    key: str | None,
    by_key: dict[str, EntityRow],
    cid_owner: dict[str, str],
    assigned: dict[str, str],
    warnings: list[str],
) -> str:
    if not key or key not in by_key:
        if sum(1 for w in warnings if "no tip entity" in w) < 5:
            warnings.append(f"{name!r} ({cid}): no tip entity")
        return "unmatched"
    owner = cid_owner.get(cid)
    if owner == key:
        return "already"
    if owner is not None:
        warnings.append(f"{cid}: already pinned on {owner}, skip {key}")
        return "skip"
    prev = assigned.get(key)
    if prev is not None and prev != cid:
        warnings.append(f"{key}: crypto_id clash {prev!r} vs {cid!r}")
        return "skip"
    if prev == cid:
        return "skip"
    assigned[key] = cid
    return "assigned"


def _suggestion(ent: EntityRow, cid: str) -> dict[str, Any]:
    name = ent.canonical_name or ent.canonical_key
    return {
        "id": f"crypto|{ent.league}|{cid}",
        "label": f"{name} ({ent.canonical_key}) ← crypto:{cid}",
        "payload": {
            "kind": "entity_alias",
            "league": ent.league,
            "canonical_key": ent.canonical_key,
            "entity_type": ent.entity_type,
            "canonical_name": name,
            "aliases": [crypto_pin(cid)],
            "reassign": False,
        },
    }


def _name_index(
    entities: Sequence[EntityRow],
    extra: dict[str, str] | None,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, code in (extra or {}).items():
        _put_name(index, name, code)
    for ent in entities:
        _put_name(index, ent.canonical_name, ent.canonical_key)
        _put_name(index, ent.canonical_key, ent.canonical_key)
    return index


def _optic_id_to_key(entities: Sequence[EntityRow]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ent in entities:
        for alias in ent.aliases:
            if not is_optic_id(alias):
                continue
            oid = str(alias.get("alias_value") or "").strip()
            if oid:
                mapping[oid] = ent.canonical_key
    return mapping


def _index_optic_competitor_names(
    name_index: dict[str, str],
    competitors: Sequence[dict[str, str]],
    optic_id_to_key: dict[str, str],
) -> None:
    for comp in competitors:
        oid = str(comp.get("optic_id") or "").strip()
        key = optic_id_to_key.get(oid)
        if not key:
            continue
        _put_name(name_index, comp.get("name"), key)


def _crypto_id_owners(entities: Sequence[EntityRow]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for ent in entities:
        for alias in ent.aliases:
            if not is_crypto_id(alias):
                continue
            cid = str(alias.get("alias_value") or "").strip()
            if cid:
                owners[cid] = ent.canonical_key
    return owners


def _put_name(index: dict[str, str], name: str | None, code: str) -> None:
    text = (name or "").strip()
    if not text:
        return
    index[text] = code
    index[text.casefold()] = code


def _default_harvest(crypto_league: str, days: int) -> dict[str, str]:
    return harvest_team_ids_from_fix(crypto_league, days=days)


def _fail(warnings: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "warnings": warnings,
        "count": 0,
        "already_pinned": 0,
        "unmatched": 0,
        "truncated": 0,
        "suggestions": [],
    }
