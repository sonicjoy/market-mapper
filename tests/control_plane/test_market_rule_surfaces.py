"""The same card text on cart, Rules, Approve, and verify previews."""

from __future__ import annotations

from mappers.control_plane.change_view import _fmt_rule_mod
from mappers.control_plane.console_rules_query import _market_rule_rows
from mappers.control_plane.gap_fix import _cart_item
from mappers.control_plane.models import MarketRuleEntryRequest
from mappers.control_plane.rows import MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import InMemoryStore


def _row(**kwargs: object) -> MarketRuleRow:
    base: dict[str, object] = {
        "rule_id": "mr",
        "league": "ufc",
        "sportsbook": "polymarket_usa",
        "rule_kind": "taxonomy",
        "source_key_type": "ticker_suffix",
        "source_key": "rof-before-r",
        "action": "map",
        "canonical_market_type": "total_rounds",
        "priority": 100,
        "enabled": True,
        "confidence": "manual",
    }
    base.update(kwargs)
    return MarketRuleRow(**base)  # type: ignore[arg-type]


def test_cart_label_uses_the_card() -> None:
    item = _cart_item({
        "kind": "mapping_market_rules",
        "league": "ufc",
        "rules": [{
            "sportsbook": "polymarket_usa",
            "rule_kind": "taxonomy",
            "source_key_type": "ticker_suffix",
            "source_key": "rof-before-r",
            "action": "map",
            "canonical_market_type": "total_rounds",
            "line_offset": -0.5,
            "yes_side": "under",
        }],
        "evidence_refs": ["polymarket_usa:ticker:aec-ufc-ryagan-ozzdia-2026-09-19-rof-before-r5"],
    })
    assert item["label"] == (
        "Polymarket US rof-before-r → total_rounds · offset -0.5 · yes_side under"
    )


def test_rules_row_prints_none_and_unset() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S",
        entities=[],
        leagues=[],
        market_rules=[_row()],
        activate=True,
    )
    rows = _market_rule_rows(store, "S", "")
    assert rows[0]["offset_text"] == "none"
    assert rows[0]["yes_side_text"] == "unset"
    assert rows[0]["side_swap_text"] == "none"
    assert "offset none" in rows[0]["transform"]


def test_served_only_amend_prints_the_transform() -> None:
    parent = _row()
    child = _row(rule_id="mr2", line_offset=-0.5, yes_side="under")
    line = _fmt_rule_mod(parent, child)
    assert "mapped as total_rounds → mapped as total_rounds" not in line
    assert "offset none · yes_side unset · side_swap none" in line
    assert "offset -0.5 · yes_side under · side_swap none" in line


def test_editor_verify_preview_includes_the_card() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S", entities=[], leagues=[], market_rules=[], activate=True)
    service = ProposalService(store)
    verified = service.entry_market_rule_verify(MarketRuleEntryRequest.model_validate({
        "league": "ufc",
        "sportsbook": "polymarket_usa",
        "source_key_type": "ticker_suffix",
        "source_key": "rof-before-r",
        "action": "map",
        "canonical_market_type": "total_rounds",
        "line_offset": -0.5,
        "yes_side": "under",
        "acknowledge_shadow": True,
    }))
    cards = verified["preview"]["cards"]
    assert cards[0]["transform"] == "offset -0.5 · yes_side under · side_swap none"
