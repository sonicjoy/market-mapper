"""Crypto gap SQL stays a manual drill-down: one scan per source, not per league."""

from __future__ import annotations

from pathlib import Path

from BigQuery.crypto_gap_config import (
    all_gap_leagues,
    distinct_gap_leagues,
    fixture_prefix_from_symbol,
    gap_league_for_symbol,
)
from BigQuery.crypto_gap_sql import (
    load_all_detail_sql,
    load_all_summary_sql,
    load_detail_sql,
    load_summary_sql,
)

_GAP_SOURCE_TABLES = (
    "markets_us.market_mapping",
    "opticodds_us.opticodds_fixtures",
    "processed_upstream_us.crypto_quote_requests",
    "processed_upstream_us.crypto_underlying_securities",
    "processed_upstream_us.crypto_security_def",
)


def _no_placeholders(sql: str) -> None:
    for token in (
        "{project}", "{core}", "{leagues_struct}", "{league_prefixes}",
        "{league_prefix}", "{optic_horizon_hours}", "{fixture_prefix_re}",
        "{mapped_player_props}", "{mapped_game_lines}",
        "{mapped_team_props}", "{mapped_game_props}", "{optic_league_ids}",
    ):
        assert token not in sql, token


def test_load_all_summary_sql_carries_every_league_as_a_dimension():
    sql = load_all_summary_sql("marketmaking-test")
    for prefix in {g.league_prefix for g in distinct_gap_leagues()}:
        assert f"'{prefix}' as league_prefix" in sql
    assert "group by league_prefix, gap_reason" in sql
    assert "order by league_prefix, total_qr_requests desc" in sql
    _no_placeholders(sql)


def test_load_all_summary_sql_scans_each_source_once():
    sql = load_all_summary_sql("marketmaking-test")
    for table in _GAP_SOURCE_TABLES:
        assert sql.count(f"`marketmaking-test.{table}`") == 1, table


def test_load_all_detail_sql_scans_each_source_once():
    sql = load_all_detail_sql("marketmaking-test")
    for table in _GAP_SOURCE_TABLES:
        assert sql.count(f"`marketmaking-test.{table}`") == 1, table
    assert "league_prefix," in sql
    assert "inferred_type_label" in sql
    assert "limit 1000" in sql
    _no_placeholders(sql)


def test_consolidated_sql_keeps_per_league_vocabulary_and_horizon():
    """The per-league unnest blocks became one struct literal per league."""
    sql = load_all_summary_sql("marketmaking-test")
    tennis = next(g for g in distinct_gap_leagues() if g.league_prefix == "NX.F.OPT.TENNIS")
    ucol = next(g for g in distinct_gap_leagues() if g.league_prefix == "NX.F.OPT.UCOL")
    for optic_id in ("atp", "atp_challenger", "itf_men", "itf_women", "wta"):
        assert f"'{optic_id}'" in sql
    assert tennis.optic_horizon_hours == 168
    assert f"{ucol.optic_horizon_hours} as optic_horizon_hours" in sql
    assert "in unnest(mapped_player_props)" in sql
    assert "in unnest(mapped_game_lines)" in sql
    assert "in unnest(mapped_team_props)" in sql
    assert "in unnest(mapped_game_props)" in sql
    assert "(select optic_horizon_hours from params)" not in sql


def test_all_league_sql_starts_with_with_so_ro_query_accepts_it():
    for sql in (
        load_all_summary_sql("marketmaking-test"),
        load_all_detail_sql("marketmaking-test"),
    ):
        assert sql.split()[0].upper() == "WITH"


def test_load_summary_sql_substitutes_project_without_touching_regex():
    fifa = next(g for g in all_gap_leagues() if g.league_prefix == "NX.F.OPT.FIFA")
    sql = load_summary_sql("marketmaking-test", fifa)
    assert "`marketmaking-test.markets_us.market_mapping`" in sql
    assert "`marketmaking-test.processed_upstream_us.crypto_quote_requests`" in sql
    assert "`marketmaking-test.processed_upstream_us.crypto_security_def`" in sql
    assert "`marketmaking-test.processed_upstream_us.crypto_underlying_securities`" in sql
    assert "raw_ingestion_us.crypto_com_fix_messages2" not in sql
    assert "{project}" not in sql
    assert r"{8}" in sql
    assert r"{6}" in sql
    assert "union all" in sql.casefold()


def test_load_detail_sql_substitutes_ucl_league():
    ucl = next(g for g in all_gap_leagues() if g.league_prefix == "NX.F.OPT.UCL")
    sql = load_detail_sql("marketmaking-test", ucl)
    assert "'NX.F.OPT.UCL'" in sql
    assert "NX\\.F\\.OPT\\.UCL-\\d+-\\d{6}" in sql
    assert "'Moneyline (3-Way)'" in sql
    assert "{project}" not in sql
    assert "{league_prefix}" not in sql


def test_gap_league_for_symbol_ucl():
    sym = "NX.F.OPT.UCL-00001-260714-M.O.1.1.20260830"
    league = gap_league_for_symbol(sym)
    assert league is not None
    assert league.league_prefix == "NX.F.OPT.UCL"
    assert fixture_prefix_from_symbol(sym) == "NX.F.OPT.UCL-00001-260714"


def test_gap_sql_game_props_respect_optic_horizon():
    root = Path(__file__).resolve().parents[2]
    detail = load_detail_sql(
        "marketmaking-test",
        next(g for g in all_gap_leagues() if g.league_prefix == "NX.F.OPT.FIFA"),
    )
    summary = (root / "BigQuery/sql/crypto_mapping_gaps_summary.sql").read_text(encoding="utf-8")
    assert (
        "market_group in ('Game Prop', 'Fight Prop')\n"
        "         and contract_type in (select contract_type from mapped_game_props)\n"
        "         and kickoff > timestamp_add("
    ) in detail
    assert (
        "market_group in ('Game Prop', 'Fight Prop')\n"
        "           and contract_type in (select contract_type from mapped_game_props)\n"
        "           and kickoff > timestamp_add("
    ) in summary
    assert "opticodds_us.opticodds_fixtures" in detail
    assert "no Optic fixture:" in detail
    assert "no Optic fixture:" in summary


def test_tennis_gap_sql_uses_mapper_optic_league_ids():
    tennis = next(g for g in distinct_gap_leagues() if g.league_prefix == "NX.F.OPT.TENNIS")
    assert tennis.optic_league_ids == frozenset({
        "atp", "atp_challenger", "itf_men", "itf_women", "wta",
    })
    sql = load_summary_sql("marketmaking-test", tennis)
    assert "'atp'" in sql
    assert "'atp_challenger'" in sql
    assert "'itf_men'" in sql
    assert "'itf_women'" in sql
    assert "'wta'" in sql
    assert "opticodds_us.opticodds_fixtures" in sql
    assert "{optic_league_ids}" not in sql
