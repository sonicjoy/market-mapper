"""Tests for Optic crypto.com market_id → FIX Symbol decode."""

from mappers.exchanges.crypto_optic import (
    CatalogueEntry,
    candidate_symbols,
    decode_market_id,
    prefer_candidate_stamp,
    stamp_from_optic_odds,
)
from mappers.exchanges.optic import Odd
from mappers.shared import CanonicalRow


def test_candidate_symbols_total_example():
    oid = "MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO"
    cands = candidate_symbols(oid)
    assert "NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130" in cands
    assert "NX.F.OPT.MLB-00001-260727-M.O.13.9.20261130" in cands


def test_decode_requires_unique_catalogue_hit():
    oid = "MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO"
    catalogue = {
        "NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130": CatalogueEntry(
            symbol="NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130",
            security_id="SEC139",
            publish_time="2026-07-26T14:27:00Z",
        ),
    }
    decoded = decode_market_id(oid, catalogue)
    assert decoded is not None
    assert decoded.symbol.endswith(".O.1.39.20261130")
    assert decoded.security_id == "SEC139"
    assert decoded.market_id == oid


def test_decode_ambiguous_returns_none():
    oid = "MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO"
    catalogue = {
        "NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130": CatalogueEntry(
            symbol="NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130",
            security_id="A",
        ),
        "NX.F.OPT.MLB-00001-260727-M.O.13.9.20261130": CatalogueEntry(
            symbol="NX.F.OPT.MLB-00001-260727-M.O.13.9.20261130",
            security_id="B",
        ),
    }
    assert decode_market_id(oid, catalogue) is None


def test_decode_missing_or_malformed_returns_none():
    assert decode_market_id(None, {}) is None
    assert decode_market_id("", {}) is None
    assert decode_market_id("not-an-id", {}) is None


def test_stamp_from_optic_odds_sets_fix_fields():
    oid = "MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO"
    symbol = "NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130"
    catalogue = {
        symbol: CatalogueEntry(
            symbol=symbol, security_id="SEC139", publish_time="2026-07-26T00:00:00Z",
        ),
    }
    # timestamp is feed-only (Odd.extra=allow); construct via validate.
    odd = Odd.model_validate({
        "id": "odd-1",
        "market_id": "total_runs",
        "grouping_key": "default",
        "source_ids": {"crypto.com": {"market_id": oid}},
        "timestamp": 1_700_000_000.0,
    })
    row = CanonicalRow(
        league="mlb",
        start_date="2026-07-27T23:00:00Z",
        home="TEX",
        away="SEA",
        market_type="game_total",
        side="over",
        line=11.5,
        optic_id="odd-1",
    )
    stats = stamp_from_optic_odds(
        [row], {"odd-1": odd}, catalogue, league="mlb",
    )
    assert stats["stamped"] == 1
    assert row.crypto_symbol == symbol
    assert row.crypto_security_id == "SEC139"
    assert row.crypto_market_id == oid
    assert row.crypto_source_ts == 1_700_000_000.0


def test_prefer_candidate_stamp_latest_wins():
    assert prefer_candidate_stamp(2.0, 1.0) is True
    assert prefer_candidate_stamp(1.0, 2.0) is False
    assert prefer_candidate_stamp(None, 1.0) is None
    assert prefer_candidate_stamp(1.0, 1.0) is None
