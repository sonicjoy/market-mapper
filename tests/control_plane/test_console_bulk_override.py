"""Bulk override batch publish, batch propagation, ops and routes (mmmapper#21). No BQ, no Pub/Sub."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.console_bulk_override_batch import batch_view, publish_override_batch
from mappers.control_plane.console_override_jobs import create_job, get_job, run_override_batch
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.models import Actor, ActorRole, ForbiddenError, ValidationFailedError
from mappers.control_plane.rows import EntityRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore

_ALICE = Actor(subject="alice@wsd.com", role=ActorRole.PROPOSER)
_JOBS = "mappers.control_plane.console_override_jobs"


@pytest.fixture(autouse=True)
def _clear_overrides() -> Any:
    """Route tests override app dependencies; never leak them into other modules."""
    yield
    app.dependency_overrides.clear()


def _pair(ticker: str, side: str, selection: str, game: str = "g1") -> dict[str, Any]:
    return {
        "source_market_id": ticker,
        "source_selection_id": side,
        "game_id": game,
        "market_id": "moneyline",
        "selection": selection,
    }


class _Recorder:
    """Fake publisher / preflight / starter; never touches Pub/Sub."""

    def __init__(self, fail_on: str = "", preflight: dict[str, str] | None = None) -> None:
        self.published: list[dict[str, Any]] = []
        self.started: list[tuple[str, dict[str, Any]]] = []
        self.preflights: list[str] = []
        self.fail_on = fail_on
        self.preflight_reasons = preflight or {}

    def publish(self, _project: str, message: dict[str, Any], *, operator: str, reason: str) -> str:
        if self.fail_on and self.fail_on in message["source_ids"]:
            raise RuntimeError("pubsub down")
        self.published.append({**message, "_operator": operator, "_reason": reason})
        return f"msg-{len(self.published)}"

    def preflight(self, game_id: str) -> str | None:
        self.preflights.append(game_id)
        return self.preflight_reasons.get(game_id)

    def start(self, entries: list[tuple[str, dict[str, Any]]]) -> None:
        self.started.extend(entries)


def _publish(rec: _Recorder, pairs: list[dict[str, Any]], **body: Any) -> dict[str, Any]:
    payload = {"sportsbook": "kalshi", "reason": "NHL preseason", "pairs": pairs, **body}
    return publish_override_batch(
        payload, _ALICE, project="p", preflight=rec.preflight, publish=rec.publish, start=rec.start
    )


def test_batch_publishes_each_pair_once_and_starts_one_propagation() -> None:
    rec = _Recorder()
    view = _publish(rec, [_pair("KX-ANA", "yes", "Anaheim Ducks"), _pair("KX-LA", "yes", "Los Angeles Kings")])
    assert [json.loads(m["source_ids"]) for m in rec.published] == [
        {"market_id": "KX-ANA", "selection_id": "yes"},
        {"market_id": "KX-LA", "selection_id": "yes"},
    ]
    assert {m["sportsbook"] for m in rec.published} == {"Kalshi"}
    assert {m["mapping_source"] for m in rec.published} == {"mapping-console-bulk"}
    assert rec.preflights == ["g1"]
    assert len(rec.started) == 2
    assert view["counts"] == {"accepted": 2}
    assert batch_view(view["batch_id"])["operator"] == "alice@wsd.com"


def test_batch_refused_whole_before_any_publish() -> None:
    rec = _Recorder(preflight={"g2": "no fixture in rank window"})
    with pytest.raises(ValidationFailedError, match="g2"):
        _publish(rec, [_pair("KX-A", "yes", "A"), _pair("KX-B", "yes", "B", game="g2")])
    with pytest.raises(ValidationFailedError, match="twice"):
        _publish(_Recorder(), [_pair("KX-A", "yes", "A"), _pair("KX-A", "yes", "B")])
    with pytest.raises(ValidationFailedError, match="reason"):
        _publish(_Recorder(), [_pair("KX-A", "yes", "A")], reason=" ")
    with pytest.raises(ValidationFailedError, match="market_mapping"):
        _publish(_Recorder(), [_pair("NX.1", "", "A")], sportsbook="crypto.com")
    assert rec.published == []


def test_viewer_cannot_publish() -> None:
    rec = _Recorder()
    viewer = Actor(subject="v@wsd.com", role=ActorRole.VIEWER)
    with pytest.raises(ForbiddenError):
        publish_override_batch(
            {"sportsbook": "kalshi", "reason": "x", "pairs": [_pair("KX-A", "yes", "A")]},
            viewer,
            project="p",
            preflight=rec.preflight,
            publish=rec.publish,
            start=rec.start,
        )


def test_one_failed_publish_does_not_stop_the_rest() -> None:
    rec = _Recorder(fail_on="KX-B")
    view = _publish(rec, [_pair("KX-A", "yes", "A"), _pair("KX-B", "yes", "B"), _pair("KX-C", "yes", "C")])
    assert view["counts"] == {"accepted": 2, "failed": 1}
    assert len(rec.started) == 2


def _message(ticker: str) -> dict[str, Any]:
    return {
        "game_id": "g1",
        "market_id": "moneyline",
        "sportsbook": "Kalshi",
        "selection": "A",
        "active": True,
        "source_ids": json.dumps({"market_id": ticker, "selection_id": "yes"}),
    }


def test_run_override_batch_merges_and_ranks_once() -> None:
    jobs = [
        create_job(active=True, sportsbook="kalshi", source_market_id=t, source_selection_id="yes")
        for t in ("A", "B", "C")
    ]
    entries = [(j.job_id, _message(j.source_market_id)) for j in jobs]
    winner = {"candidates": [], "winner": None}
    with (
        patch(f"{_JOBS}.bigquery.Client"),
        patch(f"{_JOBS}.wait_for_override_sink") as sink,
        patch(f"{_JOBS}.start_prices_state_merge", return_value="run-1") as merge,
        patch(f"{_JOBS}.run_fold_rank") as rank,
        patch(f"{_JOBS}.lookup_rfq_key", return_value=winner),
        patch(f"{_JOBS}.assess_materialisation", return_value=None),
    ):
        run_override_batch(entries, project="p")
    assert sink.call_count == 3
    merge.assert_called_once()
    rank.assert_called_once()
    assert {get_job(j.job_id).status for j in jobs} == {"materialised"}  # type: ignore[union-attr]


def test_run_override_batch_merge_failure_marks_every_job() -> None:
    jobs = [
        create_job(active=True, sportsbook="kalshi", source_market_id=t, source_selection_id="yes") for t in ("A", "B")
    ]
    entries = [(j.job_id, _message(j.source_market_id)) for j in jobs]
    with (
        patch(f"{_JOBS}.bigquery.Client"),
        patch(f"{_JOBS}.wait_for_override_sink"),
        patch(f"{_JOBS}.start_prices_state_merge", side_effect=RuntimeError("dts down")),
        patch(f"{_JOBS}.run_fold_rank") as rank,
    ):
        run_override_batch(entries, project="p")
    rank.assert_not_called()
    assert {get_job(j.job_id).status for j in jobs} == {"accepted_not_materialised"}  # type: ignore[union-attr]


# ---- ops + routes ----------------------------------------------------------------------------


def _control(rows_by_sql: dict[str, list[dict[str, Any]]]) -> ProposalService:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_bulk",
        entities=[
            EntityRow(
                "nhl",
                "team",
                "ANA",
                "Anaheim Ducks",
                [],
            ),
            EntityRow(
                "nhl",
                "team",
                "LAK",
                "Los Angeles Kings",
                [],
            ),
        ],
        leagues=[],
        market_rules=[],
        activate=True,
    )
    control = ProposalService(store, live=NullLiveLookup())

    def fake(sql: str, _params: list[Any]) -> list[dict[str, Any]]:
        return next((rows for key, rows in rows_by_sql.items() if key in sql), [])

    control.bulk_override_query_fn = fake  # type: ignore[attr-defined]
    return control


_SELECTIONS = [
    {
        "market_id": "moneyline",
        "market": "Moneyline",
        "selection": "Anaheim Ducks",
        "selection_line": "",
        "points": 0.0,
    },
    {
        "market_id": "moneyline",
        "market": "Moneyline",
        "selection": "Los Angeles Kings",
        "selection_line": "",
        "points": 0.0,
    },
    {"market_id": "total_goals", "market": "Total Goals", "selection": "", "selection_line": "over", "points": 5.5},
]


def test_draft_pairs_on_the_venue_display_names() -> None:
    control = _control({"prices_dedup_state": _SELECTIONS})
    out = control.console_bulk_override_draft(  # type: ignore[attr-defined]
        {
            "game_id": "12253-31516-2026-09-26",
            "market_id": "moneyline",
            "league": "nhl",
            "legs": [
                {"source_market_id": "KXNHLGAME-26SEP26ANALA-LA", "source_selection_id": "yes", "name": "Los Angeles Kings"},
                {"source_market_id": "KXNHLGAME-26SEP26ANALA-ANA", "source_selection_id": "yes", "name": "Anaheim Ducks"},
            ],
        }
    )
    assert [p["target"]["selection"] for p in out["pairs"]] == ["Los Angeles Kings", "Anaheim Ducks"]
    assert out["pairs"][0]["target"]["game_id"] == "12253-31516-2026-09-26"
    assert out["counts"]["confident"] == 2


def test_draft_rejects_unpriced_market() -> None:
    control = _control({"prices_dedup_state": _SELECTIONS})
    with pytest.raises(ValidationFailedError, match="no priced"):
        control.console_bulk_override_draft({"game_id": "g", "market_id": "nope", "legs": []})  # type: ignore[attr-defined]


def test_legs_shape_and_markets_grouping() -> None:
    legs = [
        {
            "market_ticker": "KXNHLGAME-26SEP26ANALA-LA",
            "side": "yes",
            "yes_sub_title": None,
            "line": None,
            "demand": 11372,
        }
    ]
    control = _control({"rfq_latest": legs, "prices_dedup_state": _SELECTIONS})
    out = control.console_bulk_override_legs(sportsbook="kalshi", event="KXNHLGAME-26SEP26ANALA")  # type: ignore[attr-defined]
    assert out["legs"][0] == {
        "source_market_id": "KXNHLGAME-26SEP26ANALA-LA",
        "source_selection_id": "yes",
        "name": "",
        "line": None,
        "demand": 11372,
    }
    assert out["day"] == ""  # no kickoff is read off a Kalshi ticker
    markets = control.console_bulk_override_markets(game_id="g")["markets"]  # type: ignore[attr-defined]
    assert [m["market_id"] for m in markets] == ["moneyline", "total_goals"]
    with pytest.raises(ValidationFailedError):
        control.console_bulk_override_legs(sportsbook="polymarket", event="x")  # type: ignore[attr-defined]


def _client(control: ProposalService) -> TestClient:
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(gcp_project="marketmaking-test")
    return TestClient(app)


def test_publish_route_requires_reason_field_and_forwards_actor() -> None:
    control = _control({})
    client = _client(control)
    headers = {"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@wsd.com"}
    assert (
        client.post(
            "/console/bulk-override/publish", json={"sportsbook": "kalshi", "pairs": []}, headers=headers
        ).status_code
        == 422
    )
    with patch.object(control, "console_bulk_override_publish", return_value={"batch_id": "b1"}) as pub:
        resp = client.post(
            "/console/bulk-override/publish",
            json={"sportsbook": "kalshi", "reason": "r", "pairs": [_pair("KX-A", "yes", "A")]},
            headers=headers,
        )
    assert resp.status_code == 200 and resp.json() == {"batch_id": "b1"}
    body, actor = pub.call_args.args
    assert body["pairs"][0]["source_market_id"] == "KX-A"
    assert actor.subject == "alice@wsd.com"
    assert client.get("/console/bulk-override/batches/missing").status_code == 404


def test_bulk_routes_404_when_catalog_disabled() -> None:
    app.dependency_overrides[service] = lambda: _control({})
    app.dependency_overrides[get_settings] = lambda: Settings(gcp_project="marketmaking-test", catalog_enabled=False)
    client = TestClient(app)
    assert client.get("/console/bulk-override/optic-fixtures").status_code == 404
