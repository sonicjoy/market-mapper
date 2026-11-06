"""Optic is_live gates live emit and insert-only load (not start_date)."""

from __future__ import annotations

from typing import Any

from mappers.pipeline import canonical_row_to_json
from mappers.shared import CanonicalRow


def _row(**kw: Any) -> CanonicalRow:
    base: dict[str, Any] = {
        "league": "nba",
        "start_date": "2026-08-20T00:00:00Z",
        "home": "AAA",
        "away": "BBB",
        "market_type": "moneyline",
        "side": "AAA",
    }
    base.update(kw)
    return CanonicalRow(**base)


def test_canonical_row_optic_is_live_defaults_false():
    assert _row().optic_is_live is False


def test_canonical_row_to_json_carries_optic_is_live():
    j = canonical_row_to_json(_row(optic_is_live=True), {}, {})
    assert j["optic_is_live"] is True
    j_pre = canonical_row_to_json(_row(), {}, {})
    assert j_pre["optic_is_live"] is False


def test_canonical_row_to_json_crypto_satellite_only_when_set():
    j = canonical_row_to_json(_row(), {}, {})
    assert "crypto_satellite" not in j
    j_sat = canonical_row_to_json(_row(crypto_satellite=True), {}, {})
    assert j_sat["crypto_satellite"] is True
