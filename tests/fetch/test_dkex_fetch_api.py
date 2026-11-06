"""DKEX API fetch batching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fetch.dkex import fetch_api


@patch("fetch.dkex._api_key")
@patch("fetch.dkex.fetch_market_metadata")
@patch("fetch.dkex.page_market_tickers")
def test_fetch_api_skips_secret_when_unset(
    page: MagicMock,
    metadata: MagicMock,
    api_key: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DKEX_API_KEY", raising=False)
    monkeypatch.delenv("DKEX_USE_API_KEY_SECRET", raising=False)
    monkeypatch.setenv("DKEX_API_BASE", "https://example.test")
    page.return_value = ["NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"]
    metadata.return_value = []
    fetch_api(("active",), with_combos=False)
    api_key.assert_not_called()


@patch("fetch.dkex.fetch_market_metadata")
@patch("fetch.dkex.page_market_tickers")
def test_fetch_api_sends_every_listed_ticker_to_the_batch(
    page: MagicMock,
    metadata: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DKEX_API_BASE", "https://example.test")
    page.return_value = [
        "NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024",
        "COMBO-12783464979703431470",
    ]
    metadata.return_value = []
    fetch_api(("active",), with_combos=False)
    metadata.assert_called_once()
    batch = metadata.call_args[0][2]
    # No ticker is filtered by its shape; the venue drops non-singles.
    assert batch == ["NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024", "COMBO-12783464979703431470"]


@patch("fetch.dkex.fetch_combo_metadata")
@patch("fetch.dkex.page_combos")
@patch("fetch.dkex.fetch_market_metadata")
@patch("fetch.dkex.page_market_tickers")
def test_fetch_api_loads_combo_legs(
    page: MagicMock,
    metadata: MagicMock,
    combos: MagicMock,
    combo_meta: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DKEX_API_BASE", "https://example.test")
    page.return_value = ["NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"]
    combos.return_value = (
        [],
        ["COMBO-12783464979703431470"],
    )
    metadata.return_value = [{"ticker": page.return_value[0]}]
    combo_meta.return_value = [{
        "ticker": "COMBO-12783464979703431470",
        "legs": [{"ticker": page.return_value[0], "side": "yes"}],
    }]
    rows = fetch_api(("active",), with_combos=True)
    metadata.assert_called_once()
    assert metadata.call_args[0][2] == page.return_value
    combo_meta.assert_called_once()
    combo = next(r for r in rows if str(r.get("ticker", "")).startswith("COMBO-"))
    assert combo["legs"][0]["ticker"] == page.return_value[0]


def _resp(status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.text = ""
    return r


def _fake_session(
    missing: list[str], singles: dict[str, MagicMock]
) -> MagicMock:
    s = MagicMock()
    s.headers = {}
    s.post.return_value = _resp(200, {"markets": [], "missingTickers": missing})
    s.get.side_effect = lambda url, **kw: singles.get(
        url.rsplit("/", 1)[-1], _resp(404)
    )
    return s


def _run(monkeypatch: pytest.MonkeyPatch, flag: str | None, session: MagicMock):
    monkeypatch.setenv("DKEX_API_BASE", "https://example.test")
    if flag is None:
        monkeypatch.delenv("DKEX_MISSING_SINGLE_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("DKEX_MISSING_SINGLE_FALLBACK", flag)
    with patch("fetch.dkex._session", return_value=session), patch(
        "fetch.dkex.page_market_tickers", return_value=["A", "B"]
    ):
        return fetch_api(("active",), with_combos=False)


def test_missing_fallback_off_makes_no_single_gets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_session(["A"], {"A": _resp(200, {"market": {"ticker": "A"}})})
    assert _run(monkeypatch, None, session) == []
    session.get.assert_not_called()


def test_missing_fallback_recovers_and_skips_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_session(
        ["A", "COMBO-1"], {"A": _resp(200, {"market": {"ticker": "A"}})}
    )
    assert _run(monkeypatch, "1", session) == [{"ticker": "A"}]
    assert session.get.call_count == 2


def test_missing_fallback_honours_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fetch.dkex.MISSING_FALLBACK_CAP", 2)
    names = ["A", "B", "C"]
    session = _fake_session(
        names, {n: _resp(200, {"market": {"ticker": n}}) for n in names}
    )
    rows = _run(monkeypatch, "1", session)
    assert [r["ticker"] for r in rows] == ["A", "B"]
    assert session.get.call_count == 2
