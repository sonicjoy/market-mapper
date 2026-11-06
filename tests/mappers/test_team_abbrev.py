"""Tests for alias loading — load_aliases and resolve_team."""

import pytest

from mappers.shared import CollisionEntry, known_alias_codes, load_aliases, resolve_team


def test_known_alias_codes_unions_overrides():
    """Bootstrap pins count even when the canonical is not on disk yet."""
    known = known_alias_codes({"HEA", "STU"}, {"abc": "MUS2", "def": "KLE"})
    assert known == {"HEA", "STU", "MUS2", "KLE"}


def test_load_aliases_inverts_toml(tmp_path):
    """TOML canonical-first format is inverted to {exchange: {alias: canonical}}."""
    toml_file = tmp_path / "team_aliases.toml"
    toml_file.write_text(
        '[GSW]\npx = ["GS"]\n\n'
        '[NYK]\npx = ["NY"]\nkalshi = ["NYK_ALT"]\n'
    )
    result = load_aliases(toml_file)
    assert result.by_exchange == {
        "px": {"GS": "GSW", "NY": "NYK"},
        "kalshi": {"NYK_ALT": "NYK"},
    }
    assert result.canonicals == {"GSW", "NYK"}


def test_load_aliases_missing_file(tmp_path):
    """Missing file returns empty AliasData."""
    result = load_aliases(tmp_path / "nonexistent.toml")
    assert result.by_exchange == {}
    assert result.canonicals == set()


def test_load_aliases_empty_file(tmp_path):
    """Empty TOML returns empty AliasData."""
    toml_file = tmp_path / "empty.toml"
    toml_file.write_text("")
    result = load_aliases(toml_file)
    assert result.by_exchange == {}
    assert result.canonicals == set()


def test_load_aliases_identity_sections(tmp_path):
    """Empty TOML sections (identity teams) appear in canonicals but not by_exchange."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        '[ATL]\n\n[BOS]\n\n[GSW]\npx = ["GS"]\n'
    )
    result = load_aliases(toml_file)
    assert result.by_exchange == {"px": {"GS": "GSW"}}
    assert result.canonicals == {"ATL", "BOS", "GSW"}


def test_load_aliases_multiple_aliases(tmp_path):
    """A canonical name can have multiple aliases for one exchange."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        '[MCI]\npx = ["Man City", "Manchester City"]\n'
    )
    result = load_aliases(toml_file)
    assert result.by_exchange == {
        "px": {"Man City": "MCI", "Manchester City": "MCI"},
    }
    assert result.canonicals == {"MCI"}


# === Collision entries ===

def test_load_aliases_collision_entries(tmp_path):
    """Table entries produce CollisionEntry lists for ambiguous abbreviations."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        '[COLO]\n'
        'px = [{abbr = "COL", id = 100, name = "Colorado Buffaloes"}]\n\n'
        '[COLU]\n'
        'px = [{abbr = "COL", id = 200, name = "Columbia Lions"}]\n'
    )
    result = load_aliases(toml_file)
    col_value = result.by_exchange["px"]["COL"]
    assert isinstance(col_value, list)
    assert len(col_value) == 2
    assert CollisionEntry("COLO", 100, "Colorado Buffaloes") in col_value
    assert CollisionEntry("COLU", 200, "Columbia Lions") in col_value
    assert result.canonicals == {"COLO", "COLU"}


def test_load_aliases_mixed_simple_and_collision(tmp_path):
    """Simple and collision entries coexist in the same exchange map."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        '[RUTG]\npx = ["RUTGERS"]\n\n'
        '[COLO]\n'
        'px = [{abbr = "COL", id = 100, name = "Colorado Buffaloes"}]\n\n'
        '[COLU]\n'
        'px = [{abbr = "COL", id = 200, name = "Columbia Lions"}]\n'
    )
    result = load_aliases(toml_file)
    assert result.by_exchange["px"]["RUTGERS"] == "RUTG"
    assert isinstance(result.by_exchange["px"]["COL"], list)
    assert result.canonicals == {"RUTG", "COLO", "COLU"}


# === resolve_team ===

def test_resolve_team_simple():
    """Unambiguous abbreviation returns canonical directly."""
    aliases = {"GS": "GSW", "NY": "NYK"}
    assert resolve_team("GS", aliases) == "GSW"


def test_resolve_team_identity():
    """Unknown abbreviation returns itself (identity fallback)."""
    aliases = {"GS": "GSW"}
    assert resolve_team("BOS", aliases) == "BOS"


def test_resolve_team_collision_with_name():
    """Ambiguous abbreviation resolved by name match."""
    aliases = {"COL": [
        CollisionEntry("COLO", 100, "Colorado Buffaloes"),
        CollisionEntry("COLU", 200, "Columbia Lions"),
    ]}
    assert resolve_team("COL", aliases, "Colorado Buffaloes", 100) == "COLO"
    assert resolve_team("COL", aliases, "Columbia Lions", 200) == "COLU"


def test_resolve_team_collision_no_name_raises():
    """Ambiguous abbreviation without name raises ValueError."""
    aliases = {"COL": [
        CollisionEntry("COLO", 100, "Colorado Buffaloes"),
        CollisionEntry("COLU", 200, "Columbia Lions"),
    ]}
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_team("COL", aliases)


def test_resolve_team_collision_wrong_name_raises():
    """Ambiguous abbreviation with unknown name raises ValueError."""
    aliases = {"COL": [
        CollisionEntry("COLO", 100, "Colorado Buffaloes"),
        CollisionEntry("COLU", 200, "Columbia Lions"),
    ]}
    with pytest.raises(ValueError, match="matches none"):
        resolve_team("COL", aliases, "Colgate Raiders")


def test_resolve_team_collision_id_mismatch_asserts():
    """Name matches but id doesn't — consistency check fails."""
    aliases = {"COL": [
        CollisionEntry("COLO", 100, "Colorado Buffaloes"),
    ]}
    with pytest.raises(AssertionError, match="ID mismatch"):
        resolve_team("COL", aliases, "Colorado Buffaloes", 999)
