"""RFQ platform registry for gap harvest inventory."""

from __future__ import annotations

from mappers.control_plane.rfq_platforms import (
    is_known_mapping_failure_platform,
    sql_crypto_platform_predicate,
    sql_unknown_platform_predicate,
)


def test_crypto_predicate_includes_inplay() -> None:
    pred = sql_crypto_platform_predicate("r")
    assert "cryptocom-inplay" in pred
    assert "cryptocom" in pred


def test_unknown_predicate_excludes_polymarket_family() -> None:
    pred = sql_unknown_platform_predicate("r")
    assert "polymarket%" in pred
    assert "'novig'" in pred


def test_known_platform_classifier() -> None:
    assert is_known_mapping_failure_platform("cryptocom-inplay")
    assert is_known_mapping_failure_platform("polymarket_us")
    assert is_known_mapping_failure_platform("underdog")
    # DraftKings Exchange writes ``draftkings``; ``dkex`` is only the book id.
    assert is_known_mapping_failure_platform("draftkings")
    assert is_known_mapping_failure_platform("draftkings-inplay")
    assert not is_known_mapping_failure_platform("dkex")
    assert is_known_mapping_failure_platform("underdog-inplay")
    assert is_known_mapping_failure_platform("prophetx-inplay")
    assert is_known_mapping_failure_platform("huddle")
    assert not is_known_mapping_failure_platform("some_new_book")
