"""Kernel hygiene: flip, MarketType, side_swap, citation host, preserved columns."""

from __future__ import annotations

from mappers.control_plane.bq_layers import market_rule_insert_row
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_tools_propose import propose_markets
from mappers.control_plane.cow_diff import market_rule_change_counts
from mappers.control_plane.dry_run_market_rules import (
    apply_market_rules_payload,
    thin_dry_run_market_rules,
)
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.official_citation import UNCITED_CONFIDENCE, stamp_official_rule
from mappers.control_plane.pin_flow_markets import draft_and_verify_market_rules
from mappers.control_plane.rof_before_rule import rof_before_ignore_observation
from mappers.control_plane.rows import MarketRuleRow
from tests.control_plane.test_chat_routing import _store
from tests.control_plane.test_pin_flow import _ufc_store


def test_blank_yes_side_on_an_ignore_stays_null() -> None:
    obs = rof_before_ignore_observation()
    obs["yes_side"] = "  "
    pins, skipped = draft_and_verify_market_rules(_ufc_store(), [obs])
    assert skipped == []
    rule = next(row for row in pins[0]["rules"] if row["sportsbook"] == "polymarket_usa")
    assert rule["yes_side"] is None


def test_side_swap_false_matches_null_and_does_not_open_a_served_amend() -> None:
    base = MarketRuleRow(
        rule_id="mr",
        league="ufc",
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key="Total Rounds",
        action="map",
        canonical_market_type="total_rounds",
        priority=100,
        enabled=True,
        confidence="manual",
    )
    flipped = MarketRuleRow(**{**base.__dict__, "side_swap": False})
    assert market_rule_change_counts([base], [flipped])["modified_count"] == 0


def test_map_canonical_must_be_a_market_type() -> None:
    store = _ufc_store()
    rid = store.current_rule_set_id
    assert rid is not None
    blocked = thin_dry_run_market_rules(
        list(store.leagues_for(rid)),
        [],
        MappingMarketRulesPayload(
            league="ufc",
            rules=[MarketRulePin(
                sportsbook="polymarket_usa",
                rule_kind="taxonomy",
                source_key_type="ticker_suffix",
                source_key="rof-before-r",
                action="map",
                canonical_market_type="rof-before-r",
            )],
        ),
    )
    assert blocked["ok"] is False
    assert any("not a MarketType" in line for line in blocked["blockers"])


def test_uncited_confidence_drops_only_on_a_book_map() -> None:
    mapped = stamp_official_rule({
        "sportsbook": "kalshi", "action": "map", "source_key": "ROUNDS",
    })
    ignored = stamp_official_rule({
        "sportsbook": "kalshi", "action": "ignore", "source_key": "ROUNDS",
        "confidence": "manual",
    })
    optic = stamp_official_rule({
        "sportsbook": "optic", "action": "map", "source_key": "total_rounds",
        "confidence": "id_verified",
    })
    assert mapped["confidence"] == UNCITED_CONFIDENCE
    assert ignored["confidence"] == "manual"
    assert optic["confidence"] == "id_verified"


def test_upsert_keeps_rule_group_family_and_settlement_note() -> None:
    prior = MarketRuleRow(
        rule_id="mr-keep",
        league="ufc",
        sportsbook="kalshi",
        rule_kind="taxonomy",
        source_key_type="ticker_type",
        source_key="ROUNDS",
        action="map",
        canonical_market_type="total_rounds",
        priority=100,
        enabled=True,
        confidence="manual",
        rule_group_id="grp",
        market_family="rounds",
        settlement_note="venue settles on the bell",
    )
    updated = apply_market_rules_payload(
        [prior],
        MappingMarketRulesPayload(
            league="ufc",
            rules=[MarketRulePin(
                sportsbook="kalshi",
                rule_kind="taxonomy",
                source_key_type="ticker_type",
                source_key="ROUNDS",
                action="map",
                canonical_market_type="total_rounds",
                line_offset=-0.5,
                yes_side="under",
            )],
        ),
    )
    assert updated[0].rule_id == "mr-keep"
    assert updated[0].rule_group_id == "grp"
    assert updated[0].market_family == "rounds"
    assert updated[0].settlement_note == "venue settles on the bell"
    assert updated[0].line_offset == -0.5
    row = market_rule_insert_row("rs", updated[0])
    assert row["rule_group_id"] == "grp"
    assert row["market_family"] == "rounds"
    assert row["settlement_note"] == "venue settles on the bell"


def test_ignore_without_a_market_type_is_not_offered() -> None:
    store = _store()
    rid = store.current_rule_set_id
    assert rid is not None
    rules = [
        MarketRuleRow(**{**row.__dict__, "canonical_market_type": None})
        if row.source_key == "SPREAD" else row
        for row in store.market_rules_for(rid)
    ]
    store.seed_rule_set(
        rule_set_id="S0",
        entities=list(store.entities_for(rid)),
        leagues=list(store.leagues_for(rid)),
        market_rules=rules,
        activate=True,
    )
    bag = ChatSession(conversation_id="flip-none")
    out = propose_markets(store, bag, league="atp", sportsbook="kalshi", market="spread")
    assert not out.get("needs_ignore_confirm")
