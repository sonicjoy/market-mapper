"""Tests for post-merge Optic agreement checks (missing > wrong)."""

from mappers.exchanges.crypto_optic import CatalogueEntry
from mappers.exchanges.optic import Odd
from mappers.exchanges.optic_verify import verify_against_optic
from mappers.pipeline import row_key
from mappers.shared import CanonicalRow


def _ml_row(
    *,
    side: str = "TYB",
    optic_id: str = "odd-home",
    crypto_security_id: str | None = None,
    crypto_symbol: str | None = None,
    crypto_market_id: str | None = None,
) -> CanonicalRow:
    return CanonicalRow(
        league="ufc",
        start_date="2026-08-01T00:00:00Z",
        home="TYB",
        away="RAK",
        market_type="moneyline",
        side=side,
        optic_id=optic_id,
        crypto_security_id=crypto_security_id,
        crypto_symbol=crypto_symbol,
        crypto_market_id=crypto_market_id,
    )


def test_side_mismatch_drops_row():
    row = _ml_row(side="RAK")  # claims away, optic odd is home fighter
    odd = Odd(
        id="odd-home",
        market_id="moneyline",
        grouping_key="default",
        team_id="t-home",
        selection="Marcin Tybura",
    )
    idx = {row_key(row): row}
    rows = [row]
    stats = verify_against_optic(
        idx, rows, {"odd-home": odd},
        team_maps={"odd-home": {"t-home": "TYB", "t-away": "RAK"}},
        crypto_catalogue=None,
        kalshi_tickers=frozenset(),
    )
    assert stats.side_dropped == 1
    assert idx == {}
    assert rows == []


def test_crypto_security_id_mismatch_strips_crypto():
    oid = (
        "UFC-00001-260801-M-MLHome-O11_261130-2300_1_PM.NPO"
    )
    symbol = "NX.F.OPT.UFC-00001-260801-M.O.1.1.20261130"
    catalogue = {
        symbol: CatalogueEntry(
            symbol=symbol, security_id="OPTIC-SID", publish_time="1",
        ),
    }
    row = _ml_row(
        crypto_security_id="WRONG-SID",
        crypto_symbol=symbol,
        crypto_market_id=oid,
    )
    odd = Odd(
        id="odd-home",
        market_id="moneyline",
        grouping_key="default",
        team_id="t-home",
        source_ids={"crypto.com": {"market_id": oid}},
    )
    idx = {row_key(row): row}
    rows = [row]
    stats = verify_against_optic(
        idx, rows, {"odd-home": odd},
        team_maps={"odd-home": {"t-home": "TYB", "t-away": "RAK"}},
        crypto_catalogue=catalogue,
        kalshi_tickers=frozenset(),
    )
    assert stats.crypto_stripped == 1
    assert row.crypto_security_id is None
    assert row.optic_id == "odd-home"  # optic row kept; only crypto gone


def test_agreeing_crypto_kept():
    oid = (
        "UFC-00001-260801-M-MLHome-O11_261130-2300_1_PM.NPO"
    )
    symbol = "NX.F.OPT.UFC-00001-260801-M.O.1.1.20261130"
    catalogue = {
        symbol: CatalogueEntry(
            symbol=symbol, security_id="OPTIC-SID", publish_time="1",
        ),
    }
    row = _ml_row(
        crypto_security_id="OPTIC-SID",
        crypto_symbol=symbol,
        crypto_market_id=oid,
    )
    odd = Odd(
        id="odd-home",
        market_id="moneyline",
        grouping_key="default",
        team_id="t-home",
        source_ids={"crypto.com": {"market_id": oid}},
    )
    idx = {row_key(row): row}
    rows = [row]
    stats = verify_against_optic(
        idx, rows, {"odd-home": odd},
        team_maps={"odd-home": {"t-home": "TYB", "t-away": "RAK"}},
        crypto_catalogue=catalogue,
        kalshi_tickers=frozenset(),
    )
    assert stats.crypto_stripped == 0
    assert row.crypto_security_id == "OPTIC-SID"
