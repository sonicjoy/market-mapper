"""COW-aware BQ snapshot loaders for dual-read."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from mappers.seed.bq_snapshot import load_market_rules, load_output_orders


def _batch(rows: list[SimpleNamespace]) -> MagicMock:
    job = MagicMock()
    job.result.return_value = rows
    return job


def _client(*batches: list[SimpleNamespace]) -> MagicMock:
    client = MagicMock()
    client.query.side_effect = [_batch(rows) for rows in batches]
    return client


def _parents() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(rule_set_id="P_tip", parent_rule_set_id="S0_root"),
        SimpleNamespace(rule_set_id="S0_root", parent_rule_set_id=None),
    ]


def _league(rule_set_id: str, league: str, order: list[str], *, tombstone: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        rule_set_id=rule_set_id,
        league=league,
        output_order=order,
        tombstone=tombstone,
    )


def _rule(
    *,
    rule_set_id: str,
    league: str,
    sportsbook: str,
    source_key: str,
    tombstone: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        rule_set_id=rule_set_id,
        rule_id=f"{league}:{source_key}",
        rule_group_id=None,
        league=league,
        sportsbook=sportsbook,
        rule_kind="map",
        source_key_type="ticker_type",
        source_key=source_key,
        match_operator="exact",
        market_family=None,
        canonical_market_type="moneyline",
        action="map",
        priority=1,
        enabled=True,
        confidence="manual",
        notes=None,
        settlement_note=None,
        tombstone=tombstone,
    )


def test_load_output_orders_includes_parent_leagues():
    leagues = [
        _league("P_tip", "italy_serie_a", ["moneyline"]),
        _league("S0_root", "italy_serie_a", ["old"]),
        _league("S0_root", "epl", ["moneyline", "spread"]),
    ]
    orders = load_output_orders(_client(_parents(), leagues), "P_tip")
    assert orders["italy_serie_a"] == ["moneyline"]
    assert orders["epl"] == ["moneyline", "spread"]


def test_load_output_orders_tombstone_hides_parent_league():
    leagues = [
        _league("P_tip", "epl", [], tombstone=True),
        _league("S0_root", "epl", ["moneyline"]),
        _league("S0_root", "nba", ["moneyline"]),
    ]
    orders = load_output_orders(_client(_parents(), leagues), "P_tip")
    assert "epl" not in orders
    assert orders["nba"] == ["moneyline"]


def test_load_market_rules_includes_parent_keys():
    rules = [
        _rule(rule_set_id="P_tip", league="italy_serie_a", sportsbook="optic", source_key="ml"),
        _rule(rule_set_id="S0_root", league="italy_serie_a", sportsbook="optic", source_key="ml"),
        _rule(rule_set_id="S0_root", league="epl", sportsbook="optic", source_key="ml"),
    ]
    loaded = load_market_rules(_client(_parents(), rules), "P_tip")
    keys = {(row.league, row.source_key) for row in loaded}
    assert keys == {("italy_serie_a", "ml"), ("epl", "ml")}


def test_load_market_rules_tombstone_hides_parent_key():
    rules = [
        _rule(
            rule_set_id="P_tip",
            league="epl",
            sportsbook="optic",
            source_key="ml",
            tombstone=True,
        ),
        _rule(rule_set_id="S0_root", league="epl", sportsbook="optic", source_key="ml"),
        _rule(rule_set_id="S0_root", league="nba", sportsbook="optic", source_key="ml"),
    ]
    loaded = load_market_rules(_client(_parents(), rules), "P_tip")
    keys = {(row.league, row.source_key) for row in loaded}
    assert keys == {("nba", "ml")}


def test_load_market_rules_root_only_snapshot():
    parents = [SimpleNamespace(rule_set_id="S0_root", parent_rule_set_id=None)]
    rules = [_rule(rule_set_id="S0_root", league="nba", sportsbook="optic", source_key="ml")]
    loaded = load_market_rules(_client(parents, rules), "S0_root")
    assert [row.league for row in loaded] == ["nba"]
