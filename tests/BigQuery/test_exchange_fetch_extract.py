"""Key extraction for exchange_fetch_raw load jobs."""

import json

from BigQuery.exchange_fetch_extract import (
    crypto_keys,
    kalshi_keys,
    novig_keys,
    optic_keys,
    polymarket_keys,
    polymarket_usa_keys,
    polymarket_usa_side_ids,
    px_event_keys,
    px_market_keys,
)
from BigQuery.exchange_fetch_snapshot import (
    fetch_time_from_dir,
    snapshot_id_from_dir,
)


def test_optic_keys():
    line = json.dumps({
        "id": "game-1",
        "league": {"id": "nba"},
    })
    assert optic_keys(line) == ("nba", "game-1")


def test_kalshi_keys():
    line = json.dumps({"event_ticker": "KXNBA-26FEB26LALBOS", "sport": "basketball"})
    assert kalshi_keys(line) == ("basketball", "KXNBA-26FEB26LALBOS")
    # No series is ever cut off the ticker: without a typed sport the key is null.
    bare = json.dumps({"event_ticker": "KXNBA-26FEB26LALBOS"})
    assert kalshi_keys(bare) == (None, "KXNBA-26FEB26LALBOS")


def test_polymarket_keys():
    line = json.dumps({"slug": "nba-lakers-celtics", "condition_id": "0xabc"})
    assert polymarket_keys(line) == ("nba", "0xabc")


def test_polymarket_usa_keys():
    line = json.dumps({
        "league_id": 1, "event_ticker": "nfl-sea-kc-2026-09-09",
        "slug": "tsc-nfl-sea-kc-2026-09-09-tt-sea-10pt5",
        "sides": [{"id": "11", "long": True}, {"id": "12", "long": False}],
    })
    assert polymarket_usa_keys(line) == (
        "1", "nfl-sea-kc-2026-09-09", "tsc-nfl-sea-kc-2026-09-09-tt-sea-10pt5",
    )
    assert polymarket_usa_side_ids(line) == ["11", "12"]


def test_crypto_keys():
    line = json.dumps({"league": "NBA"})
    assert crypto_keys(line) == "NBA"


def test_novig_keys():
    line = json.dumps({"league": "nba"})
    assert novig_keys(line, "events") == "nba"


def test_px_event_keys():
    line = json.dumps({"tournament_id": "t1", "id": "e9"})
    assert px_event_keys(line) == ("t1", "e9")


def test_px_market_keys():
    line = json.dumps({"tournament_id": "t1", "market_id": "m3"})
    assert px_market_keys(line) == ("t1", "m3")


def test_snapshot_id_from_dir():
    data_dir = __import__("pathlib").Path("data/2026-08-19/10_35")
    assert snapshot_id_from_dir(data_dir) == "2026-08-19T10:35"
    fts = fetch_time_from_dir(data_dir)
    assert fts.isoformat().startswith("2026-08-19T10:35")


def test_load_wraps_poly_usa_one_row_per_side():
    import io

    from BigQuery.load_exchange_fetch import _wrap_poly_usa

    line = json.dumps({
        "league_id": 5, "event_ticker": "mlb-pit-det-2026-09-26",
        "slug": "asc-mlb-pit-det-2026-09-26-pos-2pt5",
        "sides": [{"id": "1", "long": True}, {"id": "2", "long": False}],
    })
    buf = io.BytesIO()
    _wrap_poly_usa(buf, line, "2026-09-26T12_00", "2026-09-26T12:00:00Z")
    rows = [json.loads(r) for r in buf.getvalue().decode().splitlines()]
    assert [r["market_side_id"] for r in rows] == ["1", "2"]
    assert {r["inner_league"] for r in rows} == {"5"}
    assert {r["market_id"] for r in rows} == {"asc-mlb-pit-det-2026-09-26-pos-2pt5"}
    assert {r["event_ticker"] for r in rows} == {"mlb-pit-det-2026-09-26"}
    assert all(r["data"] == line for r in rows)
    assert set(rows[0]) == {
        "snapshot_id", "fetch_time", "inner_league", "event_ticker",
        "market_id", "market_side_id", "data",
    }
