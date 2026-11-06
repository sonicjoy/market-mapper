"""RFQ volume on Proposed rail fixtures."""

from __future__ import annotations

from mappers.control_plane.console_rfq_demand import (
    _SQL,
    attach_rfq_demand,
    collect_gap_keys,
    fixture_ids_from,
    gap_inventory_keys,
    name_tokens_from,
    query_rfq_demand,
)


def test_gap_keys_keep_event_tickers() -> None:
    assert gap_inventory_keys(
        [
            "gap:KXTENNIS-26SEP03STRUFFCERUN",
            "gap:NX.F.OPT.ATP-1-260903",
            "gap:poly-prefix:atp",
            "gap:usa-inner:atp:STRUFF",
            "gap:poly-name:atp:26sep03",
            "polymarket:slug:cs2-eternal-premium-vs-yologang",
            "kalshi:title:Struff vs Cerundolo",
        ]
    ) == [
        "KXTENNIS-26SEP03STRUFFCERUN",
        "NX.F.OPT.ATP-1-260903",
        "cs2-eternal-premium-vs-yologang",
    ]


def test_collect_gap_keys_unique() -> None:
    rows = [
        {"evidence": ["gap:KXATP-A"]},
        {"evidence": ["gap:KXATP-A", "gap:KXATP-B"]},
    ]
    assert collect_gap_keys(rows) == ["KXATP-A", "KXATP-B"]


def test_query_skips_empty_keys() -> None:
    assert query_rfq_demand([]) == {}
    assert query_rfq_demand(["", ""]) == {}


def test_rail_helpers_collect_ids_and_name_tokens() -> None:
    fixtures = {
        "cs2": [
            {
                "fixture_id": "fx1",
                "home": "eternal premium",
                "away": "yologang",
            }
        ]
    }
    assert fixture_ids_from(fixtures) == ["fx1"]
    assert name_tokens_from(fixtures) == ["eternal-premium", "yologang"]


def test_attach_does_not_double_count_home_and_away() -> None:
    rows = [
        {
            "kind": "alias",
            "evidence": ["gap:KXATP-A"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        },
        {
            "kind": "alias",
            "evidence": ["gap:KXATP-A"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        },
    ]
    fixtures = {"atp": [{"fixture_id": "fx1", "label": "A vs B"}]}
    attach_rfq_demand(rows, fixtures, {"KXATP-A": 12})
    assert rows[0]["rfq_demand"] == 12
    assert rows[1]["rfq_demand"] == 12
    assert fixtures["atp"][0]["rfq_demand"] == 12


def test_attach_sums_kalshi_and_crypto_keys() -> None:
    rows = [
        {
            "kind": "alias",
            "evidence": ["gap:KXATP-A"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        },
        {
            "kind": "alias",
            "evidence": ["gap:NX.F.OPT.ATP-1"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        },
    ]
    fixtures = {"atp": [{"fixture_id": "fx1"}]}
    attach_rfq_demand(rows, fixtures, {"KXATP-A": 12, "NX.F.OPT.ATP-1": 8})
    assert fixtures["atp"][0]["rfq_demand"] == 20


def test_attach_uses_optic_fixture_id_when_pins_have_no_gap_keys() -> None:
    rows = [
        {
            "kind": "alias",
            "evidence": ["optic:competitor:E711:yologang"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        }
    ]
    fixtures = {
        "cs2": [{"fixture_id": "fx1", "home": "eternal premium", "away": "yologang"}]
    }
    attach_rfq_demand(rows, fixtures, {"fx1": 9})
    assert fixtures["cs2"][0]["rfq_demand"] == 9


def test_attach_matches_polymarket_slug_to_fixture_names() -> None:
    rows = [
        {
            "kind": "alias",
            "evidence": ["optic:competitor:E711:yologang"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        }
    ]
    fixtures = {
        "cs2": [{"fixture_id": "fx1", "home": "eternal premium", "away": "yologang"}]
    }
    attach_rfq_demand(
        rows,
        fixtures,
        {"cs2-eternal-premium-vs-yologang-2026-09-05": 7, "other-match": 40},
    )
    assert fixtures["cs2"][0]["rfq_demand"] == 7


def test_attach_prefers_harvest_keys_over_fixture_id() -> None:
    rows = [
        {
            "kind": "alias",
            "evidence": ["gap:KXATP-A"],
            "next_fixtures": [{"fixture_id": "fx1"}],
        }
    ]
    fixtures = {"atp": [{"fixture_id": "fx1", "home": "A", "away": "B"}]}
    attach_rfq_demand(rows, fixtures, {"KXATP-A": 12, "fx1": 99})
    assert fixtures["atp"][0]["rfq_demand"] == 12


def test_demand_sql_uses_shared_crypto_quote_details() -> None:
    assert "quote_details" in _SQL
    assert "MAPPING_FAILED" in _SQL
    assert "COMBOS" in _SQL
    assert "partition by symbol, coalesce(external_rfq_id, '')" in _SQL
