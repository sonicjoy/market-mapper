"""Retag combat match-side entities from team -> fighter in one COW activation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from mappers.control_plane.cow_diff import entity_change_counts, league_change_counts
from mappers.control_plane.entity_types import match_entity_type
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.seed.league_meta import league_settings_from_row, merge_league_meta_into_exchanges

COMBAT_LEAGUES = frozenset({"ufc", "boxing_matches"})
_MATCH_SIDE = frozenset({"team", "fighter"})


def combat_league_slugs(leagues: list[LeagueRow]) -> frozenset[str]:
    """Leagues on the tip that should use fighter match-side type."""
    out: set[str] = set()
    for row in leagues:
        if row.tombstone:
            continue
        if row.league in COMBAT_LEAGUES:
            out.add(row.league)
            continue
        if match_entity_type(row.league, sport=row.sport) == "fighter":
            out.add(row.league)
    return frozenset(out)


def resolve_retag_targets(
    leagues: list[LeagueRow],
    requested: list[str] | None = None,
) -> tuple[frozenset[str], list[str]]:
    """Combat slugs on the tip; refuse unknown or non-combat payload slugs."""
    present = combat_league_slugs(leagues) & COMBAT_LEAGUES
    blockers: list[str] = []
    extra = {slug.strip() for slug in (requested or []) if slug.strip()} - COMBAT_LEAGUES
    if extra:
        blockers.append(f"combat retag refuses non-combat leagues: {sorted(extra)}")
    if not present:
        blockers.append("no UFC/boxing_matches leagues on the tip")
    return present, blockers


def apply_combat_entity_retag(
    entities: list[EntityRow],
    leagues: list[LeagueRow],
    *,
    target_leagues: frozenset[str] | None = None,
) -> tuple[list[EntityRow], list[LeagueRow]]:
    """Return full logical entity + league snapshots after combat retag."""
    want = target_leagues if target_leagues is not None else COMBAT_LEAGUES
    return (
        _retag_entities(entities, want),
        _retag_league_settings(leagues, want),
    )


def dry_run_combat_retag(
    entities: list[EntityRow],
    leagues: list[LeagueRow],
    *,
    requested: list[str] | None = None,
    target_leagues: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Summarize retag deltas; fail closed when unsafe or already live."""
    want, blockers = resolve_retag_targets(leagues, requested)
    if target_leagues is not None:
        want = target_leagues
    blockers.extend(_optic_blockers(leagues, want))
    if blockers:
        return _dry(False, blockers, {}, {})
    child_ent, child_lg = apply_combat_entity_retag(
        entities, leagues, target_leagues=want,
    )
    ent_counts = entity_change_counts(entities, child_ent)
    lg_counts = league_change_counts(leagues, child_lg)
    change_count = sum(ent_counts.values()) + sum(lg_counts.values())
    if change_count == 0:
        blockers.append("combat entity_type retag already live on the tip")
    return _dry(not blockers, blockers, ent_counts, lg_counts, change_count)


def _dry(
    ok: bool,
    blockers: list[str],
    ent_counts: dict[str, int],
    lg_counts: dict[str, int],
    change_count: int = 0,
) -> dict[str, Any]:
    added = int(ent_counts.get("added_count") or 0)
    modified = int(ent_counts.get("modified_count") or 0)
    removed = int(ent_counts.get("removed_count") or 0)
    return {
        "ok": ok,
        "blockers": blockers,
        "warnings": [],
        "summary": (
            f"Retag team → fighter: add {added} fighter rows, "
            f"update {modified}, tombstone {removed} team rows, "
            f"{int(lg_counts.get('modified_count') or 0)} league setting updates"
        ),
        "change_count": change_count,
        "item_count": 1,
        "entity_counts": ent_counts,
        "league_counts": lg_counts,
    }


def _optic_blockers(leagues: list[LeagueRow], targets: frozenset[str]) -> list[str]:
    missing = [
        row.league
        for row in leagues
        if row.league in targets and not row.tombstone and not _has_optic(row)
    ]
    if not missing:
        return []
    return [f"combat retag needs an optic exchange on: {sorted(missing)}"]


def _has_optic(row: LeagueRow) -> bool:
    return any(
        str(ex.get("sportsbook") or "") == "optic" and ex.get("enabled", True)
        for ex in row.exchanges
    )


def _retag_league_settings(
    leagues: list[LeagueRow],
    target_leagues: frozenset[str],
) -> list[LeagueRow]:
    out: list[LeagueRow] = []
    for row in leagues:
        if row.league not in target_leagues or row.tombstone:
            out.append(row)
            continue
        settings = dict(row.settings or league_settings_from_row(row))
        settings["entity_type"] = "fighter"
        clone = deepcopy(row)
        clone.settings = settings
        clone.exchanges = merge_league_meta_into_exchanges(clone.exchanges, settings)
        out.append(clone)
    return out


def _retag_entities(
    entities: list[EntityRow],
    target_leagues: frozenset[str],
) -> list[EntityRow]:
    kept = [e for e in entities if e.league not in target_leagues]
    combat = [e for e in entities if e.league in target_leagues and not e.tombstone]
    by_key: dict[tuple[str, str], list[EntityRow]] = {}
    for ent in combat:
        if ent.entity_type not in _MATCH_SIDE:
            kept.append(ent)
            continue
        by_key.setdefault((ent.league, ent.canonical_key), []).append(ent)
    return kept + [_merge_match_side(group) for group in by_key.values()]


def _merge_match_side(group: list[EntityRow]) -> EntityRow:
    teams = [e for e in group if e.entity_type == "team"]
    fighters = [e for e in group if e.entity_type == "fighter"]
    base = fighters[0] if fighters else teams[0]
    pool = teams + fighters
    return EntityRow(
        league=base.league,
        entity_type="fighter",
        canonical_key=base.canonical_key,
        canonical_name=_best_name(pool),
        aliases=_merge_aliases(pool),
        enabled=(teams[0].enabled if teams else fighters[0].enabled),
        notes=base.notes,
    )


def _best_name(rows: list[EntityRow]) -> str | None:
    teams = [e for e in rows if e.entity_type == "team"]
    source = teams or rows
    names = [str(e.canonical_name or "").strip() for e in source if e.canonical_name]
    if not names:
        return rows[0].canonical_name
    return max(names, key=len)


def _alias_triple(alias: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(alias.get("sportsbook") or ""),
        str(alias.get("alias_kind") or ""),
        str(alias.get("alias_value") or ""),
    )


def _merge_aliases(rows: list[EntityRow]) -> list[dict[str, Any]]:
    first: dict[tuple[str, str, str], dict[str, Any]] = {}
    disabled: set[tuple[str, str, str]] = set()
    for ent in rows:
        for alias in ent.aliases:
            key = _alias_triple(alias)
            if not key[2]:
                continue
            if alias.get("enabled") is False:
                disabled.add(key)
            first.setdefault(key, dict(alias))
    out: list[dict[str, Any]] = []
    for key, alias in first.items():
        row = dict(alias)
        if key in disabled:
            row["enabled"] = False
        out.append(row)
    return out
