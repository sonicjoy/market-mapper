"""Harvest mapping_market_rules from RFQ demand (kernel + AI last layer)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM
from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_ai_suggest import AI_NOTE, AI_REF, is_ai_suggest_pin
from mappers.control_plane.gap_fix_market_ai import append_ai_market_suggestions
from mappers.control_plane.gap_fix_market_rules import _observations_from_inventory, harvest_missing_market_rules
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_market_bind import live_optic_census, spine_bind
from mappers.control_plane.pin_flow_markets import MarketRuleObservation, draft_and_verify_market_rules
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.control_plane.store import InMemoryStore
from mappers.exchanges.crypto_com import FIGHT_LINE, FIGHT_PROP, GAME_LINE, GAME_PROP, PLAYER_PROP


def _wnba_league() -> LeagueRow:
    return LeagueRow(
        league="wnba",
        sport="basketball",
        optic_league_id="wnba",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[],
    )


def _wnba_store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_wnba",
        entities=[],
        leagues=[_wnba_league()],
        market_rules=[],
        activate=True,
    )
    return store


def _nfl_league() -> LeagueRow:
    return LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[
            {
                "sportsbook": "crypto.com",
                "enabled": True,
                "parser_profile": "crypto_generic_v1",
                "source_league_id": "NFL",
                "settings": {
                    "league": "NFL",
                    "sport_grouping": "NFL",
                    "period_type": "Full Game",
                },
            },
            {
                "sportsbook": "polymarket_usa",
                "enabled": True,
                "parser_profile": "poly_usa_generic_v1",
                "source_league_id": "nfl",
                "settings": {"slug_prefix": "nfl"},
            },
        ],
    )


def _store(*, rules: list[MarketRuleRow] | None = None) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_mr",
        entities=[],
        leagues=[_nfl_league()],
        market_rules=rules or [],
        activate=True,
    )
    return store


def _mlb_league() -> LeagueRow:
    return LeagueRow(
        league="mlb",
        sport="baseball",
        optic_league_id="mlb",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[
            {
                "sportsbook": "crypto.com",
                "enabled": True,
                "parser_profile": "crypto_generic_v1",
                "source_league_id": "MLB",
                "settings": {
                    "league": "MLB",
                    "sport_grouping": "MLB",
                    "period_type": "Full-Game",
                },
            },
        ],
    )


def _mlb_store(*, rules: list[MarketRuleRow] | None = None) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_mlb",
        entities=[],
        leagues=[_mlb_league()],
        market_rules=rules or [],
        activate=True,
    )
    return store


def _fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "fx1",
            "odds": [
                {"market_id": "moneyline", "selection": "Team A"},
                {"market_id": "point_spread", "selection": "Team A"},
            ],
        },
    ]


def test_crypto_game_line_unique_bind_creates_optic_and_book_pins() -> None:
    store = _store(
        rules=[
            MarketRuleRow(
                rule_id="mr-optic-ps",
                league="nfl",
                sportsbook="optic",
                rule_kind="taxonomy",
                source_key_type="market_id",
                source_key="point_spread",
                action="map",
                canonical_market_type="point_spread",
                priority=100,
                enabled=True,
                confidence="manual",
            ),
        ],
    )
    obs: MarketRuleObservation = {
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": 4,
        "market_group": GAME_LINE,
        "evidence_refs": ["gap:NX.F.OPT.NFL-1"],
        "live_optic_market_ids": {"moneyline", "point_spread"},
    }
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert not skipped
    assert len(pins) == 1
    rules = pins[0]["rules"]
    books = {str(r["sportsbook"]) for r in rules}
    assert books == {"crypto.com", "optic"}
    crypto = next(r for r in rules if r["sportsbook"] == "crypto.com")
    assert crypto["canonical_market_type"] == "moneyline"
    optic = next(r for r in rules if r["sportsbook"] == "optic")
    assert optic["source_key"] == "moneyline"


def test_mlb_total_outs_spine_binds_player_outs() -> None:
    hit = spine_bind(
        league="mlb",
        book="crypto.com",
        source_key="Total Outs Recorded",
        live_ids={"player_outs", "player_strikeouts"},
        market_group=PLAYER_PROP,
    )
    assert hit is not None
    assert hit[0] == "player_outs"
    assert hit[1] == "player_outs"


def test_mlb_crypto_total_outs_python_wired_skips_harvest() -> None:
    store = _mlb_store()
    obs: MarketRuleObservation = {
        "league": "mlb",
        "sportsbook": "crypto.com",
        "source_key": "Total Outs Recorded",
        "source_key_type": "contract_type",
        "demand": 14,
        "market_group": PLAYER_PROP,
        "evidence_refs": ["gap:NX.F.OPT.MLB-1"],
        "live_optic_market_ids": {"player_outs", "player_strikeouts"},
    }
    _pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert skipped and skipped[0]["reason"] == "already_mapped"
    assert skipped[0].get("detail") == "player_outs"


def test_mlb_total_rbis_spine_binds_player_rbis() -> None:
    hit = spine_bind(
        league="mlb",
        book="crypto.com",
        source_key="Total RBIs",
        live_ids={"player_rbis", "player_hits"},
        market_group=PLAYER_PROP,
    )
    assert hit is not None
    assert hit[0] == "player_rbis"
    assert hit[1] == "player_rbis"


def test_mlb_crypto_total_rbis_drafts_via_tip_overlay() -> None:
    store = _mlb_store()
    obs: MarketRuleObservation = {
        "league": "mlb",
        "sportsbook": "crypto.com",
        "source_key": "Total RBIs",
        "source_key_type": "player_prop_contract_type",
        "demand": 9,
        "market_group": PLAYER_PROP,
        "evidence_refs": ["gap:NX.F.OPT.MLB-rbi"],
        "live_optic_market_ids": {"player_rbis", "player_hits"},
    }
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert not skipped
    assert len(pins) == 1
    rules = pins[0]["rules"]
    crypto = next(r for r in rules if r["sportsbook"] == "crypto.com")
    assert crypto["canonical_market_type"] == "player_rbis"
    assert crypto["source_key_type"] == "player_prop_contract_type"


def test_no_optic_canonical_when_ambiguous_live_ids() -> None:
    store = _store()
    obs: MarketRuleObservation = {
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Line",
        "source_key_type": "contract_type",
        "demand": 2,
        "market_group": GAME_LINE,
        "live_optic_market_ids": {"moneyline", "point_spread"},
    }
    _pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert skipped and skipped[0]["reason"] == "no_optic_canonical"
    assert skipped[0].get("candidates")


def test_needs_code_not_ai_eligible() -> None:
    store = _store()
    obs: MarketRuleObservation = {
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "player_sacks_taken",
        "source_key_type": "contract_type",
        "demand": 1,
        "market_group": GAME_LINE,
        "live_optic_market_ids": {"player_sacks_taken"},
    }
    _pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert skipped and skipped[0]["reason"] == "needs_code"
    added = append_ai_market_suggestions(
        store,
        skipped,
        [],
        set(),
        llm=FakeChatLLM(script=[ChatLLMResult(text='{"optic_id":"player_sacks_taken"}')]),
    )
    assert added == 0


def test_ai_market_pick_not_in_census_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    store = _store()
    skip = {
        "reason": "no_optic_canonical",
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": "1",
        "candidates": json.dumps(
            [{"id": "moneyline", "name": "moneyline"}],
            separators=(",", ":"),
        ),
    }
    llm = FakeChatLLM(script=[ChatLLMResult(text='{"optic_id":"invented_id"}')])
    added = append_ai_market_suggestions(store, [skip], [], set(), llm=llm)
    assert added == 0


def test_ai_market_suggestion_appended_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    store = _store()
    skip = {
        "reason": "no_optic_canonical",
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": "1",
        "candidates": json.dumps(
            [{"id": "moneyline", "name": "moneyline"}],
            separators=(",", ":"),
        ),
    }
    llm = FakeChatLLM(script=[ChatLLMResult(text='{"optic_id":"moneyline"}')])
    pins: list[dict[str, Any]] = []
    added = append_ai_market_suggestions(store, [skip], pins, set(), llm=llm)
    assert added == 1
    assert pins[0]["kind"] == "mapping_market_rules"
    assert is_ai_suggest_pin(pins[0])
    refs = pins[0]["evidence_refs"]
    assert AI_REF in refs
    assert AI_NOTE in refs
    assert "ai:skip:no_optic_canonical" in refs


class _BoomLLM:
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        _ = (messages, tools)
        raise AssertionError("llm must not run for an ineligible skip")


def test_kalshi_skip_is_never_ai_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    store = _wnba_store()
    skip = {
        "reason": "no_optic_canonical",
        "league": "wnba",
        "sportsbook": "kalshi",
        "source_key": "1QTOTAL",
        "source_key_type": "ticker_type",
        "demand": "2",
        "candidates": json.dumps(
            [{"id": "game_total", "name": "game_total"}],
            separators=(",", ":"),
        ),
    }
    pins: list[dict[str, Any]] = []
    added = append_ai_market_suggestions(store, [skip], pins, set(), llm=_BoomLLM())
    assert added == 0
    assert pins == []


def test_ai_market_abstain_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    store = _store()
    skip = {
        "reason": "no_optic_canonical",
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": "1",
        "candidates": json.dumps(
            [{"id": "moneyline", "name": "moneyline"}],
            separators=(",", ":"),
        ),
    }
    pins: list[dict[str, Any]] = []
    added = append_ai_market_suggestions(
        store,
        [skip],
        pins,
        set(),
        llm=FakeChatLLM(script=[ChatLLMResult(text='{"abstain":true}')]),
    )
    assert added == 0


def test_gap_suggest_zero_appends_no_market_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "0")
    store = _store()
    skip = {
        "reason": "no_optic_canonical",
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": "1",
        "candidates": json.dumps([{"id": "moneyline", "name": "moneyline"}]),
    }
    added = append_ai_market_suggestions(
        store,
        [skip],
        [],
        set(),
        llm=FakeChatLLM(script=[ChatLLMResult(text='{"optic_id":"moneyline"}')]),
    )
    assert added == 0


def test_harvest_skips_crypto_prop_contracts() -> None:
    store = _store()
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    items = [
        RfqGapItem(
            book="crypto",
            key="NX.F.OPT.NFL-1",
            demand=3,
            meta={
                "league": "nfl",
                "contract_type": "Anytime TD",
                "market_group": "Player Prop",
            },
        ),
    ]

    def catalogue(_symbol: str) -> dict[str, Any]:
        return {
            "contract_type": "Anytime TD",
            "market_type": "Player Prop",
            "league": "nfl",
        }

    harvest_missing_market_rules(
        store,
        items,
        pins,
        skipped,
        seen,
        fixtures_fn=_fixtures,
        catalogue_fn=catalogue,
    )
    assert not pins


def test_harvest_crypto_python_wired_player_and_team_prop() -> None:
    store = _store()
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    items = [
        RfqGapItem(
            book="crypto",
            key="NX.F.OPT.NFL-TD",
            demand=4,
            meta={
                "league": "nfl",
                "contract_type": "To Score a Touchdown",
                "market_group": "Player Prop",
            },
        ),
        RfqGapItem(
            book="crypto",
            key="NX.F.OPT.NFL-TT",
            demand=5,
            meta={
                "league": "nfl",
                "contract_type": "Total Points",
                "market_group": "Team Prop",
            },
        ),
    ]
    harvest_missing_market_rules(
        store,
        items,
        pins,
        skipped,
        seen,
        fixtures_fn=_fixtures,
    )
    assert not pins
    reasons = {(row.get("source_key"), row.get("reason")) for row in skipped}
    assert ("To Score a Touchdown", "already_mapped") in reasons
    assert ("Total Points", "already_mapped") in reasons
    team = next(row for row in skipped if row.get("source_key") == "Total Points")
    assert team.get("source_key_type") == "team_prop_contract_type"


def test_crypto_observation_includes_game_and_fight_prop() -> None:
    store = _store()
    items = [
        RfqGapItem(
            book="crypto",
            key="NX.F.OPT.NFL-1",
            demand=3,
            meta={
                "league": "nfl",
                "contract_type": "Both Teams To Score",
                "market_group": GAME_PROP,
            },
        ),
        RfqGapItem(
            book="crypto",
            key="NX.F.OPT.UFC-1",
            demand=2,
            meta={
                "league": "ufc",
                "contract_type": "Round of Victory",
                "market_group": FIGHT_PROP,
            },
        ),
    ]
    obs = _observations_from_inventory(
        store, items, fixtures_fn=_fixtures, catalogue_fn=None,
    )
    assert len(obs) == 2
    by_key = {row.get("source_key"): row for row in obs}
    assert by_key["Both Teams To Score"].get("market_group") == GAME_PROP
    assert by_key["Both Teams To Score"].get("source_key_type") == "game_prop_contract_type"
    assert by_key["Round of Victory"].get("market_group") == FIGHT_PROP
    assert by_key["Round of Victory"].get("source_key_type") == "game_prop_contract_type"


def test_empty_fixture_odds_does_not_fake_census() -> None:
    store = _store()
    obs: MarketRuleObservation = {
        "league": "nfl",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": 2,
        "market_group": GAME_LINE,
        "live_optic_market_ids": set(),
    }
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert not pins
    assert skipped and skipped[0]["reason"] == "no_optic_canonical"
    assert "candidates" not in skipped[0]


def test_census_falls_back_to_bigquery_when_fixtures_carry_no_odds() -> None:
    """/fixtures/active has no odds, so the live census must come from BQ."""
    store = _store()
    calls: list[list[str]] = []

    def census(optic_ids: list[str], _horizon: float) -> set[str]:
        calls.append(optic_ids)
        return {"moneyline"}

    ids = live_optic_census(
        store,
        "nfl",
        lambda *_a, **_k: [{"id": "fx1"}],
        census_fn=census,
    )
    assert ids == {"moneyline"}
    assert calls == [["nfl"]]


def test_census_prefers_fixture_odds_over_bigquery() -> None:
    store = _store()

    def census(_ids: list[str], _horizon: float) -> set[str]:
        raise AssertionError("BigQuery census must not run when odds are present")

    assert live_optic_census(store, "nfl", _fixtures, census_fn=census) == {
        "moneyline", "point_spread",
    }


def test_census_stays_offline_for_injected_fixtures() -> None:
    """Injected fixtures own the evidence — harvest tests never query BigQuery."""
    store = _store()
    assert live_optic_census(store, "nfl", lambda *_a, **_k: [{"id": "fx1"}]) == set()


def test_optic_rfq_is_not_demand() -> None:
    store = _store()
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    harvest_missing_market_rules(
        store,
        [RfqGapItem(book="optic", key="moneyline", demand=9)],
        pins,
        skipped,
        seen,
        fixtures_fn=_fixtures,
    )
    assert not pins


def test_harvest_poly_usa_never_pins_a_map_rule() -> None:
    store = _store()
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    items = [
        RfqGapItem(
            book="polymarket",
            key="tsc-nfl-sea-kc-2026-09-09-tt-sea-10pt5",
            demand=2,
            meta={
                "league": "nfl",
                "kind": "team_total",
                "platform": "polymarket_usa",
            },
        ),
    ]
    harvest_missing_market_rules(
        store,
        items,
        pins,
        skipped,
        seen,
        fixtures_fn=_fixtures,
    )
    # Poly US maps from its own enum table: a legacy kind is needs_code.
    assert not pins
    assert any(
        row.get("reason") == "needs_code" and row.get("source_key") == "team_total"
        for row in skipped
    )


def test_harvest_end_to_end_cart_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "0")
    store = _store()
    result = harvest_gap_pins(
        store,
        symbols=["NX.F.OPT.NFL-1"],
        inventory_fn=lambda: [
            RfqGapItem(
                book="crypto",
                key="NX.F.OPT.NFL-1",
                demand=2,
                meta={
                    "league": "nfl",
                    "contract_type": "Moneyline",
                    "market_group": GAME_LINE,
                },
            ),
        ],
        catalogue_fn=lambda _s: {
            "contract_type": "Moneyline",
            "market_type": GAME_LINE,
            "league": "nfl",
        },
        fixtures_fn=_fixtures,
    )
    market_pins = [p for p in result["pins"] if p.get("kind") == "mapping_market_rules"]
    assert market_pins
    cart_kinds = {item["kind"] for item in result["cart_items"]}
    assert "mapping_market_rules" in cart_kinds


def test_fight_line_harvest_uses_fight_line_group() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_ufc",
        entities=[],
        leagues=[
            LeagueRow(
                league="ufc",
                sport="combat",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "UFC",
                        "settings": {
                            "league": "UFC",
                            "sport_grouping": "MMA",
                            "period_type": "Full Fight",
                        },
                    },
                ],
            ),
        ],
        activate=True,
    )
    obs: MarketRuleObservation = {
        "league": "ufc",
        "sportsbook": "crypto.com",
        "source_key": "Moneyline",
        "source_key_type": "contract_type",
        "demand": 1,
        "market_group": FIGHT_LINE,
        "live_optic_market_ids": {"moneyline"},
    }
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    assert not skipped
    assert pins[0]["rules"][0]["canonical_market_type"] == "moneyline"


def test_unknown_novig_type_drafts_a_tip_ignore() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_nhl",
        entities=[],
        leagues=[
            LeagueRow(
                league="nhl", sport="hockey", optic_league_id="nhl",
                extra_optic_league_ids=[], fixture_source="api",
                fixture_horizon_hours=96.0, enabled=True, output_order=["moneyline"],
                exchanges=[{
                    "sportsbook": "novig", "enabled": True,
                    "source_league_id": "NHL", "settings": {"league": "NHL"},
                }],
            ),
        ],
        activate=True,
    )
    item = RfqGapItem("novig", "01a0f0ea-913b-7671-9937-c0dbccde6e11", 3, {
        "league_token": "NHL", "market_type": "PENALTY_MINUTES",
    })
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    harvest_missing_market_rules(store, [item], pins, skipped, set())
    assert not skipped
    rule = pins[0]["rules"][0]
    assert rule["sportsbook"] == "novig"
    assert rule["source_key"] == "PENALTY_MINUTES"
    assert rule["source_key_type"] == "market_type"
    assert rule["action"] == "ignore"
