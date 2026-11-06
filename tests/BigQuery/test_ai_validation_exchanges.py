"""The exchange registry: every spec is complete and self-consistent, and the
core assembles itself from it (adding an exchange touches only its own module)."""

from __future__ import annotations

import dataclasses
import re

import pytest

from BigQuery import ai_validation as av
from BigQuery import ai_validation_exchanges as exchanges
from BigQuery.ai_validation_exchanges.base import ExchangeSpec

_ORDER = ["Kalshi", "Polymarket", "crypto.com", "Novig"]


def test_registry_order_is_stable_and_names_match_keys():
    assert list(exchanges.EXCHANGES) == _ORDER
    assert all(name == spec.name for name, spec in exchanges.EXCHANGES.items())
    assert tuple(_ORDER) == av.SPORTSBOOKS
    assert av.CORROBORATED_SPORTSBOOKS == ("Kalshi", "Polymarket", "Novig")
    assert set(av.EXCHANGE_PROMPTS) == set(_ORDER)


@pytest.mark.parametrize("name", _ORDER)
def test_every_spec_is_complete(name):
    spec = exchanges.EXCHANGES[name]
    assert isinstance(spec, ExchangeSpec)
    assert spec.prompt.strip()
    assert spec.cte_sql.strip() and spec.join_sql.strip() and spec.select_sql.strip()
    assert spec.lookback_days > 0
    assert "{lookback_days}" in spec.cte_sql  # the lookback is a spec field, not baked in
    assert f"'{spec.name}'" in spec.join_sql  # joins are gated on this exchange's rows only


@pytest.mark.parametrize("name", _ORDER)
def test_cte_and_join_agree(name):
    spec = exchanges.EXCHANGES[name]
    defined = set(re.findall(r"(?:^|\n|, )(\w+) AS \(", spec.cte_sql))
    joined = set(re.findall(r"LEFT JOIN (\w+) ", spec.join_sql))
    assert joined and joined <= defined
    # Each select column is qualified by an alias the join actually introduces.
    aliases = set(re.findall(r"LEFT JOIN \w+ (\w+)", spec.join_sql))
    qualifiers = {c.split(".")[0] for c in re.findall(r"\b\w+\.\w+", spec.select_sql)}
    assert qualifiers and qualifiers <= aliases


@pytest.mark.parametrize("name", _ORDER)
def test_spec_sql_is_in_the_built_query(name):
    spec = exchanges.EXCHANGES[name]
    sql = av.build_sql("proj", revalidate=False, include_corroborated=False)
    assert spec.render_cte("proj") in sql
    assert spec.join_sql in sql
    assert spec.select_sql.split("\n")[0].split(",")[0] in sql
    assert "{" not in sql  # no unfilled placeholder leaked from a fragment


def test_adding_a_spec_changes_build_sql_and_dispatch(monkeypatch):
    before = av.build_sql("proj", revalidate=False, include_corroborated=False)
    fake = dataclasses.replace(
        exchanges.EXCHANGES["Kalshi"],
        name="Fake",
        corroborated=False,
        lookback_days=7,
        cte_sql="fake AS (\n  SELECT 'x' AS fake_id, 'y' AS fake_text FROM `{project}.d.t` WHERE d > {lookback_days}\n)",  # noqa: E501
        join_sql="LEFT JOIN fake z ON m.sportsbook = 'Fake' AND z.fake_id = m.src_market_id",
        select_sql="z.fake_text",
        prompt="FAKE encoding rules",
        has_text=lambda row: bool(row.get("fake_text")),
        ref=lambda row: "ref",
        side=lambda row: "side",
        text=lambda row: "text",
        line=lambda row: "FAKE line",
    )
    monkeypatch.setitem(exchanges.EXCHANGES, "Fake", fake)
    after = av.build_sql("proj", revalidate=False, include_corroborated=False)
    assert after != before
    assert "fake AS (" in after and "d > 7" in after and "z.fake_text" in after
    assert "FAKE encoding rules" in av.system_prompt_for("Fake")
    row = {"sportsbook": "Fake", "fake_text": "t"}
    assert av.has_exchange_text(row) and av.exchange_ref(row) == "ref"
    assert av.exchange_side(row) == "side" and av.exchange_text(row) == "text"
    assert av.row_line(0, row).endswith("|| FAKE line")


def test_unknown_sportsbook_degrades_like_before():
    row = {"sportsbook": "Nope"}
    assert not av.has_exchange_text(row)
    assert av.exchange_ref(row) is None and av.exchange_side(row) is None
    assert av.exchange_text(row) is None
    assert av.system_prompt_for("Nope") == av.system_prompt_for("")


def test_crypto_catalogue_lookback_stays_short() -> None:
    """14 days of crypto_underlying_securities alone billed 46 GB (2026-11-03)."""
    from BigQuery.ai_validation_exchanges.crypto_com import CATALOGUE_LOOKBACK_DAYS

    assert CATALOGUE_LOOKBACK_DAYS <= 3
