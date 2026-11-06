"""Transient upstream failures in fetch.optic.get_optic."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch import optic  # noqa: E402

_TRANSIENT = (
    requests.exceptions.ConnectionError("reset"),
    requests.exceptions.Timeout("timed out"),
    requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
)


def _ok_page() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"id": "fx1"}], "has_more": False}
    resp.raise_for_status = MagicMock()
    return resp


def test_get_optic_passes_timeout():
    with patch("fetch.optic.requests.get", return_value=_ok_page()) as mock_get:
        optic.get_optic("https://example.test/fixtures", headers={})
    assert mock_get.call_args.kwargs["timeout"] == optic.GET_TIMEOUT


@pytest.mark.parametrize("exc", _TRANSIENT)
def test_get_optic_retries_transient_then_succeeds(exc):
    ok = _ok_page()
    with (
        patch(
            "fetch.optic.requests.get",
            side_effect=[exc, ok],
        ) as mock_get,
        patch("fetch.optic.sleep") as mock_sleep,
    ):
        rows = optic.get_optic("https://example.test/fixtures", headers={})
    assert rows == [{"id": "fx1"}]
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(2)


@pytest.mark.parametrize("exc", _TRANSIENT)
def test_get_optic_raises_after_persistent_transients(exc):
    with (
        patch("fetch.optic.requests.get", side_effect=exc),
        patch("fetch.optic.sleep"),
        pytest.raises(type(exc)),
    ):
        optic.get_optic("https://example.test/fixtures", headers={})


def _err_page(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    err = requests.exceptions.HTTPError(
        f"{status} Server Error", response=resp)
    resp.raise_for_status.side_effect = err
    return resp


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_get_optic_retries_http_then_succeeds(status):
    ok = _ok_page()
    with (
        patch(
            "fetch.optic.requests.get",
            side_effect=[_err_page(status), ok],
        ) as mock_get,
        patch("fetch.optic.sleep") as mock_sleep,
    ):
        rows = optic.get_optic("https://example.test/fixtures", headers={})
    assert rows == [{"id": "fx1"}]
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(2)


def test_get_optic_raises_after_persistent_500():
    with (
        patch("fetch.optic.requests.get", return_value=_err_page(500)),
        patch("fetch.optic.sleep"),
        pytest.raises(requests.exceptions.HTTPError),
    ):
        optic.get_optic("https://example.test/fixtures", headers={})


def test_get_optic_does_not_retry_401():
    with (
        patch(
            "fetch.optic.requests.get", return_value=_err_page(401),
        ) as mock_get,
        pytest.raises(requests.exceptions.HTTPError),
    ):
        optic.get_optic("https://example.test/fixtures", headers={})
    assert mock_get.call_count == 1


def test_get_fixtures_or_skip_returns_none_on_500():
    resp = MagicMock()
    resp.status_code = 500
    err = requests.exceptions.HTTPError("500 Server Error", response=resp)
    with patch("fetch.optic.get_fixtures", side_effect=err):
        assert optic.get_fixtures_or_skip({}, "sweden_-_damallsvenskan") is None


def test_get_fixtures_or_skip_returns_none_on_chunked_encoding():
    err = requests.exceptions.ChunkedEncodingError(
        "Response ended prematurely")
    with patch("fetch.optic.get_fixtures", side_effect=err):
        assert optic.get_fixtures_or_skip({}, "nba") is None


def test_get_fixtures_or_skip_reraises_401():
    resp = MagicMock()
    resp.status_code = 401
    err = requests.exceptions.HTTPError("401", response=resp)
    with (
        patch("fetch.optic.get_fixtures", side_effect=err),
        pytest.raises(requests.exceptions.HTTPError),
    ):
        optic.get_fixtures_or_skip({}, "sweden_-_damallsvenskan")


def test_fetch_processed_fixture_skips_500():
    resp = MagicMock()
    resp.status_code = 500
    err = requests.exceptions.HTTPError("500 Server Error", response=resp)
    with patch("fetch.optic.get_fixture_odds", side_effect=err):
        assert optic.fetch_processed_fixture({}, {"id": "fx1"}) is None


def test_fetch_processed_fixture_skips_chunked_encoding():
    err = requests.exceptions.ChunkedEncodingError(
        "Response ended prematurely")
    with patch("fetch.optic.get_fixture_odds", side_effect=err):
        assert optic.fetch_processed_fixture({}, {"id": "fx1"}) is None


def test_fetch_processed_fixture_reraises_401():
    resp = MagicMock()
    resp.status_code = 401
    err = requests.exceptions.HTTPError("401", response=resp)
    with (
        patch("fetch.optic.get_fixture_odds", side_effect=err),
        pytest.raises(requests.exceptions.HTTPError),
    ):
        optic.fetch_processed_fixture({}, {"id": "fx1"})
