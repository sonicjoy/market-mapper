"""Suffix specificity and the vocab-dict delete gate."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.seed.vocab_flip_gate import missing_vocab_keys
from mappers.vocab.combat_usa import _suffix_rule


def _row(**kwargs: object) -> SimpleNamespace:
    base = {
        "enabled": True,
        "tombstone": False,
        "sportsbook": "polymarket_usa",
        "source_key_type": "ticker_suffix",
        "action": "map",
        "priority": 100,
        "match_operator": "prefix",
        "league": "ufc",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_suffix_rule_prefers_the_longer_key_then_priority() -> None:
    short = _row(source_key="rof-before-r", priority=1)
    exact = _row(source_key="rof-before-r5", match_operator="exact", priority=200)
    prefix = _row(source_key="ro", priority=40)
    suffix = _row(source_key="r5", match_operator="suffix", priority=10)
    assert _suffix_rule("rof-before-r5", [short, exact]) is exact
    assert _suffix_rule("rof-before-r5", [prefix, suffix]) is suffix


def test_missing_vocab_keys_requires_every_file_key() -> None:
    rules = [
        _row(sportsbook="kalshi", source_key_type="ticker_type", source_key="GAME"),
        _row(
            sportsbook="kalshi", source_key_type="ticker_type",
            source_key="SPREAD", action="ignore",
        ),
        _row(
            sportsbook="kalshi", source_key_type="ticker_type",
            source_key="TOTAL", tombstone=True,
        ),
        _row(sportsbook="optic", source_key_type="ticker_type", source_key="TOTAL"),
    ]
    missing = missing_vocab_keys(
        ["GAME", "SPREAD", "TOTAL"],
        rules,
        sportsbook="kalshi",
        source_key_type="ticker_type",
        league="ufc",
    )
    assert missing == ["TOTAL"]
    assert missing_vocab_keys(
        ["GAME", "SPREAD"],
        rules,
        sportsbook="kalshi",
        source_key_type="ticker_type",
        league="ufc",
    ) == []
