"""Tests for Coverage published stamp shaping."""

from __future__ import annotations

from mappers.control_plane.console_coverage_stamps import (
    coverage_stamp_row,
    format_stamp_source_id,
)


def test_format_stamp_source_id_kalshi() -> None:
    assert format_stamp_source_id(
        "Kalshi",
        {"market_id": "KXNFLGAME-SEA", "selection_id": "yes"},
    ) == "KXNFLGAME-SEA"


def test_format_stamp_source_id_crypto_and_px() -> None:
    assert format_stamp_source_id("crypto.com", {"symbol": "NX.F.OPT.NFL"}) == "NX.F.OPT.NFL"
    assert (
        format_stamp_source_id("px", {"event_id": "44821", "line_id": "90112"})
        == "44821 / 90112"
    )
    assert (
        format_stamp_source_id(
            "Prophet X",
            {"event_id": "44821", "line_id": "90112"},
        )
        == "44821 / 90112"
    )


def test_coverage_stamp_row_prefers_selection() -> None:
    row = coverage_stamp_row(
        {
            "sportsbook": "Kalshi",
            "market_type": "moneyline",
            "market_id": "moneyline",
            "entity": "sea",
            "selection": "Seattle Seahawks",
            "line": None,
            "points": 3.5,
            "side": "yes",
            "selection_line": None,
            "source_ids": {"market_id": "KX-SEA"},
            "last_updated": "2026-09-09T06:12:00Z",
        }
    )
    assert row["entity"] == "Seattle Seahawks"
    assert row["line"] == "3.5"
    assert row["source_id"] == "KX-SEA"
    assert row["contract_side"] == ""
    assert row["sportsbook"] == "kalshi"
    assert row["sportsbook_label"] == "Kalshi"


def test_coverage_stamp_row_exposes_kalshi_no_side() -> None:
    row = coverage_stamp_row(
        {
            "sportsbook": "Kalshi",
            "market_type": "moneyline",
            "market_id": "moneyline",
            "selection": "Kansas City Chiefs",
            "side": "KC",
            "source_ids": {
                "market_id": "KXNFLGAME-26SEP27KCMIA-MIA",
                "selection_id": "no",
            },
        }
    )
    assert row["side"] == "KC"
    assert row["contract_side"] == "no"
    assert row["source_id"] == "KXNFLGAME-26SEP27KCMIA-MIA"


def test_coverage_stamp_row_ignores_token_selection_id() -> None:
    row = coverage_stamp_row(
        {
            "sportsbook": "Polymarket",
            "market_type": "moneyline",
            "market_id": "moneyline",
            "selection": "Miami Dolphins",
            "side": "MIA",
            "source_ids": {"selection_id": "123456789"},
        }
    )
    assert row["contract_side"] == ""
    assert row["source_id"] == "123456789"
