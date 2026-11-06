"""Batched COW layer loading: lineage walk, caching, and coalesce equivalence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_cow import coalesce_entity_layers
from mappers.control_plane.bq_layers import (
    ENTITIES,
    LayerCache,
    entity_row,
    walk_lineage,
)


class _FakeBq:
    """Stand-in for BigQueryStore._query that records every job it would run."""

    def __init__(
        self,
        parents: dict[str, str | None],
        entities: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.parents = parents
        self.entities = entities
        self.calls: list[str] = []

    def query(self, sql: str, params: list[Any] | None = None) -> list[Any]:
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


def _chain_fixture() -> _FakeBq:
    """Three-deep lineage: root adds A/B, mid renames A, tip tombstones B."""
    return _FakeBq(
        parents={"S0": None, "P_mid": "S0", "P_tip": "P_mid"},
        entities={
            "S0": [_entity("A", "Arsenal"), _entity("B", "Brentford")],
            "P_mid": [_entity("A", "Arsenal FC")],
            "P_tip": [_entity("B", "Brentford", tombstone=True)],
        },
    )


def test_walk_lineage_stops_on_cycle():
    parents: dict[str, str | None] = {"a": "b", "b": "a"}
    assert walk_lineage(parents, "a") == ["a", "b"]


def test_walk_lineage_stops_on_unknown_parent():
    parents: dict[str, str | None] = {"tip": "missing"}
    assert walk_lineage(parents, "tip") == ["tip", "missing"]


def test_layers_load_whole_lineage_in_two_jobs():
    fake = _chain_fixture()
    cache = LayerCache()
    ids = cache.lineage(fake.query, "P_tip")
    cache.layers(fake.query, ENTITIES, ids)
    assert ids == ["P_tip", "P_mid", "S0"]
    # One parent-map query plus one IN UNNEST query, not two per ancestor.
    assert fake.calls == ["parents", "entities:P_tip,P_mid,S0"]


def test_layers_reuse_cache_on_second_read():
    fake = _chain_fixture()
    cache = LayerCache()
    ids = cache.lineage(fake.query, "P_tip")
    cache.layers(fake.query, ENTITIES, ids)
    fake.calls.clear()
    cache.layers(fake.query, ENTITIES, cache.lineage(fake.query, "P_tip"))
    assert fake.calls == []


def test_layers_fetch_only_the_uncached_ancestor():
    fake = _chain_fixture()
    cache = LayerCache()
    cache.layers(fake.query, ENTITIES, cache.lineage(fake.query, "P_mid"))
    fake.calls.clear()
    cache.layers(fake.query, ENTITIES, cache.lineage(fake.query, "P_tip"))
    # P_mid and S0 are already cached; only the tip's own delta is fetched.
    assert fake.calls == ["entities:P_tip"]


def test_lineage_reloads_parents_for_an_unknown_id():
    fake = _chain_fixture()
    cache = LayerCache()
    cache.lineage(fake.query, "P_tip")
    fake.calls.clear()
    fake.parents["P_new"] = "P_tip"
    assert cache.lineage(fake.query, "P_new") == ["P_new", "P_tip", "P_mid", "S0"]
    assert fake.calls == ["parents"]


def test_note_candidate_needs_no_round_trip():
    fake = _chain_fixture()
    cache = LayerCache()
    cache.layers(fake.query, ENTITIES, cache.lineage(fake.query, "P_tip"))
    fake.calls.clear()
    cache.note_candidate("P_new", "P_tip", {ENTITIES: []})
    ids = cache.lineage(fake.query, "P_new")
    cache.layers(fake.query, ENTITIES, ids)
    assert ids == ["P_new", "P_tip", "P_mid", "S0"]
    assert fake.calls == []


def test_tip_is_cached_then_overridden_by_set_tip():
    cache = LayerCache(tip_ttl_sec=60.0)
    loads: list[int] = []

    def load() -> str:
        loads.append(1)
        return "P_tip"

    assert cache.tip(load) == "P_tip"
    assert cache.tip(load) == "P_tip"
    assert len(loads) == 1
    cache.set_tip("P_next")
    assert cache.tip(load) == "P_next"
    assert len(loads) == 1


def test_invalidate_tip_forces_a_reload():
    cache = LayerCache(tip_ttl_sec=60.0)
    loads: list[int] = []

    def load() -> str:
        loads.append(1)
        return "P_tip"

    cache.tip(load)
    cache.invalidate_tip()
    cache.tip(load)
    assert len(loads) == 2


def test_batched_layers_coalesce_like_a_per_ancestor_walk():
    """The batched loader must not change what the tip resolves to."""
    fake = _chain_fixture()
    cache = LayerCache()
    ids = cache.lineage(fake.query, "P_tip")
    batched = coalesce_entity_layers(cache.layers(fake.query, ENTITIES, ids))

    per_ancestor = coalesce_entity_layers(
        [
            _rows_for(fake, rid)
            for rid in walk_lineage(fake.parents, "P_tip")
        ]
    )
    assert [(row.canonical_key, row.canonical_name) for row in batched] == [
        (row.canonical_key, row.canonical_name) for row in per_ancestor
    ]
    # Tip tombstone hides B; mid layer wins the rename over root.
    assert [(row.canonical_key, row.canonical_name) for row in batched] == [
        ("A", "Arsenal FC")
    ]


def _rows_for(fake: _FakeBq, rule_set_id: str) -> list[Any]:
    """Load one ancestor the old way, for the equivalence comparison."""
    params = [bigquery.ArrayQueryParameter("ids", "STRING", [rule_set_id])]
    return [entity_row(row) for row in fake.query("select ... unnest(@ids)", params)]
