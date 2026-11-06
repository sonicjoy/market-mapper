"""Underdog team code catalogue."""

from __future__ import annotations

from mappers.control_plane.rows import EntityRow
from mappers.control_plane.underdog_team_catalog import (
    ncaaf_codes_from_golden,
    parse_appendix_team_tables,
    resolve_team_entity,
)


def test_appendix_tables_cover_game_line_leagues() -> None:
    tables = parse_appendix_team_tables()
    assert len(tables["mlb"]) == 30
    assert len(tables["nfl"]) == 32
    assert len(tables["wnba"]) == 15


def test_ncaaf_codes_from_golden_non_empty() -> None:
    codes = ncaaf_codes_from_golden()
    assert len(codes) >= 10


def test_missing_catalog_files_are_empty(tmp_path) -> None:
    assert parse_appendix_team_tables(tmp_path / "missing.md") == {}
    assert ncaaf_codes_from_golden(tmp_path / "missing.json") == {}


def test_resolve_team_entity_by_canonical_key() -> None:
    entity = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="KC",
        canonical_name="Kansas City Chiefs",
        aliases=[],
    )
    hit = resolve_team_entity([entity], "KC", "Kansas City Chiefs")
    assert hit is entity
