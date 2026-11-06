"""Tests for fetch/runshop.py."""

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from fetch import runshop, runshop_db


def _json_response(payload: list[dict]) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _http_error(code: int, body: bytes = b"nope") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://betbuilder/api", code, "err", None, io.BytesIO(body),  # type: ignore[arg-type]
    )


def test_get_json_retries_transient_url_error():
    prices = [{"txOddsFixtureID": 905827989}]
    responses = [
        urllib.error.URLError("connection reset"),
        _json_response(prices),
    ]
    with patch.object(
        runshop.urllib.request, "urlopen", side_effect=responses,
    ) as mock_open, patch.object(runshop.time, "sleep") as mock_sleep:
        assert runshop._get_json("http://betbuilder/api", {}, 5) == prices

    assert mock_open.call_count == 2
    assert mock_sleep.call_count == 1


def test_get_json_raises_runtime_error_after_persistent_url_error():
    error = urllib.error.URLError("connection reset")
    with patch.object(
        runshop.urllib.request, "urlopen", side_effect=error,
    ) as mock_open, patch.object(runshop.time, "sleep"), pytest.raises(
        RuntimeError, match="betbuilder API connectivity failed",
    ):
        runshop._get_json("http://betbuilder/api", {}, 5)

    assert mock_open.call_count == runshop._FETCH_RETRIES


def test_get_json_raises_http_failed_after_persistent_503():
    with patch.object(
        runshop.urllib.request, "urlopen", side_effect=_http_error(503),
    ) as mock_open, patch.object(runshop.time, "sleep"), pytest.raises(
        RuntimeError, match="betbuilder API HTTP failed after",
    ):
        runshop._get_json("http://betbuilder/api", {}, 5)

    assert mock_open.call_count == runshop._FETCH_RETRIES


def test_get_json_retries_http_503():
    prices = [{"txOddsFixtureID": 905827989}]
    responses = [_http_error(503), _json_response(prices)]
    with patch.object(
        runshop.urllib.request, "urlopen", side_effect=responses,
    ), patch.object(runshop.time, "sleep"):
        assert runshop._get_json("http://betbuilder/api", {}, 5) == prices


def test_get_json_does_not_retry_http_401():
    with patch.object(
        runshop.urllib.request, "urlopen", side_effect=_http_error(401, b"bad key"),
    ) as mock_open, patch.object(runshop.time, "sleep"), pytest.raises(
        RuntimeError, match="HTTP 401: bad key",
    ):
        runshop._get_json("http://betbuilder/api", {}, 5)

    assert mock_open.call_count == 1


def test_extract_fixture_ids_deduplicates_and_sorts():
    prices = [
        {"txOddsFixtureID": 905828017, "marketIds": [1, 2]},
        {"txOddsFixtureID": 905827989, "marketIds": [3, 4]},
        {"txOddsFixtureID": 905828017, "marketIds": [5, 6]},
    ]
    assert runshop.extract_fixture_ids(prices) == [905827989, 905828017]


def test_build_chain_records_skips_unmapped_legacy():
    tx_rows = [(905827989, 905827989), (999, 888)]
    legacy_to_poly = {905827989: "90086996"}
    events: dict[str, tuple[str | None, str | None]] = {
        "90086996": ("Canada vs. Morocco", "2026-07-04T17:00:00+00:00"),
    }
    records = runshop.build_chain_records(tx_rows, legacy_to_poly, events)
    assert len(records) == 1
    assert records[0]["tx_odds_fixture_id"] == 905827989
    assert records[0]["poly_title"] == "Canada vs. Morocco"


def test_fetch_betbuilder_fixture_ids_from_prices():
    prices = [{"txOddsFixtureID": 905827989, "marketIds": [3, 629]}]
    assert runshop.fetch_betbuilder_fixture_ids(prices=prices) == [905827989]


def test_fetch_tx_legacy_by_fixture_ids_skips_null_legacy():
    class FakeTxCon:
        def run(self, _sql: str):
            return [(905827989, 905827989), (999, None)]

    out = runshop_db.fetch_tx_legacy_by_fixture_ids(
        FakeTxCon(),  # type: ignore[arg-type]
        [905827989, 999],
    )
    assert out == {905827989: 905827989}


def test_fetch_fixture_chain_continues_when_tx_db_unavailable():
    legacy_to_poly = {905827989: "90086996"}
    events: dict[str, tuple[str | None, str | None]] = {
        "90086996": ("Canada vs. Morocco", "2026-07-04T17:00:00+00:00"),
    }

    class FakePolyCon:
        def close(self) -> None:
            pass

    with patch.object(runshop, "_load_secret", return_value="pw"), patch.object(
        runshop, "_load_tx_legacy_map", return_value={},
    ), patch.object(
        runshop, "connect_poly", return_value=FakePolyCon(),
    ), patch.object(
        runshop, "fetch_poly_by_legacy_ids", return_value=legacy_to_poly,
    ), patch.object(
        runshop, "fetch_events", return_value=events,
    ):
        records, stats = runshop.fetch_fixture_chain(
            api_fixture_ids=[905827989],
        )

    assert stats["tx_rows_resolved"] == 0
    assert stats["chain_rows"] == 1
    assert records[0]["tx_legacy_fixture_id"] == 905827989


def test_fetch_fixture_chain_enriches_from_dbs():
    tx_rows = [(905827989, 905827989)]
    legacy_to_poly = {905827989: "90086996"}
    events: dict[str, tuple[str | None, str | None]] = {
        "90086996": ("Canada vs. Morocco", "2026-07-04T17:00:00+00:00"),
    }

    class FakePolyCon:
        def close(self) -> None:
            pass

    with patch.object(runshop, "_load_secret", return_value="pw"), patch.object(
        runshop, "_load_tx_legacy_map", return_value={905827989: 905827989},
    ), patch.object(
        runshop, "connect_poly", return_value=FakePolyCon(),
    ), patch.object(
        runshop, "fetch_poly_by_legacy_ids", return_value=legacy_to_poly,
    ), patch.object(
        runshop, "fetch_events", return_value=events,
    ):
        records, stats = runshop.fetch_fixture_chain(
            api_fixture_ids=[905827989],
        )

    assert stats == {
        "api_fixtures": 1,
        "chain_rows": 1,
        "tx_rows_resolved": 1,
    }
    assert records == runshop.build_chain_records(
        tx_rows, legacy_to_poly, events,
    )


def test_filter_prices_by_fixture_ids():
    prices = [
        {"txOddsFixtureID": 905827989, "id": 1},
        {"txOddsFixtureID": 905828017, "id": 2},
        {"txOddsFixtureID": 905827989, "id": 3},
    ]
    filtered = runshop.filter_prices_by_fixture_ids(prices, {905827989})
    assert [row["id"] for row in filtered] == [1, 3]


def test_write_prices_writes_verbatim_jsonl(tmp_path: Path):
    prices = [
        {
            "id": 2655276840,
            "txOddsFixtureID": 905827989,
            "updateTimeStamp": "2026-07-03T10:43:08.099056Z",
            "marketIds": [3, 629],
            "modelId": 224,
            "price": 8.213923470122,
            "metadataId": 51189316,
        },
    ]
    out = tmp_path / runshop.PRICES_FILENAME
    runshop.write_prices(out, prices)
    assert json.loads(out.read_text(encoding="utf-8").strip()) == prices[0]


def test_main_writes_prices_and_chain_from_single_snapshot(tmp_path: Path):
    prices = [
        {
            "id": 1,
            "txOddsFixtureID": 905827989,
            "updateTimeStamp": "2026-07-03T10:43:08.099056Z",
            "marketIds": [3, 629],
            "modelId": 224,
            "price": 1.5,
            "metadataId": 51189316,
        },
        {
            "id": 2,
            "txOddsFixtureID": 905828017,
            "updateTimeStamp": "2026-07-03T10:43:08.099056Z",
            "marketIds": [3, 631],
            "modelId": 224,
            "price": 2.5,
            "metadataId": 51189317,
        },
    ]
    chain = [{
        "tx_odds_fixture_id": 905827989,
        "tx_legacy_fixture_id": 905827989,
        "poly_game_id": "90086996",
        "poly_title": "Canada vs. Morocco",
        "poly_start_time": "2026-07-04T17:00:00+00:00",
    }]

    with patch.object(
        runshop, "fetch_betbuilder_prices", return_value=prices,
    ), patch.object(
        runshop, "fetch_fixture_chain", return_value=(chain, {
            "api_fixtures": 1,
            "chain_rows": 1,
            "tx_rows_resolved": 1,
        }),
    ) as mock_chain, patch.object(sys, "argv", [
        "runshop",
        "--league", "world_cup",
        "--out-dir", str(tmp_path),
        "--max-items", "1",
    ]):
        runshop.main()

    mock_chain.assert_called_once_with(api_fixture_ids=[905827989])

    prices_path = tmp_path / runshop.PRICES_FILENAME
    chain_path = tmp_path / runshop.CHAIN_FILENAME
    assert prices_path.exists()
    assert chain_path.exists()

    written_prices = [
        json.loads(line)
        for line in prices_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(written_prices) == 1
    assert written_prices[0]["txOddsFixtureID"] == 905827989

    written_chain = json.loads(chain_path.read_text(encoding="utf-8").strip())
    assert written_chain["tx_odds_fixture_id"] == 905827989


def test_main_logs_reachable_when_model_returns_no_prices(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    with patch.object(
        runshop, "fetch_betbuilder_prices", return_value=[],
    ), patch.object(
        runshop, "fetch_fixture_chain", return_value=([], {
            "api_fixtures": 0,
            "chain_rows": 0,
            "tx_rows_resolved": 0,
        }),
    ), patch.object(sys, "argv", [
        "runshop",
        "--league", "world_cup",
        "--out-dir", str(tmp_path),
    ]):
        runshop.main()

    err = capsys.readouterr().err
    assert "betbuilder reachable" in err
    assert "returned 0 prices" in err
    assert (tmp_path / runshop.PRICES_FILENAME).exists()


def test_write_chain_creates_parent_dirs(tmp_path: Path):
    out = tmp_path / "nested" / runshop.CHAIN_FILENAME
    runshop.write_chain(out, [{
        "tx_odds_fixture_id": 1,
        "tx_legacy_fixture_id": 10,
        "poly_game_id": "100",
        "poly_title": None,
        "poly_start_time": None,
    }])
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("{")
