"""DKEX alias bind skip reasons."""

from __future__ import annotations

from mappers.control_plane.gap_fix_dkex_harvest import _alias_bind
from mappers.control_plane.rows import EntityRow


def test_alias_bind_no_entity() -> None:
    bound, reason = _alias_bind("Denver Broncos", [], "nfl")
    assert bound is None
    assert reason == "no_entity"


def test_alias_bind_ambiguous() -> None:
    entities = [
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
        EntityRow(
            league="nfl",
            entity_type="team",
            canonical_key="DEN2",
            canonical_name="Denver Broncos",
            aliases=[],
            enabled=True,
        ),
    ]
    bound, reason = _alias_bind("Denver Broncos", entities, "nfl")
    assert bound is None
    assert reason == "ambiguous"
