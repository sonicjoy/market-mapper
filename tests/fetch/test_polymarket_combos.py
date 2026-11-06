"""Tests for fetch/polymarket_combos.py -- combo-leg catalog pagination."""

from unittest.mock import MagicMock, patch

from fetch import polymarket_combos as combos


def _fake_response(markets: list[dict], next_cursor: str | None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"markets": markets, "next_cursor": next_cursor}
    return resp


def test_fetch_combo_markets_pages_past_the_old_10000_cap():
    """The old default (max_pages=200, limit=50) hard-capped the catalog at
    exactly 10,000 markets even when the API had more pages to give -- the real
    combo-leg catalog exceeds that (43,131 condition_ids observed against prod).
    fetch_combo_markets must keep paging until the API itself reports no
    next_cursor, not stop because an arbitrary page count was reached.
    """
    total_pages = 300  # 300 * 50 = 15,000 markets -- more than the old 10,000 cap
    pages = [
        _fake_response(
            markets=[{"condition_id": f"0x{p}-{i}"} for i in range(50)],
            next_cursor=str(p + 1) if p + 1 < total_pages else None,
        )
        for p in range(total_pages)
    ]
    with patch("fetch.polymarket_combos.requests.get", side_effect=pages) as mock_get:
        markets = combos.fetch_combo_markets()
    assert len(markets) == total_pages * 50
    assert mock_get.call_count == total_pages


def test_fetch_combo_markets_has_no_default_page_cap():
    """No default budget at all -- paginate until the API itself runs out of pages.
    Any numeric default (even a generous one) risks silently truncating upcoming
    markets, since the catalog is sorted by volume, not date. The job's own
    activeDeadlineSeconds is the real backstop, not a page count in this loop."""
    total_pages = 5001  # one past the previous generous-but-still-a-cap default
    pages = [
        _fake_response(
            markets=[{"condition_id": f"0x{p}-{i}"} for i in range(50)],
            next_cursor=str(p + 1) if p + 1 < total_pages else None,
        )
        for p in range(total_pages)
    ]
    with patch("fetch.polymarket_combos.requests.get", side_effect=pages) as mock_get:
        markets = combos.fetch_combo_markets()
    assert len(markets) == total_pages * 50
    assert mock_get.call_count == total_pages


def test_fetch_combo_markets_warns_when_page_cap_is_hit(capsys):
    """If the page cap is ever hit while the API still has more pages (cursor
    still set), that must be loud, not a silent truncation -- the bug that
    dropped ~33k condition_ids from prod produced no error and no log line."""
    pages = [
        _fake_response(markets=[{"condition_id": f"0x{p}"}], next_cursor=str(p + 1))
        for p in range(5)
    ]
    with patch("fetch.polymarket_combos.requests.get", side_effect=pages):
        markets = combos.fetch_combo_markets(max_pages=5)
    assert len(markets) == 5
    err = capsys.readouterr().err
    assert "max_pages" in err and "5" in err
