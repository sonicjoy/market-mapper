"""Channel routing on the shared application-alerts publisher.

Mapping alerts share #marketmaking-alerts-rfqs with every other publisher on the
topic because an incoming webhook is bound to one channel. ALERT_SLACK_CHANNEL
lets these alerts name their own; it must stay absent from the payload when
unset, so nothing changes until the relay side is ready for it.
"""

import pytest

from BigQuery.alerts import (
    AlertPublisher,
    build_gap_propose_publisher,
    build_publisher,
    format_critical_alert,
)


@pytest.fixture
def disabled_publisher_kwargs():
    """Publisher config that never touches Pub/Sub."""
    return {"enabled": False, "project_id": None, "topic_id": "application-alerts"}


def test_payload_has_no_channel_key_by_default(disabled_publisher_kwargs):
    publisher = AlertPublisher(**disabled_publisher_kwargs)
    assert "channel" not in publisher.build_payload("warning", "gaps")


def test_payload_carries_a_configured_channel(disabled_publisher_kwargs):
    publisher = AlertPublisher(**disabled_publisher_kwargs, channel="#marketmaking-mapping-alerts")
    assert publisher.build_payload("warning", "gaps")["channel"] == "#marketmaking-mapping-alerts"


def test_blank_channel_is_treated_as_unset(disabled_publisher_kwargs):
    publisher = AlertPublisher(**disabled_publisher_kwargs, channel="   ")
    assert "channel" not in publisher.build_payload("warning", "gaps")


def test_build_publisher_reads_alert_slack_channel(monkeypatch):
    monkeypatch.setenv("ALERT_PUBSUB_ENABLED", "false")
    monkeypatch.setenv("ALERT_SLACK_CHANNEL", " #marketmaking-mapping-alerts ")
    publisher = build_publisher()
    assert publisher.build_payload("info", "hi")["channel"] == "#marketmaking-mapping-alerts"


def test_build_publisher_omits_channel_when_env_is_unset(monkeypatch):
    monkeypatch.setenv("ALERT_PUBSUB_ENABLED", "false")
    monkeypatch.delenv("ALERT_SLACK_CHANNEL", raising=False)
    publisher = build_publisher()
    assert "channel" not in publisher.build_payload("info", "hi")


def test_build_payload_accepts_critical_severity(disabled_publisher_kwargs):
    publisher = AlertPublisher(**disabled_publisher_kwargs)
    payload = publisher.build_payload("critical", "gap-propose down")
    assert payload["severity"] == "critical"


def test_format_critical_alert_prefixes_once() -> None:
    assert format_critical_alert("down") == "[CRITICAL] down"
    assert format_critical_alert("[CRITICAL] down") == "[CRITICAL] down"


def test_build_gap_propose_publisher_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("ALERT_PUBSUB_ENABLED", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    publisher = build_gap_propose_publisher()
    assert publisher._enabled is True


def test_build_publisher_defaults_disabled_without_env(monkeypatch) -> None:
    monkeypatch.delenv("ALERT_PUBSUB_ENABLED", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    publisher = build_publisher()
    assert publisher._enabled is False
