"""Release 068 G2 — oom fold+rank SQL and CronJob guardrails."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from BigQuery.oom_fold_rank import RANK_VERSION, load_fold_rank_sql, load_soak_sql

_REPO = Path(__file__).resolve().parents[2]
_SQL_PATH = _REPO / "BigQuery" / "sql" / "oom_fold_rank.sql"
_SOAK_SQL_PATH = _REPO / "BigQuery" / "sql" / "oom_fold_rank_soak.sql"
_CRONJOB = _REPO / "deploy" / "k8s" / "mapping-console" / "base" / "oom-fold-rank-cronjob.yaml"
_TEST_ENV = _REPO / "deploy" / "k8s" / "mapping-console" / "overlays" / "test-us" / "oom-fold-rank-env.yaml"
_TEST_CONSOLE_ENV = _REPO / "deploy" / "k8s" / "mapping-console" / "overlays" / "test-us" / "env.yaml"
_PROD_ENV = _REPO / "deploy" / "k8s" / "mapping-console" / "overlays" / "prod-us" / "oom-fold-rank-env.yaml"
_PROD_CONSOLE_ENV = _REPO / "deploy" / "k8s" / "mapping-console" / "overlays" / "prod-us" / "env.yaml"
_INFRA_MERGE = (
    Path(__file__).resolve().parents[3]
    / "mm-infrastructure"
    / "modules"
    / "general_us"
    / "queries"
    / "opticodds"
    / "prices_state_merge.sql"
)


def _load_yaml(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


_MERGE_ON = """
  target.game_id = source.game_id
  and target.market_id = source.market_id
  and lower(target.sportsbook) = source.sportsbook_key
  and target.selection = source.selection
  and ifnull(target.selection_line, '') = source.selection_line
  and ifnull(target.points, 0) = source.points
  and ifnull(target.selection_points, 0) = source.selection_points
  and target.grouping_key = source.grouping_key
""".strip()


def test_sql_header_documents_rank_order() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8").casefold()
    assert "override > curated greg" in body
    assert "optic_passthrough" in body
    assert "tiebreak: verify_tier" in body
    assert "canonical-key string" in body


def test_load_fold_rank_sql_substitutes_project() -> None:
    sql = load_fold_rank_sql("marketmaking-test")
    assert "{project}" not in sql
    assert "`marketmaking-test.opticodds_us.opticodds_mapping`" in sql


def test_load_soak_sql_substitutes_project_and_fixture_window() -> None:
    sql = load_soak_sql("marketmaking-test")
    assert sql.lstrip().casefold().startswith("with ")
    assert "{project}" not in sql
    assert "{fixture_window_where}" not in sql
    assert "`marketmaking-test.opticodds_us.opticodds_mapping`" in sql
    assert sql.count("start_date >=") >= 1
    assert "rank_lag_p99_min" in sql
    assert "approx_quantiles" in sql
    assert "select\n    lower(sportsbook)" in sql
    assert "select *" not in sql.casefold()


def test_soak_sql_file_exists() -> None:
    assert _SOAK_SQL_PATH.is_file()


def test_sql_uses_single_transaction() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8").lower()
    assert re.search(r"^begin;\s*$", body, re.MULTILINE)
    assert re.search(r"^commit;\s*$", body, re.MULTILINE)


def test_sql_merge_key_matches_infra_step_5() -> None:
    body = load_fold_rank_sql("rs-marketmaking")
    fold_merge = re.search(
        (
            r"merge `rs-marketmaking\.opticodds_us\.opticodds_mapping` as target"
            r"\s+using greg_apply as source\s+on\s+(.*?)when matched"
        ),
        body,
        re.IGNORECASE | re.DOTALL,
    )
    assert fold_merge is not None, "greg fold merge block not found"
    on_clause = re.sub(r"\s+", " ", fold_merge.group(1).strip().lower())
    expected = re.sub(r"\s+", " ", _MERGE_ON.lower())
    assert on_clause == expected


def test_sql_permission_probe_uses_fixture_window_partition_filter() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    probe = body.split("-- 1. dedupe greg rows")[0]
    assert probe.count("start_date >=") >= 2


def test_sql_fold_does_not_update_original_rows() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "when matched and target.mapping_source = 'GREG' then" in body
    assert "when matched and target.mapping_source = 'ORIGINAL'" not in body


def test_sql_converts_source_ids_struct_to_json() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "parse_json(to_json_string(source_ids))" in body


def test_sql_fold_preserves_market_mapping_last_updated() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "greg_last_updated" in body
    assert "target.last_updated = source.greg_last_updated" in body
    fold_insert = re.search(
        r"when not matched by target.*?values \((.*?)\);",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    assert fold_insert is not None
    assert "source.greg_last_updated" in fold_insert.group(1)
    assert "current_timestamp()" not in fold_insert.group(1)


def test_sql_greg_apply_breaks_last_updated_ties_on_side_then_ids() -> None:
    """A Kalshi yes + complement no pair on one odd shares a load's last_updated: the yes must win, every run."""
    body = _SQL_PATH.read_text(encoding="utf-8")
    greg_apply = body.split("create temp table greg_apply as")[1].split("-- 2. fold greg")[0]
    aggs = greg_apply.count("array_agg(")
    assert aggs == 10
    tiebroken = re.findall(r"order by last_updated desc, no_side, ids_key\s+limit 1", greg_apply)
    assert len(tiebroken) == aggs
    assert "coalesce(json_value(to_json_string(source_ids), '$.selection_id') = 'no', false) as no_side" in greg_apply
    assert "to_json_string(source_ids) as ids_key" in greg_apply


def test_sql_ranks_rows_with_either_rfq_id_present() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "json_value(o.source_ids, '$.market_id') is not null" in body
    assert "json_value(o.source_ids, '$.selection_id') is not null" in body
    assert " or " in body.split("rank_scored")[1].split("create temp table rank_stamped")[0]


def test_sql_null_market_match_method_is_greg_passthrough() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "o.market_match_method is not null" in body
    assert "when o.mapping_source = 'GREG' then 4" in body
    assert "when o.mapping_source = 'GREG' then 'greg_passthrough'" in body


def test_sql_preserves_fixture_id_when_fixture_lookup_misses() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "coalesce(fl.fixture_id, o.fixture_id)" in body


def test_sql_stamps_rank_version() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert f"target.rank_version = {RANK_VERSION}" in body


# mmmapper#27 real pair (prod 2026-09-27): fixture 202609275E72F08B was re-keyed from
# 40848-66077-2026-09-27-03 (10:00) to -06 (13:00); both copies were stamped winners.
def test_sql_current_game_per_fixture_from_latest_fixture_publish() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "create temp table fixture_current as" in body
    # A completed / cancelled listing is the old game of a reschedule; never "current".
    current = body[
        body.index("create temp table fixture_current as") : body.index(
            "qualify", body.index("create temp table fixture_current as")
        )
    ]
    assert "status in ('unplayed', 'live', 'delayed')" in current
    assert "qualify row_number() over (partition by id order by publish_time desc) = 1;" in body
    assert "drop table fixture_current;" in body


def test_sql_stale_game_ranks_last_and_never_wins() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "coalesce(fc.game_id is not null and fc.game_id != o.game_id, false) as is_stale_game" in body
    rank = body[body.index("create temp table rank_stamped") :]
    order = rank[rank.index("order by") : rank.index(") as rn")]
    keys = order.split()
    assert keys[2:5] == [
        "rs.is_blocked_crosscheck,",
        "rs.is_stale_game,",
        "rs.is_orphan_greg,",
    ]
    assert "not source.is_blocked_crosscheck" in body
    assert "not source.is_stale_game" in body
    assert "not source.is_withdrawn_passthrough" in body


# 2026-09-27 prod: Optic's Polymarket ladder for "Nathan Silva" sat on Jordan
# Silva as greg_passthrough winners. Once the mapper strips it, the upsert-only
# fold must stop serving the orphan row.
def test_sql_blocklist_join_prevents_winner() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "markets_us.optic_passthrough_blocklist" in body
    assert "as is_blocked_crosscheck" in body
    assert "coalesce(o.market_match_method, 'optic_passthrough') = 'optic_passthrough'" in body
    rank = body[body.index("create temp table rank_stamped") :]
    order = rank[rank.index("order by") : rank.index(") as rn")]
    assert "rs.is_blocked_crosscheck," in order


def test_sql_orphan_polymarket_passthrough_never_wins() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    withdrawn = body[
        body.index("(\n    o.mapping_source = 'GREG'") : body.index("as is_withdrawn_passthrough")
    ]
    assert "ga.game_id is null" in withdrawn
    assert "lower(o.sportsbook) = 'polymarket'" in withdrawn
    assert "coalesce(o.market_match_method, 'optic_passthrough') = 'optic_passthrough'" in withdrawn


# Measured 2026-09-28: ~2.1k Underdog / SX Bet / Novig greg winners are orphaned
# in opticodds_mapping with nothing current to replace them. They must still
# serve; an orphan only loses to a current row of the same rfq key.
def test_sql_other_orphan_greg_rows_only_rank_last() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert "(o.mapping_source = 'GREG' and ga.game_id is null) as is_orphan_greg" in body
    winner = body[body.index("target.is_rfq_winner = (") : body.index("target.rank_class")]
    assert "is_orphan_greg" not in winner
    join = body[body.index("left join greg_apply as ga") : body.index("left join fixture_lookup as fl")]
    for pair in (
        "ga.game_id = o.game_id",
        "ga.market_id = o.market_id",
        "ga.sportsbook_key = lower(o.sportsbook)",
        "ga.selection = o.selection",
        "ga.selection_line = ifnull(o.selection_line, '')",
        "ga.points = ifnull(o.points, 0)",
        "ga.selection_points = ifnull(o.selection_points, 0)",
        "ga.grouping_key = o.grouping_key",
    ):
        assert pair in join, pair
    rank = body[body.index("create temp table rank_stamped") :]
    order = rank[rank.index("order by") : rank.index(") as rn")].split()
    assert order[2:5] == [
        "rs.is_blocked_crosscheck,",
        "rs.is_stale_game,",
        "rs.is_orphan_greg,",
    ]


def test_sql_greg_apply_outlives_the_rank_step() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    assert body.index("left join greg_apply as ga") < body.index("drop table greg_apply;")
    assert "delete from" not in body.casefold()


def test_sql_stale_game_lookup_uses_the_rows_own_fixture_id() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    join = body[body.index("left join fixture_current as fc") :]
    assert join.index("coalesce(fl.fixture_id, o.fixture_id)") < join.index("where")
    assert "else o.fixture_id" in join[: join.index("where")]


def test_sql_does_not_touch_infra_price_columns_on_rank_merge() -> None:
    body = _SQL_PATH.read_text(encoding="utf-8")
    rank_update = re.search(
        (
            r"merge `.*?opticodds_mapping` as target\s+using rank_stamped as source"
            r".*?when matched then\s+update set\s+(.*?);"
        ),
        body,
        re.IGNORECASE | re.DOTALL,
    )
    assert rank_update is not None
    updated = rank_update.group(1).casefold()
    for forbidden in (
        "target.market_id",
        "target.sportsbook =",
        "target.selection =",
        "target.mapping_source",
        "target.source_ids",
        "target.is_main",
    ):
        assert forbidden not in updated, forbidden


def test_cronjob_schedule_and_concurrency() -> None:
    doc = _load_yaml(_CRONJOB)
    assert doc["spec"]["schedule"] == "2,17,32,47 * * * *"
    assert doc["spec"]["concurrencyPolicy"] == "Forbid"
    command = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"]
    assert command == ["python", "-m", "mappers.control_plane.pipeline_oom_fold_rank"]
    assert doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["serviceAccountName"] == "mapping-control-plane"


def test_test_overlay_routes_alerts_to_test_channel() -> None:
    doc = _load_yaml(_TEST_ENV)
    env = {
        item["name"]: item["value"]
        for item in doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert doc["spec"].get("suspend") is not True
    assert env["MAPPING_PIPELINE_OOM_FOLD_RANK"] == "1"
    assert env["ALERT_PUBSUB_ENABLED"] == "true"
    assert env["ALERT_SLACK_CHANNEL"] == "#mm-test-app-alerts"
    assert env["MAPPING_PIPELINE_OOM_FOLD_RANK_SOAK"] == "1"
    assert env["OOM_FOLD_RANK_SOAK_ALERT_HOURLY_ONLY"] == "1"


def test_test_overlay_keeps_catalog_on() -> None:
    doc = _load_yaml(_TEST_CONSOLE_ENV)
    env = {item["name"]: item["value"] for item in doc["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env.get("MAPPING_CP_CATALOG", "1") != "0"


def test_prod_overlay_enables_fold_rank() -> None:
    """R_068 G2 lifted on prod 2026-09-21 after G1 schema landed."""
    doc = _load_yaml(_PROD_ENV)
    env = {
        item["name"]: item["value"]
        for item in doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert doc["spec"].get("suspend") is not True
    assert env["MAPPING_PIPELINE_OOM_FOLD_RANK"] == "1"
    assert env["MAPPING_PIPELINE_OOM_FOLD_RANK_SOAK"] == "1"
    assert env["GCP_PROJECT"] == "rs-marketmaking"


def test_prod_overlay_shows_catalog() -> None:
    doc = _load_yaml(_PROD_CONSOLE_ENV)
    env = {item["name"]: item["value"] for item in doc["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["MAPPING_CP_CATALOG"] == "1"


def test_infra_merge_still_has_no_rank_sql() -> None:
    if not _INFRA_MERGE.is_file():
        return
    body = _INFRA_MERGE.read_text(encoding="utf-8")
    assert "is_rfq_winner" not in body
    assert not re.search(r"\brank_", body)
