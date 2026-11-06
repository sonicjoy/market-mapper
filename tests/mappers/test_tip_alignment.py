"""Served-tip alignment: latest seed vs activated tip audit events."""

from unittest.mock import MagicMock, patch

from mappers.control_plane.store import InMemoryStore
from mappers.seed.tip_alignment import (
    check_tip_alignment,
    coalesce_league_keys,
    lineage_ids,
    tip_alignment_event,
)


def test_lineage_ids_walks_tip_to_root():
    parents = {"P_2": "P_1", "P_1": "S0_a", "S0_a": None}
    assert lineage_ids(parents, "P_2") == ["P_2", "P_1", "S0_a"]


def test_lineage_ids_stops_on_cycle():
    parents = {"a": "b", "b": "a"}
    assert lineage_ids(parents, "a") == ["a", "b"]


def test_coalesce_league_keys_nearest_layer_wins():
    layers = [
        [("nfl", False), ("cs2", True)],
        [("nfl", True), ("cs2", False), ("nba", False)],
    ]
    assert coalesce_league_keys(layers) == {"nfl", "nba"}


def _event(*, activated, seed_leagues, served_leagues):
    with patch("mappers.seed.tip_alignment.git_commit_short", return_value="abc1234"):
        return tip_alignment_event(
            seed_rule_set_id="S0_seed",
            activated=activated,
            seed_leagues=seed_leagues,
            served_leagues=served_leagues,
            mapping_run_id="run_1",
            project="marketmaking-test",
            environment="test",
        )


def test_tip_alignment_event_ok_when_activated_is_latest_seed():
    row = _event(
        activated="S0_seed",
        seed_leagues={"nfl", "cs2"},
        served_leagues={"nfl", "cs2"},
    )
    assert row["event_type"] == "tip_alignment_ok"
    assert row["reason_code"] == "activated_tip_aligned"
    assert row["rule_set_id"] == "S0_seed"
    assert row["expected_rule_set_id"] == "S0_seed"
    assert row["environment"] == "test"
    payload = row["payload"]
    assert payload["missing_leagues"] == []
    assert payload["mismatch_count"] == 0
    assert payload["seed_league_count"] == payload["served_league_count"] == 2


def test_tip_alignment_event_ok_when_never_activated():
    row = _event(activated=None, seed_leagues={"nfl"}, served_leagues={"nfl"})
    assert row["event_type"] == "tip_alignment_ok"
    assert row["payload"]["activated_rule_set_id"] is None
    assert row["payload"]["served_rule_set_id"] == "S0_seed"


def test_tip_alignment_event_stale_lists_missing_leagues():
    row = _event(
        activated="P_stale",
        seed_leagues={"nfl", "cs2", "dota_2"},
        served_leagues={"nfl"},
    )
    assert row["event_type"] == "tip_alignment_stale"
    assert row["reason_code"] == "activated_tip_behind_seed"
    assert row["rule_set_id"] == "P_stale"
    assert row["expected_rule_set_id"] == "S0_seed"
    payload = row["payload"]
    assert payload["missing_leagues"] == ["cs2", "dota_2"]
    assert payload["missing_league_count"] == 2
    assert payload["mismatch_count"] == 2
    assert payload["seed_league_count"] == 3
    assert payload["served_league_count"] == 1
    assert payload["mapper_git_commit"] == "abc1234"


def test_tip_alignment_event_stale_when_ids_differ_without_missing_leagues():
    row = _event(
        activated="P_other",
        seed_leagues={"nfl"},
        served_leagues={"nfl", "extra"},
    )
    assert row["event_type"] == "tip_alignment_stale"
    assert row["payload"]["missing_leagues"] == []


class _Row:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _resolver_client(*, activated, rule_sets, leagues) -> MagicMock:
    """Fake client answering the three tip-alignment queries by table name."""

    def query(sql, job_config=None):  # noqa: ARG001 — params unused by the fake
        if "mapping_audit_events" in sql:
            rows = [_Row(rule_set_id=activated)] if activated else []
        elif "mapping_rule_sets" in sql:
            rows = [
                _Row(rule_set_id=rid, parent_rule_set_id=parent)
                for rid, parent in rule_sets.items()
            ]
        else:
            rows = [
                _Row(rule_set_id=rid, league=league, tombstone=False)
                for rid, league in leagues
            ]
        job = MagicMock()
        job.result.return_value = rows
        return job

    client = MagicMock()
    client.query.side_effect = query
    return client


def test_check_tip_alignment_resolves_served_tip_from_activation():
    client = _resolver_client(
        activated="P_stale",
        rule_sets={"S0_seed": None, "P_stale": "S0_old", "S0_old": None},
        leagues=[
            ("S0_seed", "nfl"),
            ("S0_seed", "cs2"),
            ("S0_old", "nfl"),
        ],
    )
    with patch("mappers.seed.tip_alignment.git_commit_short", return_value="abc1234"):
        row = check_tip_alignment(
            client,
            seed_rule_set_id="S0_seed",
            mapping_run_id="run_1",
            project="marketmaking-test",
            environment="test",
        )
    assert row["event_type"] == "tip_alignment_stale"
    assert row["payload"]["served_rule_set_id"] == "P_stale"
    assert row["payload"]["missing_leagues"] == ["cs2"]


def test_check_tip_alignment_ok_when_activation_is_the_seed_tip():
    client = _resolver_client(
        activated="S0_seed",
        rule_sets={"S0_seed": None},
        leagues=[("S0_seed", "nfl")],
    )
    with patch("mappers.seed.tip_alignment.git_commit_short", return_value="abc1234"):
        row = check_tip_alignment(
            client,
            seed_rule_set_id="S0_seed",
            mapping_run_id="run_1",
            project="marketmaking-test",
            environment="test",
        )
    assert row["event_type"] == "tip_alignment_ok"
    assert row["payload"]["served_league_count"] == 1


def test_list_parity_events_includes_tip_alignment():
    store = InMemoryStore(environment="test")
    store.append_audit(
        {
            "event_type": "rule_parity_ok",
            "rule_set_id": "S0_seed",
            "reason_code": "declarative_parity_ok",
            "payload": {"mismatch_count": 0, "mismatches": []},
        }
    )
    store.append_audit(
        {
            "event_type": "tip_alignment_stale",
            "rule_set_id": "P_stale",
            "reason_code": "activated_tip_behind_seed",
            "payload": {
                "latest_seed_rule_set_id": "S0_seed",
                "served_rule_set_id": "P_stale",
                "missing_leagues": ["cs2", "dota_2"],
                "missing_league_count": 2,
                "mismatch_count": 2,
            },
        }
    )
    events = store.list_parity_events()
    assert [e["event_type"] for e in events] == [
        "tip_alignment_stale",
        "rule_parity_ok",
    ]
    assert events[0]["mismatch_count"] == 2
    assert events[0]["payload"]["missing_leagues"] == ["cs2", "dota_2"]


def test_list_parity_events_alignment_ok_defaults_to_zero_mismatches():
    store = InMemoryStore(environment="test")
    store.append_audit(
        {
            "event_type": "tip_alignment_ok",
            "rule_set_id": "S0_seed",
            "reason_code": "activated_tip_aligned",
            "payload": {"served_rule_set_id": "S0_seed"},
        }
    )
    events = store.list_parity_events()
    assert events[0]["mismatch_count"] == 0
