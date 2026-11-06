"""Console side of the market_mapping override lane (crypto.com / Polymarket (USA)); no BQ, no Pub/Sub."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from BigQuery.override_lane import LANE_ENV, LANE_POLYUSA_ENV
from mappers.control_plane import console_override_lane as lane
from mappers.control_plane.console_override_jobs import create_job, get_job, run_override_job
from mappers.control_plane.console_override_ops import _override_message_from_body, _resolved_override_body
from mappers.control_plane.models import ValidationFailedError

SYMBOL = "NX.F.OPT.UNL-00008-260925-M.O.1.1.20261230"


def _body(**extra: Any) -> dict[str, Any]:
    return {
        "game_id": "30547-41571-2026-09-25",
        "market_id": "moneyline",
        "sportsbook": "crypto.com",
        "selection": "Cyprus",
        "source_market_id": SYMBOL,
        "source_selection_id": "",
        "grouping_key": "default",
        "reason": "wrong side",
        **extra,
    }


@pytest.fixture
def lane_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LANE_ENV, "1")


def test_lane_off_keeps_ticker_shaped_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LANE_ENV, raising=False)
    assert not lane.lane_venue("crypto.com")
    msg = _override_message_from_body(_body(), active=True)
    assert json.loads(msg["source_ids"]) == {"market_id": SYMBOL, "selection_id": ""}


def test_lane_on_crypto_message_is_symbol_keyed(lane_on: None) -> None:
    msg = _override_message_from_body(_body(), active=True)
    assert json.loads(msg["source_ids"]) == {"symbol": SYMBOL}
    assert msg["sportsbook"] == "crypto.com"


def test_lane_on_rejects_non_symbol_crypto_key(lane_on: None) -> None:
    with pytest.raises(ValidationFailedError, match="FIX symbol"):
        _override_message_from_body(_body(source_market_id="CFB-00017-260926-M-SPD.NPO"), active=True)


def test_lane_on_usa_needs_side(lane_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LANE_POLYUSA_ENV, "1")
    body = _body(sportsbook="Polymarket (USA)", source_market_id="aec-cs2-sta-baks-2026-09-25", selection="STATE")
    with pytest.raises(ValidationFailedError, match="'yes' or 'no'"):
        _override_message_from_body(body, active=True)
    msg = _override_message_from_body({**body, "source_selection_id": "YES"}, active=True)
    assert json.loads(msg["source_ids"]) == {"market_id": "aec-cs2-sta-baks-2026-09-25", "selection_id": "yes"}


def test_lane_leaves_other_books_alone(lane_on: None) -> None:
    msg = _override_message_from_body(
        _body(sportsbook="Kalshi", source_market_id="KX-1", source_selection_id="yes"), active=True
    )
    assert json.loads(msg["source_ids"]) == {"market_id": "KX-1", "selection_id": "yes"}


def test_lane_resolve_skips_opticodds_lookup(lane_on: None) -> None:
    with patch("mappers.control_plane.console_override_ops.lookup_rfq_key") as lookup:
        out = _resolved_override_body(_body(source_market_id=f" {SYMBOL} "), client=object(), project="p")  # type: ignore[arg-type]
    lookup.assert_not_called()
    assert out["source_market_id"] == SYMBOL


def test_lookup_lane_key_reads_market_mapping() -> None:
    row = {
        "game_id": "g",
        "selection": "Draw",
        "market_match_method": "override",
        "source_ids": json.dumps({"symbol": SYMBOL}),
    }
    captured: dict[str, Any] = {}

    def fake_ro_query(_client: Any, sql: str, **kwargs: Any) -> list[Any]:
        captured["sql"] = sql
        captured["params"] = {p.name: p.value for p in kwargs["job_config"].query_parameters}
        return [type("R", (), {"items": lambda _self: row.items()})()]

    with patch("mappers.control_plane.console_override_lane.ro_query", fake_ro_query):
        out = lane.lookup_lane_key(
            object(),  # type: ignore[arg-type]
            sportsbook="crypto.com",
            source_market_id=SYMBOL,
            source_selection_id="",
            project="rs-marketmaking",
        )
    assert "markets_us.market_mapping" in captured["sql"]
    assert "'$.symbol'" in captured["sql"]
    assert captured["params"] == {"sportsbook": "crypto.com", "venue_key": SYMBOL}
    assert out["winner"]["selection"] == "Draw"
    assert out["winner"]["is_mapping_override"] is True
    assert "next mapping pipeline run" in out["lookup_note"]


def test_lane_job_stops_after_sink_and_says_when(lane_on: None) -> None:
    job = create_job(active=True, sportsbook="crypto.com", source_market_id=SYMBOL, source_selection_id="")
    message = _override_message_from_body(_body(), active=True)
    lookup_hit = {"winner": None, "candidates": [], "candidate_count": 0}
    with (
        patch("mappers.control_plane.console_override_jobs.wait_for_override_sink"),
        patch("mappers.control_plane.console_override_jobs.start_prices_state_merge") as merge,
        patch("mappers.control_plane.console_override_jobs.run_fold_rank") as rank,
        patch("mappers.control_plane.console_override_jobs.lookup_lane_key", return_value=lookup_hit),
        patch("mappers.control_plane.console_override_jobs.bigquery.Client"),
    ):
        run_override_job(job.job_id, project="p", message=message, operator="op", reason="r")
    merge.assert_not_called()
    rank.assert_not_called()
    finished = get_job(job.job_id)
    assert finished is not None
    assert finished.status == "accepted_not_materialised"
    assert "15 min" in finished.message
    assert finished.steps["lane"].startswith("market_mapping")


def test_polymarket_usa_is_not_a_lane_venue_without_its_flag(lane_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LANE_POLYUSA_ENV, raising=False)
    assert lane.lane_venue("crypto.com")
    assert not lane.lane_venue("Polymarket (USA)")
