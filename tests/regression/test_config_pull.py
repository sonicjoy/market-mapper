"""Tests for regression/config_pull.py (step 5, side-B materializer).

Everything here exercises the pure parts (lineage walk, COW
coalesce, record explosion, cache pathing) on fixture rows shaped
exactly like bq CLI JSON output — stringified scalars included,
because that wire format is where the nastiest bug lives
(bool("false") is True)."""
import json

import pytest

import datetime

from regression.config_project import VERSION, strip_annotations
from regression.config_pull import (
    KNOWN_STALE_ROWS,
    SnapshotIntegrityError,
    _RULE_KEY,
    _by_layer,
    canon_config_path,
    coalesce,
    drop_known_stale,
    lineage,
    materialize,
    records_from,
)


def receipt(rid, parent=None):
    return {"rule_set_id": rid, "parent_rule_set_id": parent,
            "source_revision": "a0ffe0c7c199", "environment": "prod"}


def rule(rid, source_key, **over):
    """A mapping_market_rules row as the bq CLI would emit it."""
    row = {
        "rule_set_id": rid, "rule_id": "fc054b9872ab0b4d",
        "rule_group_id": None, "league": "mlb", "sportsbook": "kalshi",
        "rule_kind": "taxonomy", "source_key_type": "ticker_type",
        "source_key": source_key, "source_selection_key": None,
        "match_operator": "exact", "market_family": None,
        "period": None, "effective_from_date": None,
        "effective_to_date": None,
        "canonical_market_type": "point_spread",
        "target_optic_odd_id": None, "action": "map",
        "priority": "100", "enabled": "true",
        "confidence": "id_verified", "evidence_refs": [],
        "created_from_gap_event_id": None, "proposal_id": None,
        "notes": None, "settlement_note": None, "tombstone": None,
    }
    row.update(over)
    return row


def entity(rid, key, aliases=(), **over):
    row = {
        "rule_set_id": rid, "league": "mlb", "entity_type": "team",
        "canonical_key": key, "canonical_name": "New York Mets",
        "enabled": "true", "aliases": list(aliases), "notes": None,
        "tombstone": None,
    }
    row.update(over)
    return row


# --- lineage -----------------------------------------------------------

def test_lineage_root_only():
    chain = lineage("S0_a", [receipt("S0_a")])
    assert [r["rule_set_id"] for r in chain] == ["S0_a"]


def test_lineage_walks_tip_to_root():
    chain = lineage("P_c", [receipt("S0_a"),
                            receipt("P_b", parent="S0_a"),
                            receipt("P_c", parent="P_b")])
    assert [r["rule_set_id"] for r in chain] == ["P_c", "P_b", "S0_a"]


def test_lineage_dangling_parent_is_loud():
    """cow_rebuild would quietly stop; a snapshot with unresolvable
    ancestry must never materialize shallow."""
    with pytest.raises(SnapshotIntegrityError, match="dangling"):
        lineage("P_b", [receipt("P_b", parent="S0_gone")])


def test_lineage_cycle_is_loud():
    with pytest.raises(SnapshotIntegrityError, match="cycle"):
        lineage("P_a", [receipt("P_a", parent="P_b"),
                        receipt("P_b", parent="P_a")])


def test_lineage_duplicate_receipt_is_loud():
    with pytest.raises(SnapshotIntegrityError, match="duplicate"):
        lineage("S0_a", [receipt("S0_a"), receipt("S0_a")])


# --- coalesce ----------------------------------------------------------

def test_coalesce_tip_wins_over_root():
    tip = rule("P_b", "SPREAD", canonical_market_type="game_total")
    root = rule("S0_a", "SPREAD")
    [got] = coalesce([[tip], [root]], _RULE_KEY)
    assert got["canonical_market_type"] == "game_total"
    assert got["rule_set_id"] == "P_b"


def test_coalesce_tombstone_hides_ancestor_row():
    dead = rule("P_b", "SPREAD", tombstone="true")
    root = rule("S0_a", "SPREAD")
    keeper = rule("S0_a", "TOTAL")
    got = coalesce([[dead], [root, keeper]], _RULE_KEY)
    assert [r["source_key"] for r in got] == ["TOTAL"]


def test_coalesce_string_false_tombstone_is_not_a_delete():
    """bq JSON stringifies scalars; bool(\"false\") is True, so a
    truthiness test would delete explicitly-live rows."""
    [got] = coalesce([[rule("S0_a", "SPREAD", tombstone="false")]],
                     _RULE_KEY)
    assert got["source_key"] == "SPREAD"


def test_coalesce_strips_the_tombstone_column():
    [got] = coalesce([[rule("S0_a", "SPREAD")]], _RULE_KEY)
    assert "tombstone" not in got


def test_coalesce_garbage_tombstone_is_loud():
    with pytest.raises(SnapshotIntegrityError, match="untombstoneable"):
        coalesce([[rule("S0_a", "SPREAD", tombstone="maybe")]],
                 _RULE_KEY)


def test_coalesce_duplicate_key_within_one_layer_is_loud():
    with pytest.raises(SnapshotIntegrityError, match="within one layer"):
        coalesce([[rule("S0_a", "SPREAD"), rule("S0_a", "SPREAD")]],
                 _RULE_KEY)


def test_by_layer_orders_rows_by_lineage():
    chain = [receipt("P_b", parent="S0_a"), receipt("S0_a")]
    rows = [rule("S0_a", "SPREAD"), rule("P_b", "SPREAD")]
    layers = _by_layer(rows, chain)
    assert [[r["rule_set_id"] for r in layer] for layer in layers] \
        == [["P_b"], ["S0_a"]]


# --- records -----------------------------------------------------------

ALIAS = {"alias_id": "al_1", "sportsbook": "kalshi",
         "alias_kind": "code", "alias_value": "NYM",
         "normalized_alias_value": None, "normalization_profile": None,
         "disambiguation_id": None, "disambiguation_name": None,
         "priority": None, "enabled": "true",
         "confidence": "id_verified", "evidence_refs": [],
         "created_from_gap_event_id": None, "proposal_id": None,
         "notes": None}


def test_entity_explodes_into_entity_plus_alias_records():
    ent = entity("S0_a", "NYM", aliases=[ALIAS])
    ent.pop("tombstone")
    recs = list(records_from([], [ent], [], "S0_a"))
    kinds = [k for k, _ in recs]
    assert kinds == ["entity", "alias"]
    alias_rec = recs[1][1]
    assert (alias_rec["league"], alias_rec["entity_type"],
            alias_rec["canonical_key"]) == ("mlb", "team", "NYM")
    assert alias_rec["alias_value"] == "NYM"
    assert alias_rec["rule_set_id"] == "S0_a"


def test_canonical_markets_carry_tip_provenance():
    cm = {"canonical_market_type": "point_spread", "scope": "game",
          "shape": "spread", "enabled": "true", "description": "SPREAD"}
    [(kind, rec)] = list(records_from([], [], [cm], "S0_tip"))
    assert kind == "canonical_market"
    assert rec["rule_set_id"] == "S0_tip"


# --- known-stale exemption ---------------------------------------------

# The real pinned pair: the stale ignore (dropped) and the live map
# (kept), exactly as they sit in every current prod seed.
MOV_IGNORE = rule("S0_a", "method_of_victory", league="ufc",
                  sportsbook="optic", source_key_type="market_id",
                  rule_id="c32db3f13913e0c9", action="ignore",
                  canonical_market_type=None, priority="50")
MOV_MAP = rule("S0_a", "method_of_victory", league="ufc",
               sportsbook="optic", source_key_type="market_id",
               rule_id="05898797225ae9e3",
               canonical_market_type="method_of_victory")


@pytest.fixture
def pin_live(monkeypatch):
    """The pin's real expiry is a policy date that passes; these tests are about the drop, not the clock."""
    monkeypatch.setitem(KNOWN_STALE_ROWS["c32db3f13913e0c9"], "expires", "9999-12-31")


def test_pinned_stale_row_is_dropped_and_map_survives(capsys, pin_live):
    kept = drop_known_stale([MOV_MAP, MOV_IGNORE])
    assert kept == [MOV_MAP]
    assert "DROPPED known-stale row c32db3f13913e0c9" in \
        capsys.readouterr().err


def test_pin_matching_nothing_reports_delete_me(capsys):
    kept = drop_known_stale([MOV_MAP])
    assert kept == [MOV_MAP]
    assert "matched nothing" in capsys.readouterr().err


def test_pin_with_changed_content_refuses_to_drop():
    """The expect fields are belt-and-braces against a rule_id that
    no longer means what was verified — never a silent drop."""
    mutated = dict(MOV_IGNORE, action="map")
    with pytest.raises(SnapshotIntegrityError, match="disagrees"):
        drop_known_stale([mutated])


def test_expired_pin_that_still_matches_is_an_error():
    after = datetime.date.fromisoformat(
        KNOWN_STALE_ROWS["c32db3f13913e0c9"]["expires"]) \
        + datetime.timedelta(days=1)
    with pytest.raises(SnapshotIntegrityError, match="expired"):
        drop_known_stale([MOV_IGNORE], today=after)


def test_materialize_passes_on_the_real_mov_conflict(capsys, pin_live):
    """End-to-end: the exact prod conflict materializes, keeping the
    map; an unpinned duplicate elsewhere still fails loud."""
    q = fake_query([receipt("S0_a")], [MOV_MAP, MOV_IGNORE], [], [])
    lines, stats, _ = materialize("S0_a", query=q)
    assert stats["market_rule"] == 1
    [d] = [json.loads(li) for li in lines]
    assert d["v"]["action"] == "map"
    assert "DROPPED" in capsys.readouterr().err


# --- materialize (fake bq) ---------------------------------------------

def fake_query(receipts, rules, entities, canonical_markets):
    def query(sql):
        if "mapping_market_rules" in sql:
            return rules
        if "mapping_entities" in sql:
            return entities
        if "canonical_markets" in sql:
            return [{"canonical_markets": canonical_markets}]
        return receipts
    return query


def test_materialize_end_to_end_over_a_cow_lineage():
    """One edited rule, one tombstoned entity, tip-only alias — the
    canonical lines reflect the coalesced logical snapshot."""
    receipts = [receipt("S0_a"), receipt("P_b", parent="S0_a")]
    rules = [rule("S0_a", "SPREAD"),
             rule("S0_a", "TOTAL", canonical_market_type="game_total"),
             rule("P_b", "SPREAD", canonical_market_type="run_line")]
    entities = [entity("S0_a", "NYM", aliases=[ALIAS]),
                entity("S0_a", "BOS", canonical_name="Boston Red Sox"),
                entity("P_b", "BOS", tombstone="true", aliases=[])]
    lines, stats, tip = materialize(
        "P_b", query=fake_query(receipts, rules, entities, []))
    assert stats == {"market_rule": 2, "entity": 1, "alias": 1,
                     "canonical_market": 0}
    assert tip["rule_set_id"] == "P_b"
    spread = next(json.loads(li) for li in lines
                  if json.loads(li)["k"][-1:] == ["SPREAD"])
    assert spread["v"]["canonical_market_type"] == "run_line"
    assert spread["a"]["rule_set_id"] == "P_b"
    assert not any(json.loads(li)["k"][-1] == "BOS" for li in lines
                   if json.loads(li)["t"] == "entity")


def test_materialize_bq_strings_compare_equal_to_ir_types():
    """The stringified wire format canonicalizes to the same compared
    form as proper types — the whole point of the shared writer."""
    wire = fake_query([receipt("S0_a")], [rule("S0_a", "SPREAD")],
                      [], [])
    typed = fake_query(
        [receipt("S0_a")],
        [rule("S0_a", "SPREAD", priority=100, enabled=True)], [], [])
    a, _, _ = materialize("S0_a", query=wire)
    b, _, _ = materialize("S0_a", query=typed)
    assert [strip_annotations(li) for li in a] \
        == [strip_annotations(li) for li in b]


def test_malformed_rule_set_id_never_reaches_sql():
    with pytest.raises(ValueError, match="malformed"):
        materialize("S0_a'; drop table --",
                    query=fake_query([], [], [], []))


def test_cache_path_carries_project_and_contract_version():
    p = canon_config_path("rs-marketmaking", "S0_cb85f20c3ad7")
    assert p.name == f"rs-marketmaking.S0_cb85f20c3ad7.v{VERSION}.jsonl"
    assert p.parent.name == "config"
