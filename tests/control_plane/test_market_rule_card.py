"""Worked examples for the one market-rule card."""

from __future__ import annotations

from mappers.control_plane.dry_run_market_rules import apply_market_rules_payload
from mappers.control_plane.market_rule_card import (
    attach_already_mapped_context,
    market_rule_card,
    notes_with_example,
    payload_from_market_pin,
)
from mappers.control_plane.market_rule_evidence import evidence_by_source_key
from mappers.control_plane.models import MarketRulePin
from mappers.control_plane.rows import MarketRuleRow

_KALSHI = "KXUFCROUNDS-26SEP28-5"
_TDS = "astatc-nfl-phi-chi-2026-09-28-tds-4pt5"


def test_evidence_split_prefers_the_longest_source_key() -> None:
    ncaaf = [
        "kalshi:series:KXNCAAFSPREAD",
        "spine:kalshi_ticker_types:SPREAD",
        "optic:market_id:point_spread",
        "kalshi:series:KXNCAAF1HSPREAD",
        "spine:kalshi_ticker_types:1HSPREAD",
        "optic:market_id:1st_half_point_spread",
        "kalshi:series:KXNCAAFTEAMTOTAL",
        "spine:kalshi_ticker_types:TEAMTOTAL",
        "optic:market_id:team_total",
        "kalshi:series:KXNCAAFTOTAL",
        "spine:kalshi_ticker_types:TOTAL",
        "optic:market_id:total_points",
    ]
    owned = evidence_by_source_key(
        ncaaf, ["SPREAD", "1HSPREAD", "TOTAL", "TEAMTOTAL", "GAME", "1H"],
    )
    assert owned["SPREAD"] == ncaaf[:3]
    assert owned["1HSPREAD"] == ncaaf[3:6]
    assert owned["TEAMTOTAL"] == ncaaf[6:9]
    assert owned["TOTAL"] == ncaaf[9:]
    assert owned["GAME"] == []
    assert owned["1H"] == []
    mlb = evidence_by_source_key(
        [
            "kalshi:series:KXMLBHR",
            "spine:kalshi_ticker_types:HR",
            "optic:market_id:player_home_runs",
            "kalshi:series:KXMLBHRR",
            "spine:kalshi_ticker_types:HRR",
            "optic:market_id:player_hits_+_runs_+_rbis",
        ],
        ["HR", "HRR"],
    )
    assert [ref.rsplit(":", 1)[-1] for ref in mlb["HR"]] == ["KXMLBHR", "HR", "player_home_runs"]
    assert mlb["HRR"][-1].endswith("rbis")
    assert "KXMLBHRR" not in " ".join(mlb["HR"])
    single = evidence_by_source_key(
        ["ai:ref:suggest", "ai:skip:no_optic_canonical"],
        ["1HSPREAD"],
    )
    assert single["1HSPREAD"] == ["ai:ref:suggest", "ai:skip:no_optic_canonical"]


def test_rof_before_rounds_card_matches_the_worked_example() -> None:
    ticker = "aec-ufc-ryagan-ozzdia-2026-09-19-rof-before-r5"
    card = market_rule_card(
        {
            "sportsbook": "polymarket_usa",
            "source_key": "rof-before-r",
            "source_key_type": "ticker_suffix",
            "match_operator": "prefix",
            "action": "map",
            "canonical_market_type": "total_rounds",
            "line_offset": -0.5,
            "yes_side": "under",
        },
        league="ufc",
        evidence_refs=[f"polymarket_usa:ticker:{ticker}", "polymarket_usa:line:5"],
    )
    assert card["venue"] == f"Polymarket US rof-before-r · example {ticker} · line 5"
    assert card["transform"] == "offset -0.5 · yes_side under · side_swap none"
    assert card["optic"] == (
        "total_rounds · example line 4.5 · side under (rule covers rof-before-r…)"
    )
    assert card["label"] == (
        "Polymarket US rof-before-r → total_rounds · offset -0.5 · yes_side under"
    )


def test_polymarket_touchdowns_card_prints_none_and_unset() -> None:
    card = market_rule_card(
        {
            "sportsbook": "polymarket_usa",
            "source_key": "football_game_total_touchdowns",
            "action": "map",
            "canonical_market_type": "total_touchdowns",
        },
        league="nfl",
        evidence_refs=[
            f"polymarket_usa:ticker:{_TDS}",
            "polymarket_usa:line:4.5",
        ],
    )
    assert card["venue"] == (
        f"Polymarket US football_game_total_touchdowns · example {_TDS} · line 4.5"
    )
    assert card["transform"] == "offset none · yes_side unset · side_swap none"
    assert "example line 4.5 · side unset" in card["optic"]
    assert "rule covers tds-0pt5, 2pt5, 4pt5" in card["optic"]


def test_ncaaf_card_marks_the_nfl_example_slug() -> None:
    card = market_rule_card(
        {
            "sportsbook": "polymarket_usa",
            "source_key": "football_game_total_touchdowns",
            "action": "map",
            "canonical_market_type": "total_touchdowns",
        },
        league="ncaaf",
        evidence_refs=[f"polymarket_usa:ticker:{_TDS}", "polymarket_usa:line:4.5"],
    )
    assert "NFL slug; no ncaaf slug in hand" in card["venue"]


def test_side_swap_flips_the_resulting_side() -> None:
    card = market_rule_card(
        {
            "sportsbook": "kalshi",
            "source_key": "ROUNDS",
            "action": "map",
            "canonical_market_type": "total_rounds",
            "line_offset": -0.5,
            "yes_side": "under",
            "side_swap": True,
        },
        league="ufc",
        evidence_refs=[f"kalshi:market_ticker:{_KALSHI}"],
    )
    assert "yes_side under · side_swap yes" in card["transform"]
    assert "side over" in card["optic"]


def test_notes_keep_the_trader_note_and_the_example() -> None:
    notes = notes_with_example(
        "trader note",
        _KALSHI,
        mark=None,
    )
    assert notes is not None
    assert notes.startswith("trader note")
    assert f"example: {_KALSHI}" in notes
    assert "before Round 5" not in notes
    again = notes_with_example(notes, _KALSHI)
    assert again == notes


def test_already_mapped_context_is_not_an_approvable_row() -> None:
    tip = MarketRuleRow(
        rule_id="mr-rounds",
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
        line_offset=-0.5,
        yes_side="under",
    )

    class _Store:
        current_rule_set_id = "S"

        def market_rules_for(self, rid: str) -> list[MarketRuleRow]:
            assert rid == "S"
            return [tip]

    real = MarketRulePin(
        sportsbook="kalshi",
        rule_kind="taxonomy",
        source_key_type="ticker_type",
        source_key="MOV",
        action="ignore",
    ).model_dump(mode="json")
    pins = [{"league": "ufc", "rules": [real], "evidence_refs": []}]
    skipped = [{
        "reason": "already_mapped",
        "league": "ufc",
        "sportsbook": "kalshi",
        "source_key_type": "ticker_type",
        "source_key": "ROUNDS",
        "detail": "total_rounds",
    }]
    attach_already_mapped_context(_Store(), pins, skipped)
    assert pins[0]["rules"] == [real]
    payload = payload_from_market_pin(pins[0])
    assert [pin.source_key for pin in payload.context_rules] == ["ROUNDS"]
    assert payload.context_rules[0].line_offset == -0.5
    applied = apply_market_rules_payload([], payload)
    assert [row.source_key for row in applied] == ["MOV"]


def test_already_mapped_without_a_pin_is_not_a_second_proposal() -> None:
    pins: list[dict] = []
    skipped = [{
        "reason": "already_mapped",
        "league": "ufc",
        "sportsbook": "crypto.com",
        "source_key_type": "contract_type",
        "source_key": "Round of Finish",
        "detail": "round_betting",
    }]
    attach_already_mapped_context(object(), pins, skipped)
    assert pins == []
