"""Serving the COW tail from mapping_entities_current.

The base may only stand in for a lineage walk if it reproduces the walk's row
order exactly. Entity order decides which canonical wins an alias claimed by
several of them, so a reordering here silently re-resolves collisions rather
than failing. Every test below therefore compares full ordered output, not sets.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from google.api_core.exceptions import BadRequest

from mappers.control_plane.bq_cow import coalesce_entity_layers, entity_current_rows
from mappers.control_plane.bq_layers import ENTITIES, LayerCache
from mappers.control_plane.rows import EntityRow


class _FakeBq:
    """Stand-in for BigQueryStore._query that records every job it would run."""

    def __init__(
        self,
        parents: dict[str, str | None],
        entities: dict[str, list[dict[str, Any]]],
        base: list[dict[str, Any]] | None = None,
    ) -> None:
        self.parents = parents
        self.entities = entities
        self.base = base or []
        self.calls: list[str] = []

    def query(self, sql: str, params: list[Any] | None = None) -> list[Any]:
        if "mapping_entities_current" in sql:
            self.calls.append("base")
            return [SimpleNamespace(tombstone=False, **row) for row in self.base]
        if "parent_rule_set_id" in sql:
            self.calls.append("parents")
            return [
                SimpleNamespace(rule_set_id=key, parent_rule_set_id=value)
                for key, value in self.parents.items()
            ]
        ids = list(params[0].values) if params else []
        self.calls.append("entities:" + ",".join(ids))
        return [
            SimpleNamespace(rule_set_id=rid, **row)
            for rid in ids
            for row in self.entities.get(rid, [])
        ]


def _entity(key: str, name: str, *, tombstone: bool = False) -> dict[str, Any]:
    return {
        "league": "epl",
        "entity_type": "team",
        "canonical_key": key,
        "canonical_name": name,
        "aliases": [],
        "enabled": True,
        "notes": None,
        "tombstone": tombstone,
    }


# Chosen so the coalesced order is NOT the natural key order: P_mid renames B,
# which lifts B above A. A base read back in canonical_key order would pass a
# set comparison and still be wrong.
_PARENTS: dict[str, str | None] = {
    "S0": None,
    "P_mid": "S0",
    "P_tip": "P_mid",
    "P_new": "P_tip",
}
_ENTITIES = {
    "S0": [_entity("A", "Arsenal"), _entity("B", "Brentford"), _entity("C", "Chelsea")],
    "P_mid": [_entity("B", "Brentford FC")],
    "P_tip": [_entity("D", "Derby")],
    "P_new": [_entity("A", "Arsenal FC")],
}


def _named(rows: list[EntityRow]) -> list[tuple[str, str | None]]:
    return [(row.canonical_key, row.canonical_name) for row in rows]


def _walk(fake: _FakeBq, rule_set_id: str) -> list[EntityRow]:
    """Coalesce the full lineage with no base in play."""
    cache = LayerCache()
    ids = cache.lineage(fake.query, rule_set_id)
    return coalesce_entity_layers(cache.layers(fake.query, ENTITIES, ids))


def _base_rows_for(fake: _FakeBq, rule_set_id: str) -> list[dict[str, Any]]:
    """Materialize the base exactly as the writer does, then read it back."""
    written = entity_current_rows(rule_set_id, _walk(fake, rule_set_id))
    return [{k: v for k, v in row.items() if k != "materialized_at"} for row in written]


def _fixture(base_at: str | None = None) -> _FakeBq:
    fake = _FakeBq(dict(_PARENTS), dict(_ENTITIES))
    if base_at is not None:
        fake.base = _base_rows_for(fake, base_at)
        fake.calls.clear()
    return fake


def test_the_walk_order_is_not_key_order() -> None:
    """Guards the fixture itself: a key-ordered base would be a false pass."""
    assert _named(_walk(_fixture(), "P_tip")) == [
        ("D", "Derby"),
        ("B", "Brentford FC"),
        ("A", "Arsenal"),
        ("C", "Chelsea"),
    ]


def test_base_reproduces_the_walk_exactly_at_the_materialized_tip() -> None:
    fake = _fixture(base_at="P_tip")
    cache = LayerCache()

    served = coalesce_entity_layers(cache.entity_layers(fake.query, "P_tip"))

    assert _named(served) == _named(_walk(_fixture(), "P_tip"))


def test_base_reproduces_the_walk_for_a_descendant() -> None:
    fake = _fixture(base_at="P_tip")
    cache = LayerCache()

    served = coalesce_entity_layers(cache.entity_layers(fake.query, "P_new"))

    assert _named(served) == _named(_walk(_fixture(), "P_new"))
    assert _named(served) == [
        ("A", "Arsenal FC"),
        ("D", "Derby"),
        ("B", "Brentford FC"),
        ("C", "Chelsea"),
    ]


def test_base_replaces_the_ancestor_fetch() -> None:
    fake = _fixture(base_at="P_tip")
    cache = LayerCache()

    cache.entity_layers(fake.query, "P_new")

    # Only P_new's own delta is fetched; P_tip, P_mid and S0 come from the base.
    assert fake.calls == ["parents", "base", "entities:P_new"]


def test_a_tombstone_above_the_base_still_hides_a_base_row() -> None:
    kill_b = [_entity("B", "Brentford FC", tombstone=True)]
    fake = _fixture(base_at="P_tip")
    fake.entities["P_new"] = kill_b
    walked = _fixture()
    walked.entities["P_new"] = kill_b
    cache = LayerCache()

    served = coalesce_entity_layers(cache.entity_layers(fake.query, "P_new"))

    assert "B" not in {row.canonical_key for row in served}
    assert _named(served) == _named(_walk(walked, "P_new"))


def test_walks_the_lineage_when_the_base_is_empty() -> None:
    fake = _fixture()

    served = coalesce_entity_layers(LayerCache().entity_layers(fake.query, "P_tip"))

    assert _named(served) == _named(_walk(_fixture(), "P_tip"))
    assert "entities:P_tip,P_mid,S0" in fake.calls


def test_walks_the_lineage_when_ordinal_is_missing() -> None:
    """Rows written before the ordinal column cannot reproduce the order."""
    fake = _fixture(base_at="P_tip")
    for row in fake.base:
        row["ordinal"] = None

    served = coalesce_entity_layers(LayerCache().entity_layers(fake.query, "P_new"))

    assert _named(served) == _named(_walk(_fixture(), "P_new"))
    assert "entities:P_new,P_tip,P_mid,S0" in fake.calls


def test_walks_the_lineage_when_the_base_query_fails() -> None:
    """An image running ahead of the Terraform apply has no ordinal column."""
    fake = _fixture(base_at="P_tip")
    real_query = fake.query

    def query(sql: str, params: list[Any] | None = None) -> list[Any]:
        if "mapping_entities_current" in sql:
            raise BadRequest("Unrecognized name: ordinal")
        return real_query(sql, params)

    served = coalesce_entity_layers(LayerCache().entity_layers(query, "P_new"))

    assert _named(served) == _named(_walk(_fixture(), "P_new"))


def test_walks_the_lineage_when_the_base_is_not_an_ancestor() -> None:
    fake = _fixture(base_at="P_tip")
    for row in fake.base:
        row["rule_set_id"] = "P_unrelated"

    served = coalesce_entity_layers(LayerCache().entity_layers(fake.query, "P_new"))

    assert _named(served) == _named(_walk(_fixture(), "P_new"))
    assert "entities:P_new,P_tip,P_mid,S0" in fake.calls


def test_a_stale_base_is_still_correct() -> None:
    """A base from an older ancestor is a truthful coalesce of that ancestor."""
    fake = _fixture(base_at="P_mid")
    cache = LayerCache()

    served = coalesce_entity_layers(cache.entity_layers(fake.query, "P_new"))

    assert _named(served) == _named(_walk(_fixture(), "P_new"))
    assert fake.calls == ["parents", "base", "entities:P_new,P_tip"]


def test_the_base_is_read_once_per_process() -> None:
    fake = _fixture(base_at="P_tip")
    cache = LayerCache()

    cache.entity_layers(fake.query, "P_tip")
    cache.entity_layers(fake.query, "P_new")

    assert fake.calls.count("base") == 1


def test_set_entity_base_avoids_the_read_back() -> None:
    fake = _fixture(base_at="P_tip")
    cache = LayerCache()

    cache.set_entity_base("P_tip", _walk(_fixture(), "P_tip"))
    served = coalesce_entity_layers(cache.entity_layers(fake.query, "P_new"))

    assert "base" not in fake.calls
    assert _named(served) == _named(_walk(_fixture(), "P_new"))


def test_entity_current_rows_stamp_contiguous_ordinals_in_walk_order() -> None:
    entities = _walk(_fixture(), "P_tip")

    rows = entity_current_rows("P_tip", entities)

    assert [row["ordinal"] for row in rows] == list(range(len(entities)))
    assert [row["canonical_key"] for row in rows] == [e.canonical_key for e in entities]


def test_entity_current_rows_keep_ordinals_contiguous_across_tombstones() -> None:
    def row(key: str, *, tombstone: bool = False) -> EntityRow:
        return EntityRow(
            league="epl",
            entity_type="team",
            canonical_key=key,
            canonical_name=key,
            aliases=[],
            tombstone=tombstone,
        )

    entities = [row("A"), row("B", tombstone=True), row("C")]

    rows = entity_current_rows("P_tip", entities)

    assert [(row["canonical_key"], row["ordinal"]) for row in rows] == [("A", 0), ("C", 1)]
