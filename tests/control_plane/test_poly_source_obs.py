"""Polymarket US inventory keeps example tickers and the raw sportsMarketType."""

from __future__ import annotations

from mappers.control_plane.gap_fix_market_rules import _observations_from_inventory
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL
from mappers.market_types import MarketType
from mappers.vocab.poly_usa_smt import smt_spec
from tests.control_plane.test_gap_fix_market_rules import _fixtures, _store

_TICKER = "astatc-nfl-phi-chi-2026-09-28-tds-4pt5"


def test_inventory_sql_keeps_three_polymarket_us_tickers() -> None:
    assert "order by p.last_updated desc limit 3" in RFQ_INVENTORY_SQL
    assert (
        "select book, key, demand, last_seen, market_ticker, cast(null as string),\n"
        "    cast(null as string), cast(null as string)\n"
        "  from poly_true"
    ) in RFQ_INVENTORY_SQL


def test_poly_obs_emits_sports_market_type_with_line_evidence() -> None:
    obs = _observations_from_inventory(
        _store(),
        [RfqGapItem(
            book="polymarket",
            key="nfl",
            demand=4,
            meta={
                "sports_market_type": "football_game_total_touchdowns",
                "market_ticker": f"{_TICKER},astatc-nfl-phi-chi-2026-09-28-tds-2pt5",
                "line": "4.5",
                "long_description": "Over",
            },
        )],
        fixtures_fn=_fixtures,
        catalogue_fn=None,
    )
    row = obs[0]
    assert row.get("source_key_type") == "sports_market_type"
    assert row.get("source_key") == "football_game_total_touchdowns"
    assert row.get("sportsbook") == "polymarket_usa"
    refs = row.get("evidence_refs") or []
    assert f"polymarket_usa:ticker:{_TICKER}" in refs
    assert "polymarket_usa:line:4.5" in refs
    assert "polymarket_usa:side:Over" in refs


def test_unknown_sports_market_type_fails_closed() -> None:
    """A known enum maps from the code table; an unknown enum does not."""
    spec = smt_spec("football_game_total_touchdowns")
    assert spec is not None
    assert spec[0] == MarketType.TOTAL_TOUCHDOWNS
    assert smt_spec("not_a_football_shape") is None
