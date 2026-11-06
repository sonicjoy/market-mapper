"""Tests for optic.verify_source_ids Kalshi cross-check."""

import pytest

from mappers.exchanges.optic import Odd, verify_source_ids
from mappers.pipeline import row_key
from mappers.shared import CanonicalRow

OPTIC_ID = "22409-17875-2026-06-16:1st_half_moneyline:senegal"


def _wc_row(
    *,
    optic_id: str,
    kalshi_ticker: str,
    side: str = "SEN",
) -> CanonicalRow:
    return CanonicalRow(
        league="world_cup",
        start_date="2026-06-16T19:00:00Z",
        home="FRA",
        away="SEN",
        market_type="1h_winner_3way",
        side=side,
        kalshi_ticker=kalshi_ticker,
        kalshi_scope="1H",
        kalshi_side="yes",
        optic_id=optic_id,
    )


def _odd(cited: str) -> Odd:
    return Odd(
        id=OPTIC_ID,
        market_id="1st_half_moneyline",
        normalized_selection="Senegal",
        grouping_key="default",
        source_ids={"Kalshi": {"market_id": cited, "selection_id": "yes"}},
    )


def _pair() -> tuple[CanonicalRow, CanonicalRow]:
    row = _wc_row(optic_id=OPTIC_ID, kalshi_ticker="KXWC1H-26JUN16FRASEN-SEN")
    france_row = _wc_row(
        optic_id="22409-17875-2026-06-16:1st_half_moneyline:france",
        kalshi_ticker="KXWC1H-26JUN16FRASEN-FRA",
        side="FRA",
    )
    return row, france_row


def test_kalshi_cited_ticker_not_in_open_book_is_stale(capsys):
    """Optic citing a ticker Kalshi no longer lists keeps ours."""
    row = _wc_row(optic_id=OPTIC_ID, kalshi_ticker="KXWC1H-26JUN16FRASEN-SEN")
    stats = verify_source_ids(
        {row_key(row): row},
        {OPTIC_ID: _odd("KXWC1H-26JUN13FRASEN-SEN")},
        kalshi_tickers=frozenset({"KXWC1H-26JUN16FRASEN-SEN"}),
    )
    assert row.kalshi_ticker == "KXWC1H-26JUN16FRASEN-SEN"
    assert "not in Kalshi's open book" in capsys.readouterr().err
    assert stats is not None


def test_kalshi_listed_mismatch_strips_kalshi(capsys):
    """A cited ticker Kalshi still lists that disagrees strips ours (missing > wrong)."""
    row, france_row = _pair()
    verify_source_ids(
        {row_key(row): row, row_key(france_row): france_row},
        {OPTIC_ID: _odd("KXWC1H-26JUN16FRASEN-FRA")},
        kalshi_tickers=frozenset(
            {"KXWC1H-26JUN16FRASEN-SEN", "KXWC1H-26JUN16FRASEN-FRA"},
        ),
    )
    assert row.kalshi_ticker is None
    assert row.kalshi_scope is None
    assert france_row.kalshi_ticker == "KXWC1H-26JUN16FRASEN-FRA"
    assert "stripping Kalshi" in capsys.readouterr().err


def test_kalshi_listed_mismatch_raise_mode():
    """on_mismatch='raise' keeps historical hard-fail behaviour."""
    row, france_row = _pair()
    with pytest.raises(ValueError, match="source_ids mismatch"):
        verify_source_ids(
            {row_key(row): row, row_key(france_row): france_row},
            {OPTIC_ID: _odd("KXWC1H-26JUN16FRASEN-FRA")},
            kalshi_tickers=frozenset(
                {"KXWC1H-26JUN16FRASEN-SEN", "KXWC1H-26JUN16FRASEN-FRA"},
            ),
            on_mismatch="raise",
        )
