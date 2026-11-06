"""In-memory Optic empty-abbr pins for mapping runs that read the legacy BQ tip."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

from mappers.canonical_codes import fallback_code as _fallback_code
from mappers.optic_sides import fold_side

OpticSource = Path | Iterable[str]


def _league_ids(league_id: str, extra_league_ids: tuple[str, ...]) -> frozenset[str]:
    return frozenset((league_id, *extra_league_ids))


def _iter_competitors(optic_source: OpticSource, league_ids: frozenset[str]):
    """Yield (id, name, abbreviation) for competitors in scope."""
    if isinstance(optic_source, Path):
        if not optic_source.exists():
            return
        line_iter: Iterable[str] = optic_source.open(encoding="utf-8")
    else:
        line_iter = optic_source
    for line in line_iter:
        game = json.loads(line)
        if game.get("league", {}).get("id") not in league_ids:
            continue
        for side in ("home_competitors", "away_competitors"):
            folded = fold_side(game.get(side) or [])
            if folded is None:
                continue
            yield (
                str(folded["id"]),
                str(folded["name"]),
                str(folded["abbreviation"]),
            )


def _pin_empties(
    optic_source: OpticSource,
    league_ids: frozenset[str],
    overrides: dict[str, str],
    used: set[str],
) -> list[tuple[str, str]]:
    """Pin empty-abbr competitors in-memory; return (code, name) added."""
    added: list[tuple[str, str]] = []
    seen: set[str] = set(overrides)
    for optic_id, name, abbr in _iter_competitors(optic_source, league_ids):
        if abbr or not optic_id or optic_id in seen:
            continue
        seen.add(optic_id)
        code = _fallback_code(name, used, optic_id)
        used.add(code)
        overrides[optic_id] = code
        added.append((code, name))
    return added


def _iter_games(optic_source: OpticSource, league_ids: frozenset[str]):
    """Yield home/away competitor triples for games in scope."""
    if isinstance(optic_source, Path):
        if not optic_source.exists():
            return
        line_iter: Iterable[str] = optic_source.open(encoding="utf-8")
    else:
        line_iter = optic_source
    for line in line_iter:
        game = json.loads(line)
        if game.get("league", {}).get("id") not in league_ids:
            continue
        home = fold_side(game.get("home_competitors") or [])
        away = fold_side(game.get("away_competitors") or [])
        if home is None or away is None:
            continue
        yield _comp_triple(home), _comp_triple(away)


def _comp_triple(comp: dict) -> tuple[str, str, str]:
    """id, name, abbreviation for one competitor dict."""
    return (
        str(comp.get("id") or ""),
        str(comp.get("name") or ""),
        (comp.get("abbreviation") or "").strip(),
    )


def pin_shared_optic_abbr(
    home: tuple[str, str, str],
    away: tuple[str, str, str],
    overrides: dict[str, str],
    used: set[str],
) -> list[tuple[str, str, str]]:
    """Pin Optic ids when both sides of a fixture share a non-empty abbr.

    Nantes and Nancy both ship abbreviation NAN; without an id override the
    mapper collapses team totals onto one entity and aborts the league.
    The longer display name keeps the shared abbr; the other gets a
    fallback_code. Already-overridden ids are left alone.
    """
    home_id, home_name, home_abbr = home
    away_id, away_name, away_abbr = away
    if not home_id or not away_id or not home_abbr or home_abbr != away_abbr:
        return []
    added: list[tuple[str, str, str]] = []
    unpinned = [
        (oid, name)
        for oid, name in ((home_id, home_name), (away_id, away_name))
        if oid not in overrides
    ]
    if len(unpinned) == 2:
        unpinned.sort(key=lambda row: (-len(row[1]), row[0]))
        keep_id, _keep_name = unpinned[0]
        overrides[keep_id] = home_abbr
        used.add(home_abbr)
        added.append((keep_id, home_abbr, _keep_name))
        unpinned = [unpinned[1]]
    if len(unpinned) != 1:
        return added
    oid, name = unpinned[0]
    code = _fallback_code(name, used, oid)
    used.add(code)
    overrides[oid] = code
    added.append((oid, code, name))
    return added


def _pin_duplicate_abbrs(
    optic_source: OpticSource,
    league_ids: frozenset[str],
    overrides: dict[str, str],
    used: set[str],
) -> list[tuple[str, str]]:
    """Pin same-abbr fixture pairs; return (code, name) added."""
    added: list[tuple[str, str]] = []
    for home, away in _iter_games(optic_source, league_ids):
        for _oid, code, name in pin_shared_optic_abbr(home, away, overrides, used):
            added.append((code, name))
    return added


def _resolve_optic_source(
    data_dir: Path, optic_lines: Iterable[str] | None,
) -> OpticSource | None:
    if optic_lines is not None:
        return optic_lines
    path = data_dir / "optic_fixtures_odds.jsonl"
    return path if path.exists() else None


def bootstrap_empty_abbrs(
    data_dir: Path,
    league_id: str,
    toml_path: Path,
    *,
    extra_league_ids: tuple[str, ...] = (),
    optic_lines: Iterable[str] | None = None,
    seed_used: set[str] | None = None,
    seed_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Pin empty Optic abbreviations in-memory from the BQ tip + fixtures."""
    del toml_path  # archive TOML path removed in rules-as-data migration
    source = _resolve_optic_source(data_dir, optic_lines)
    overrides = dict(seed_overrides or {})
    if source is None:
        return overrides
    if not isinstance(source, Path):
        source = list(source)
    league_ids = _league_ids(league_id, extra_league_ids)
    used = set(seed_used or ())
    used.update(overrides.values())
    for _cid, _name, abbr in _iter_competitors(source, league_ids):
        if abbr:
            used.add(abbr)
    added = _pin_empties(source, league_ids, overrides, used)
    added.extend(_pin_duplicate_abbrs(source, league_ids, overrides, used))
    if added:
        lines = ", ".join(f"{code} ← {name}" for code, name in added)
        print(
            f"  team bootstrap [{league_id}]: in-memory "
            f"{len(added)} empty/duplicate-abbr pin(s) (BQ SoT): {lines}",
            file=sys.stderr,
        )
    return overrides
