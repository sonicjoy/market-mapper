"""Mapping-risk alert job: selection, dedupe, Slack rollup, engine sink (no real publish)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests

from mappers.control_plane import mismap_alert
from mappers.control_plane.console_mismap import FLAG_SOURCE
from mappers.control_plane.mismap_alert import (
    ALERT_SOURCE,
    TOP_ROWS,
    recently_alerted,
    record_alerted,
    run_alert,
    select_new,
    slack_text,
)
from mappers.control_plane.mismap_alert_engine import RULE_ID, TOKEN_HEADER, EngineAlertSink, engine_payload
from mappers.control_plane.store import InMemoryStore, WorkItemRow

NOW = datetime(2026, 9, 26, 20, 0, tzinfo=UTC)


def _row(n: int, *, tier: str = "high", served: bool = True, sb: str = "kalshi") -> dict[str, Any]:
    return {
        "fingerprint": f"mismap|{sb}|KX-{n}|canon-{n}",
        "tier": tier,
        "is_rfq_winner": served,
        "sb": sb,
        "book": sb.title(),
        "src_key": f"KX-{n}",
        "league": "nhl",
        "market_id": "total_goals",
        "selection": "Over 7.5",
        "start_date": (NOW + timedelta(hours=n)).isoformat(),
        "signals": [{"code": "optic_disagrees", "tier": "high", "text": "Optic maps Over 6.5"}],
    }


class _Publisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def publish(self, severity: str, text: str) -> str:
        self.sent.append((severity, text))
        return "msg-1"


def _run(store: InMemoryStore, rows: list[dict[str, Any]], engine: EngineAlertSink | None = None) -> dict[str, Any]:
    publisher = _Publisher()
    out = run_alert(
        store=store,
        publisher=publisher,  # type: ignore[arg-type]
        engine=engine or EngineAlertSink(""),
        environment="test",
        query_fn=list,
        now=NOW,
    )
    out["publisher"] = publisher
    return out


@pytest.fixture
def scored(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows = [_row(1), _row(2, sb="polymarket"), _row(3, tier="medium"), _row(4, served=False)]
    monkeypatch.setattr(mismap_alert, "score_live_mappings", lambda _q, _now: rows)
    return rows


def _store() -> InMemoryStore:
    return InMemoryStore(environment="test", allow_activate=True)


def test_select_keeps_high_served_unflagged_unalerted() -> None:
    rows = [_row(1), _row(2), _row(3, tier="medium"), _row(4, served=False)]
    flags = {rows[0]["fingerprint"]: {"status": "resolved"}}
    kept = select_new(rows, flags, alerted={rows[1]["fingerprint"]})
    assert kept == []
    assert [r["src_key"] for r in select_new(rows, {}, set())] == ["KX-1", "KX-2"]


def test_run_alerts_once_then_dedupes_for_24h(scored: list[dict[str, Any]]) -> None:
    store = _store()
    first = _run(store, scored)
    assert first["new"] == 2
    severity, text = first["publisher"].sent[0]
    assert severity == "warning"
    assert "2 new high-risk mapping(s) being quoted (Kalshi 1, Polymarket 1)" in text
    assert "/mapping-risk?tier=high" in text
    second = _run(store, scored)
    assert second["new"] == 0 and second["publisher"].sent == []
    items = [i for i in store.list_work_items() if i.source == ALERT_SOURCE]
    assert len(items) == 1
    assert len((items[0].request_extraction or {})["fingerprints"]) == 2


def test_realerts_after_the_window() -> None:
    store = _store()
    record_alerted(store, [_row(1)], NOW - timedelta(hours=25))
    assert recently_alerted(store, NOW) == set()
    record_alerted(store, [_row(1)], NOW - timedelta(hours=2))
    assert recently_alerted(store, NOW) == {_row(1)["fingerprint"]}


def test_flagged_mapping_never_alerts(scored: list[dict[str, Any]]) -> None:
    store = _store()
    store.put_work_item(
        WorkItemRow(work_item_id="w1", fingerprint=scored[0]["fingerprint"], source=FLAG_SOURCE, status="open")
    )
    out = _run(store, scored)
    assert out["new"] == 1 and "KX-1" not in out["publisher"].sent[0][1]


def test_slack_text_caps_rows() -> None:
    rows = [_row(n) for n in range(TOP_ROWS + 5)]
    text = slack_text(rows, link="https://x/mapping-risk?tier=high")
    assert text.count("\n- ") == TOP_ROWS
    assert "... and 5 more." in text


def test_engine_sink_off_without_url_and_posts_one_per_row(scored: list[dict[str, Any]]) -> None:
    assert _run(_store(), scored)["engine"] == 0
    posted: list[dict[str, Any]] = []
    assert not EngineAlertSink("http://engine").enabled  # no token = off
    sink = EngineAlertSink(
        "http://engine",
        token="t0k",
        post_fn=lambda url, body, headers: posted.append({"url": url, "token": headers[TOKEN_HEADER], **body}) or 202,
    )
    store = _store()
    out = _run(store, scored, engine=sink)
    assert out["engine"] == 2
    assert {p["url"] for p in posted} == {"http://engine/v1/alerts/external"}
    assert {p["token"] for p in posted} == {"t0k"}
    assert {p["rule_id"] for p in posted} == {RULE_ID}
    assert posted[0]["scope_key"] == scored[0]["fingerprint"]
    # Second run inside Slack's 24h window: no Slack, but the engine is reinforced again.
    again = _run(store, scored, engine=sink)
    assert again["new"] == 0 and again["publisher"].sent == [] and again["engine"] == 2


def test_engine_sink_counts_refusals_and_stops_when_unreachable() -> None:
    refused = EngineAlertSink("http://engine", token="t", post_fn=lambda _u, _b, _h: 404)
    assert refused.raise_alerts([_row(1)], link="l") == 0

    def boom(_u: str, _b: dict[str, Any], _h: dict[str, str]) -> int:
        raise requests.ConnectionError("down")

    assert EngineAlertSink("http://engine", token="t", post_fn=boom).raise_alerts([_row(1), _row(2)], link="l") == 0


def test_engine_payload_shape() -> None:
    body = engine_payload(_row(1), link="https://x")
    assert body["severity_band"] == "HIGH" and body["scope_type"] == "mapping"
    assert body["evidence"]["reasons"] == ["optic_disagrees"] and body["evidence"]["link"] == "https://x"


def test_main_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mismap_alert.ALERT_ENV, raising=False)
    monkeypatch.setattr(mismap_alert, "build_store", lambda: pytest.fail("must not touch BigQuery"))
    assert mismap_alert.main([]) == 0
