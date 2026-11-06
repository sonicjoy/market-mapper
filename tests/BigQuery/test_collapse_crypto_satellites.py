"""Tests for collapse_crypto_satellites — pure transform, no BQ.

Satellites are the mapper's per-live-symbol crypto rows. Identity includes
source_ids.symbol, so distinct FIX Symbols for one canonical bet each keep
a row (RFQ joins on symbol). Same-symbol re-issues still collapse to max
source_ids.security_id. Only crypto.com rows collapse; duplicates on any
other sportsbook pass through so the pre-merge assertion still catches them.
"""

from BigQuery.load_mappings import collapse_crypto_satellites


def _row(*, sportsbook="crypto.com", side="CLE", security_id="1",
         symbol="SYM-1", market_type="moneyline", line=None,
         entity=None):
    return {
        "sport": "baseball",
        "league": "mlb",
        "start_date": "2026-07-18T17:10:00Z",
        "home": "CLE",
        "away": "PIT",
        "market_type": market_type,
        "entity": entity,
        "line": line,
        "side": side,
        "group_key": None,
        "sportsbook": sportsbook,
        "source_ids": {"security_id": security_id, "symbol": symbol},
    }


def test_collapses_same_symbol_to_max_security_id():
    """True re-list: same FIX Symbol, newer SecurityID wins."""
    stale = _row(security_id="202607170000001D", symbol="M.O.1.2")
    fresh = _row(security_id="202607180000009D", symbol="M.O.1.2")
    rows, n = collapse_crypto_satellites([stale, fresh])
    assert n == 1
    assert rows == [fresh]


def test_distinct_live_symbols_survive():
    """MLB twin contracts (To Get A Hit Yes vs Hits Milestones Over 0.5)
    share the canonical key but RFQ on different symbols — both load."""
    yes_hit = _row(
        security_id="202607300000001D", symbol="M.O.1.93",
        market_type="player_hits", entity="nick_gonzales",
        line=0.5, side="over",
    )
    milestone = _row(
        security_id="202607300000099D", symbol="M.O.1.306",
        market_type="player_hits", entity="nick_gonzales",
        line=0.5, side="over",
    )
    rows, n = collapse_crypto_satellites([yes_hit, milestone])
    assert n == 0
    assert rows == [yes_hit, milestone]


def test_winner_keeps_first_position_regardless_of_order():
    fresh = _row(security_id="202607180000009D", symbol="M.O.1.2")
    stale = _row(security_id="202607170000001D", symbol="M.O.1.2")
    other = _row(side="PIT", security_id="3", symbol="M.O.1.3")
    rows, n = collapse_crypto_satellites([fresh, other, stale])
    assert n == 1
    assert rows == [fresh, other]


def test_distinct_keys_untouched():
    a = _row(side="CLE", symbol="M.O.1.1")
    b = _row(side="PIT", symbol="M.O.1.2")
    c = _row(market_type="point_spread", line=1.5, symbol="M.O.1.3")
    rows, n = collapse_crypto_satellites([a, b, c])
    assert n == 0
    assert rows == [a, b, c]


def test_non_crypto_duplicates_pass_through():
    """Kalshi/PX duplicate keys mean a pipeline bug, not a re-list;
    they must survive so the loader's pre-merge assertion fires."""
    a = _row(sportsbook="Kalshi", security_id="1", symbol="x")
    b = _row(sportsbook="Kalshi", security_id="2", symbol="y")
    rows, n = collapse_crypto_satellites([a, b])
    assert n == 0
    assert rows == [a, b]


def test_mixed_sportsbooks_preserve_order():
    kalshi = _row(sportsbook="Kalshi", symbol="k")
    stale = _row(security_id="1", symbol="M.O.1.2")
    px = _row(sportsbook="Prophet X", symbol="p")
    fresh = _row(security_id="9", symbol="M.O.1.2")
    rows, n = collapse_crypto_satellites([kalshi, stale, px, fresh])
    assert n == 1
    assert rows == [kalshi, fresh, px]


def test_missing_security_id_does_not_raise():
    """Malformed/partial source_ids must not abort the load."""
    incomplete = _row(security_id="1", symbol="M.O.1.2")
    incomplete["source_ids"] = {"symbol": "M.O.1.2"}
    complete = _row(security_id="9", symbol="M.O.1.2")
    rows, n = collapse_crypto_satellites([incomplete, complete])
    assert n == 1
    assert rows == [complete]

    rows2, n2 = collapse_crypto_satellites([complete, incomplete])
    assert n2 == 1
    assert rows2 == [complete]
