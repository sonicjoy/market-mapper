"""Console catalog lookup + override orchestration (Release 068 G5)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.console_oom_catalog import (
    _matching_candidates,
    _row_to_dict,
    _winner_from_candidates,
    _winner_in_rank_window,
    assess_materialisation,
    lookup_rfq_key,
    preflight_fixture_materialisation,
)
from mappers.control_plane.console_override_jobs import create_job, get_job, run_override_job
from mappers.control_plane.console_override_publish import build_console_override_message
from mappers.control_plane.console_override_sink import wait_for_override_sink
from mappers.control_plane.console_sportsbook import canonical_sportsbook
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.spa_static import is_spa_document_path
from mappers.control_plane.store import InMemoryStore


def _client(control: ProposalService) -> TestClient:
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(gcp_project="marketmaking-test")
    return TestClient(app)


def test_winner_in_rank_window_from_chosen_row() -> None:
    winner = {"in_rank_window": False}
    assert _winner_in_rank_window([winner], winner) is False
    assert _winner_in_rank_window([], None) is None
    assert _winner_in_rank_window([{"in_rank_window": True}], None) is True


def test_winner_from_candidates_single_unstamped_row() -> None:
    row = {
        "src_market_id": "KX",
        "is_rfq_winner": None,
        "in_rank_window": False,
    }
    assert _winner_from_candidates([row]) is row


def test_winner_from_candidates_rejects_false_only_row() -> None:
    row = {
        "src_market_id": "KX",
        "is_rfq_winner": False,
        "in_rank_window": True,
    }
    assert _winner_from_candidates([row]) is None


def test_winner_from_candidates_prefers_in_window_stamp() -> None:
    stale = {
        "src_market_id": "KX",
        "is_rfq_winner": True,
        "in_rank_window": False,
    }
    fresh = {
        "src_market_id": "KX",
        "is_rfq_winner": True,
        "in_rank_window": True,
        "rank_class": "override",
    }
    assert _winner_from_candidates([stale, fresh]) is fresh


def test_lookup_rfq_key_strips_source_ids() -> None:
    client = MagicMock()
    with patch("mappers.control_plane.console_oom_catalog._query_lookup_rows", return_value=[]):
        hit = lookup_rfq_key(
            client,
            sportsbook="kalshi",
            source_market_id="  KXMISSING  ",
            source_selection_id=" yes ",
            project="marketmaking-test",
        )
    assert hit["source_market_id"] == "KXMISSING"
    assert hit["source_selection_id"] == "yes"
    assert hit["resolved_source_market_id"] == "KXMISSING"
    assert hit["resolved_source_selection_id"] == "yes"
    assert hit["rfq_key"] == "kalshi|KXMISSING|yes"


def test_build_console_override_message_normalises_sportsbook() -> None:
    msg = build_console_override_message(
        game_id="g1",
        market_id="m1",
        sportsbook="kalshi",
        selection="Team A",
        source_market_id="KXTEST-YES",
        source_selection_id="yes",
    )
    assert msg["sportsbook"] == "Kalshi"
    assert msg["active"] is True
    assert "mapping_source" not in msg


def test_build_console_override_message_includes_mapping_source_when_set() -> None:
    msg = build_console_override_message(
        game_id="g1",
        market_id="m1",
        sportsbook="Kalshi",
        selection="Team A",
        source_market_id="KXTEST-YES",
        source_selection_id="yes",
        mapping_source="HENRY",
    )
    assert msg["mapping_source"] == "HENRY"


def test_polymarket_usa_canonicalisation() -> None:
    assert canonical_sportsbook("polymarket (usa)") == "Polymarket (USA)"


def test_assess_materialisation_active_requires_override_winner() -> None:
    candidates = [
        {
            "src_market_id": "KX",
            "src_selection_id": "yes",
            "is_rfq_winner": True,
            "rank_class": "greg",
            "in_rank_window": True,
        }
    ]
    reason = assess_materialisation(
        candidates=candidates,
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=True,
    )
    assert reason == "override accepted; override winner not stamped yet"

    candidates[0]["rank_class"] = "override"
    assert assess_materialisation(
        candidates=candidates,
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=True,
    ) is None


def test_assess_materialisation_deactivate_requires_candidates() -> None:
    assert assess_materialisation(
        candidates=[],
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=False,
    ) == "no opticodds_mapping row for this RFQ key yet"


def test_assess_materialisation_deactivate_rejects_override_winner() -> None:
    candidates = [
        {
            "src_market_id": "KX",
            "src_selection_id": "yes",
            "is_rfq_winner": True,
            "rank_class": "override",
            "in_rank_window": True,
        }
    ]
    assert assess_materialisation(
        candidates=candidates,
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=False,
    ) == "deactivate accepted; override still winning"


def test_assess_materialisation_ignores_outside_rank_window_for_deactivate() -> None:
    candidates = [
        {
            "src_market_id": "KX",
            "src_selection_id": "yes",
            "is_rfq_winner": None,
            "rank_class": None,
            "in_rank_window": False,
        }
    ]
    reason = assess_materialisation(
        candidates=candidates,
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=False,
    )
    assert reason is not None
    assert "outside live rank window" in reason
    assert "deactivate accepted" in reason


def test_assess_materialisation_active_outside_rank_window_stale_row() -> None:
    candidates = [
        {
            "src_market_id": "KX",
            "src_selection_id": "yes",
            "is_rfq_winner": None,
            "in_rank_window": False,
        }
    ]
    reason = assess_materialisation(
        candidates=candidates,
        expected_source_market_id="KX",
        expected_source_selection_id="yes",
        active=True,
    )
    assert reason is not None
    assert "outside live rank window" in reason
    assert "override accepted" in reason


def test_preflight_fixture_materialisation_missing_fixture() -> None:
    client = MagicMock()
    with patch(
        "mappers.control_plane.console_oom_catalog.ro_query",
        return_value=[],
    ):
        reason = preflight_fixture_materialisation(client, "marketmaking-test", "missing-game")
    assert reason is not None
    assert "no fixture" in reason


def test_lookup_rfq_key_falls_back_to_stale_window() -> None:
    client = MagicMock()
    row = MagicMock(
        items=lambda: [
            ("game_id", "g1"),
            ("src_market_id", "KX"),
            ("src_selection_id", "Yes"),
            ("is_rfq_winner", None),
            ("in_rank_window", False),
        ]
    )
    converted = _row_to_dict(row)
    with patch(
        "mappers.control_plane.console_oom_catalog._query_lookup_rows",
        side_effect=[[], [converted]],
    ) as query_rows:
        hit = lookup_rfq_key(
            client,
            sportsbook="kalshi",
            source_market_id="KX",
            source_selection_id="yes",
            project="marketmaking-test",
        )
    assert query_rows.call_count == 2
    assert query_rows.call_args_list[1].kwargs["min_last_updated_days"] == 365
    assert hit["winner"] is not None
    assert hit["resolved_source_selection_id"] == "Yes"


def test_matching_candidates_ignore_source_id_case() -> None:
    rows = [{"src_market_id": "KXTEST", "src_selection_id": "Yes"}]
    assert _matching_candidates(rows, "kxtest", "yes") == rows


def test_lookup_rfq_key_returns_stamped_winner() -> None:
    client = MagicMock()
    row = MagicMock(
        items=lambda: [
            ("game_id", "g1"),
            ("sportsbook", "Kalshi"),
            ("src_market_id", "KX"),
            ("src_selection_id", "Yes"),
            ("is_rfq_winner", True),
            ("rank_class", "override"),
            ("mapping_source", "ORIGINAL"),
            ("in_rank_window", True),
            ("source_ids", {"market_id": "KX", "selection_id": "Yes"}),
        ]
    )
    with patch(
        "mappers.control_plane.console_oom_catalog._query_lookup_rows",
        return_value=[_row_to_dict(row)],
    ):
        hit = lookup_rfq_key(
            client,
            sportsbook="kalshi",
            source_market_id="KX",
            source_selection_id="yes",
            project="marketmaking-test",
        )
    assert hit["winner"] is not None
    assert hit["winner"]["game_id"] == "g1"
    assert hit["resolved_source_selection_id"] == "Yes"
    assert hit["in_rank_window"] is True
    assert hit["lookup_note"] == "stamped RFQ winner (override) in live rank window"


def test_lookup_rfq_key_outside_rank_window() -> None:
    client = MagicMock()
    row = MagicMock(
        items=lambda: [
            ("game_id", "wsdsyn-g1"),
            ("src_market_id", "KXITFDOUBLES-TEST"),
            ("src_selection_id", "yes"),
            ("is_rfq_winner", None),
            ("in_rank_window", False),
            ("source_ids", {"market_id": "KXITFDOUBLES-TEST", "selection_id": "yes"}),
        ]
    )
    with patch(
        "mappers.control_plane.console_oom_catalog._query_lookup_rows",
        return_value=[_row_to_dict(row)],
    ):
        hit = lookup_rfq_key(
            client,
            sportsbook="kalshi",
            source_market_id="KXITFDOUBLES-TEST",
            source_selection_id="yes",
            project="marketmaking-test",
        )
    assert hit["winner"] is not None
    assert hit["in_rank_window"] is False
    assert hit["lookup_note"] is not None
    assert "opticodds_fixtures" in hit["lookup_note"]
    assert "fold+rank will not restamp" in hit["lookup_note"]
    assert "preflight" not in hit["lookup_note"]


def test_lookup_rfq_key_empty_sets_note() -> None:
    client = MagicMock()
    with patch("mappers.control_plane.console_oom_catalog._query_lookup_rows", return_value=[]):
        hit = lookup_rfq_key(
            client,
            sportsbook="kalshi",
            source_market_id="KXMISSING",
            source_selection_id="yes",
            project="marketmaking-test",
        )
    assert hit["winner"] is None
    assert hit["candidate_count"] == 0
    assert hit["in_rank_window"] is None
    assert hit["lookup_note"] == "no opticodds_mapping row for this RFQ key yet"


def test_catalog_lookup_route() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    with patch.object(
        control,
        "console_catalog_lookup",
        return_value={
            "winner": None,
            "candidates": [],
            "candidate_count": 0,
            "in_rank_window": None,
            "lookup_note": "no opticodds_mapping row for this RFQ key yet",
        },
    ):
        client = _client(control)
        resp = client.get(
            "/console/catalog/lookup",
            params={
                "sportsbook": "kalshi",
                "source_market_id": "KXTEST",
                "source_selection_id": "yes",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_catalog_routes_404_when_disabled() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
        catalog_enabled=False,
    )
    client = TestClient(app)
    lookup = client.get(
        "/console/catalog/lookup",
        params={
            "sportsbook": "kalshi",
            "source_market_id": "KXTEST",
            "source_selection_id": "yes",
        },
    )
    override = client.post(
        "/console/catalog/override",
        json={
            "sportsbook": "kalshi",
            "game_id": "g1",
            "market_id": "m1",
            "selection": "Team A",
            "source_market_id": "KXTEST",
            "reason": "prod hold",
        },
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
    )
    job = client.get("/console/catalog/override/jobs/missing")
    assert lookup.status_code == 404
    assert lookup.json()["detail"]["reason_code"] == "catalog_disabled"
    assert override.status_code == 404
    assert job.status_code == 404


def test_meta_exposes_catalog_enabled() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    client = _client(control)
    meta = client.get(
        "/meta",
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
    ).json()
    assert meta["catalog_enabled"] is True


def test_catalog_override_requires_reason() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    client = _client(control)
    resp = client.post(
        "/console/catalog/override",
        json={
            "sportsbook": "kalshi",
            "game_id": "g1",
            "market_id": "m1",
            "selection": "Team A",
            "source_market_id": "KX",
            "source_selection_id": "yes",
            "reason": "",
        },
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
    )
    assert resp.status_code == 422


def test_catalog_override_returns_job_id() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    with patch.object(
        control,
        "console_catalog_override",
        return_value={"job_id": "abc123", "status": "accepted", "poll_url": "/x"},
    ):
        client = _client(control)
        resp = client.post(
            "/console/catalog/override",
            json={
                "sportsbook": "kalshi",
                "game_id": "g1",
                "market_id": "m1",
                "selection": "Team A",
                "source_market_id": "KX",
                "source_selection_id": "yes",
                "reason": "test override",
            },
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
        )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "abc123"


def test_run_override_job_fails_when_sink_times_out() -> None:
    job = create_job(
        active=True,
        sportsbook="kalshi",
        source_market_id="KX",
        source_selection_id="yes",
    )
    message = {
        "game_id": "g1",
        "market_id": "m1",
        "sportsbook": "Kalshi",
        "selection": "Team A",
        "active": True,
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
        "source_ids": '{"market_id":"KX","selection_id":"yes"}',
    }
    with (
        patch(
            "mappers.control_plane.console_override_jobs.wait_for_override_sink",
            side_effect=TimeoutError("sink timeout"),
        ),
        patch("mappers.control_plane.console_override_jobs.start_prices_state_merge") as merge,
        patch("mappers.control_plane.console_override_jobs.bigquery.Client"),
    ):
        run_override_job(
            job.job_id,
            project="marketmaking-test",
            message=message,
            operator="alice@wsd.com",
            reason="test",
        )
    finished = get_job(job.job_id)
    assert finished is not None
    assert finished.status == "failed"
    assert "sink" in finished.message
    merge.assert_not_called()


def test_catalog_override_resolves_source_ids_from_lookup() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    with (
        patch(
            "mappers.control_plane.console_override_ops.lookup_rfq_key",
            return_value={
                "candidate_count": 1,
                "resolved_source_market_id": "KX",
                "resolved_source_selection_id": "Yes",
            },
        ),
        patch(
            "mappers.control_plane.console_override_ops.preflight_fixture_materialisation",
            return_value=None,
        ),
        patch(
            "mappers.control_plane.console_override_ops.publish_console_override",
            return_value="msg-1",
        ) as publish,
        patch("mappers.control_plane.console_override_ops.bigquery.Client"),
    ):
        client = _client(control)
        resp = client.post(
            "/console/catalog/override",
            json={
                "sportsbook": "kalshi",
                "game_id": "g1",
                "market_id": "m1",
                "selection": "Team A",
                "source_market_id": "KX",
                "source_selection_id": "yes",
                "reason": "test override",
                "active": True,
            },
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
        )
    assert resp.status_code == 200
    published = publish.call_args.args[1]
    source_ids = json.loads(published["source_ids"])
    assert source_ids["selection_id"] == "Yes"


def test_catalog_override_keeps_typed_ids_when_lookup_fails() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    with (
        patch(
            "mappers.control_plane.console_override_ops.lookup_rfq_key",
            side_effect=RuntimeError("bq timeout"),
        ),
        patch(
            "mappers.control_plane.console_override_ops.preflight_fixture_materialisation",
            return_value=None,
        ),
        patch(
            "mappers.control_plane.console_override_ops.publish_console_override",
            return_value="msg-1",
        ) as publish,
        patch("mappers.control_plane.console_override_ops.bigquery.Client"),
    ):
        client = _client(control)
        resp = client.post(
            "/console/catalog/override",
            json={
                "sportsbook": "kalshi",
                "game_id": "g1",
                "market_id": "m1",
                "selection": "Team A",
                "source_market_id": "KX",
                "source_selection_id": "yes",
                "reason": "deactivate while lookup is down",
                "active": False,
            },
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
        )
    assert resp.status_code == 200
    published = publish.call_args.args[1]
    source_ids = json.loads(published["source_ids"])
    assert source_ids["selection_id"] == "yes"


def test_catalog_override_blocks_preflight_failure() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    control = ProposalService(store, live=NullLiveLookup())
    with (
        patch(
            "mappers.control_plane.console_override_ops.lookup_rfq_key",
            return_value={
                "candidate_count": 1,
                "resolved_source_market_id": "KX",
                "resolved_source_selection_id": "yes",
            },
        ),
        patch(
            "mappers.control_plane.console_override_ops.preflight_fixture_materialisation",
            return_value="no fixture in opticodds_fixtures",
        ),
        patch("mappers.control_plane.console_override_ops.bigquery.Client"),
        patch(
            "mappers.control_plane.console_override_ops.publish_console_override"
        ) as publish,
    ):
        client = _client(control)
        resp = client.post(
            "/console/catalog/override",
            json={
                "sportsbook": "kalshi",
                "game_id": "g1",
                "market_id": "m1",
                "selection": "Team A",
                "source_market_id": "KX",
                "source_selection_id": "yes",
                "reason": "test override",
                "active": True,
            },
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"},
        )
    assert resp.status_code == 422
    assert "preflight" in resp.text.lower()
    publish.assert_not_called()


def test_run_override_job_materialises_active_override() -> None:
    job = create_job(
        active=True,
        sportsbook="kalshi",
        source_market_id="KX",
        source_selection_id="yes",
    )
    message = {
        "game_id": "g1",
        "market_id": "m1",
        "sportsbook": "Kalshi",
        "selection": "Team A",
        "active": True,
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
        "source_ids": '{"market_id":"KX","selection_id":"yes"}',
    }
    lookup_hit = {
        "winner": {
            "src_market_id": "KX",
            "src_selection_id": "yes",
            "is_rfq_winner": True,
            "rank_class": "override",
            "in_rank_window": True,
        },
        "candidates": [
            {
                "src_market_id": "KX",
                "src_selection_id": "yes",
                "is_rfq_winner": True,
                "rank_class": "override",
                "in_rank_window": True,
            }
        ],
    }
    with (
        patch("mappers.control_plane.console_override_jobs.wait_for_override_sink"),
        patch(
            "mappers.control_plane.console_override_jobs.start_prices_state_merge",
            return_value="run-1",
        ),
        patch("mappers.control_plane.console_override_jobs.run_fold_rank"),
        patch(
            "mappers.control_plane.console_override_jobs.lookup_rfq_key",
            return_value=lookup_hit,
        ),
        patch("mappers.control_plane.console_override_jobs.bigquery.Client"),
    ):
        run_override_job(
            job.job_id,
            project="marketmaking-test",
            message=message,
            operator="alice@wsd.com",
            reason="test",
        )
    finished = get_job(job.job_id)
    assert finished is not None
    assert finished.status == "materialised"


def _override_message() -> dict:
    return {
        "game_id": "g1",
        "market_id": "m1",
        "sportsbook": "Kalshi",
        "selection": "Team A",
        "active": True,
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
        "source_ids": '{"market_id": "KX", "selection_id": "yes"}',
    }


def test_run_override_job_skips_rank_when_merge_fails() -> None:
    job = create_job(
        active=True,
        sportsbook="kalshi",
        source_market_id="KX",
        source_selection_id="yes",
    )
    with (
        patch("mappers.control_plane.console_override_jobs.wait_for_override_sink"),
        patch(
            "mappers.control_plane.console_override_jobs.start_prices_state_merge",
            side_effect=RuntimeError("transfers denied"),
        ),
        patch("mappers.control_plane.console_override_jobs.run_fold_rank") as rank,
        patch("mappers.control_plane.console_override_jobs.lookup_rfq_key") as lookup,
        patch("mappers.control_plane.console_override_jobs.bigquery.Client"),
    ):
        run_override_job(
            job.job_id,
            project="marketmaking-test",
            message=_override_message(),
            operator="alice@wsd.com",
            reason="test",
        )
    finished = get_job(job.job_id)
    assert finished is not None
    assert finished.status == "accepted_not_materialised"
    assert "merge failed" in finished.message
    rank.assert_not_called()
    lookup.assert_not_called()


def test_run_override_job_skips_rank_when_merge_disabled() -> None:
    job = create_job(
        active=False,
        sportsbook="kalshi",
        source_market_id="KX",
        source_selection_id="yes",
    )
    with (
        patch("mappers.control_plane.console_override_jobs.wait_for_override_sink"),
        patch(
            "mappers.control_plane.console_override_jobs.start_prices_state_merge",
            return_value="disabled",
        ),
        patch("mappers.control_plane.console_override_jobs.run_fold_rank") as rank,
        patch("mappers.control_plane.console_override_jobs.bigquery.Client"),
    ):
        run_override_job(
            job.job_id,
            project="marketmaking-test",
            message=_override_message(),
            operator="alice@wsd.com",
            reason="test",
        )
    finished = get_job(job.job_id)
    assert finished is not None
    assert finished.status == "accepted_not_materialised"
    assert "merge trigger disabled" in finished.message
    rank.assert_not_called()


def test_wait_for_override_sink_requires_source_ids_content() -> None:
    row = MagicMock(active=True, source_ids_json='{"market_id":"OTHER","selection_id":"yes"}')
    # A leftover override job can poll the same clock. A finite iterator
    # raises StopIteration on that extra read and hides the timeout.
    reads = {"n": 0}

    def _clock() -> float:
        reads["n"] += 1
        return 0.0 if reads["n"] <= 2 else 2.0

    with (
        patch("mappers.control_plane.console_override_sink.ro_query", return_value=[row]),
        patch("mappers.control_plane.console_override_sink.time.sleep"),
        patch(
            "mappers.control_plane.console_override_sink.time.monotonic",
            side_effect=_clock,
        ),
        pytest.raises(TimeoutError, match="sink did not reflect"),
    ):
        wait_for_override_sink(
            MagicMock(),
            "marketmaking-test",
            _override_message(),
            timeout_sec=1,
        )


def test_wait_for_override_sink_accepts_compact_source_ids() -> None:
    row = MagicMock(
        active=True,
        source_ids_json='{"market_id":"KX","selection_id":"yes"}',
    )
    with patch("mappers.control_plane.console_override_sink.ro_query", return_value=[row]):
        wait_for_override_sink(
            MagicMock(),
            "marketmaking-test",
            _override_message(),
            timeout_sec=1,
        )


def test_catalog_route_is_spa_document() -> None:
    assert is_spa_document_path("/catalog")
