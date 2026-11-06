"""CronJob deadline watcher: alert once, stay silent when harvest finishes."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

from mappers.control_plane.pipeline_gap_deadline import (
    DeadlineWatch,
    arm_deadline_watch,
    deadline_sec_from_env,
    sigterm_alert_text,
    timeout_alert_text,
)
from mappers.control_plane.pipeline_gap_propose import run_once


def test_timeout_alert_text_names_cap_and_no_propose() -> None:
    text = timeout_alert_text(deadline_sec=3600, elapsed_sec=3601)
    assert "activeDeadlineSeconds=3600s" in text
    assert "3601s" in text
    assert "did not propose" in text


def test_sigterm_alert_text_mentions_oom() -> None:
    text = sigterm_alert_text(elapsed_sec=612)
    assert "SIGTERM" in text
    assert "OOMKilled" in text


def test_deadline_sec_from_env_zero_disables(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_DEADLINE_SEC", "0")
    assert deadline_sec_from_env() == 0
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_DEADLINE_SEC", "3600")
    assert deadline_sec_from_env() == 3600


def test_watch_does_not_alert_when_disarmed_before_cap() -> None:
    publish = MagicMock()
    watch = DeadlineWatch(
        None, deadline_sec=2, publish=publish, catch_signal=False,
    )
    watch.disarm()
    time.sleep(0.05)
    publish.assert_not_called()


def test_watch_alerts_on_sigterm_before_cap() -> None:
    publish = MagicMock()
    watch = DeadlineWatch(
        None, deadline_sec=3600, publish=publish, catch_signal=False,
    )
    watch.alert_if_unfinished(trigger="sigterm")
    publish.assert_called_once()
    _pub, severity, text = publish.call_args.args
    assert severity == "critical"
    assert "SIGTERM" in text


def test_watch_alerts_once_when_cap_elapses() -> None:
    publish = MagicMock()
    watch = DeadlineWatch(
        None, deadline_sec=0.05, publish=publish, catch_signal=False,
    )
    time.sleep(0.2)
    watch.disarm()
    publish.assert_called_once()
    _pub, severity, text = publish.call_args.args
    assert severity == "critical"
    assert "did not propose" in text
    watch.alert_if_unfinished()
    publish.assert_called_once()


def test_arm_deadline_watch_zero_is_noop() -> None:
    publish = MagicMock()
    watch = arm_deadline_watch(None, publish, deadline_sec=0, catch_signal=False)
    watch.alert_if_unfinished()
    publish.assert_not_called()
    watch.disarm()


def test_run_once_arms_deadline_watch(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_DEADLINE_SEC", "0")
    armed: list[object] = []

    class _Watch:
        def disarm(self) -> None:
            armed.append("disarm")

    def fake_arm(publisher: object, publish: object, **_k: object) -> _Watch:
        armed.append(publisher)
        return _Watch()

    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.arm_deadline_watch", fake_arm,
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.build_pipeline_service",
        lambda: (object(), "test"),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.build_gap_propose_publisher",
        MagicMock(),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.arm_memory_pressure_watch",
        lambda *_a, **_k: type("W", (), {"disarm": lambda self: None})(),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.run_pipeline_gap_propose",
        lambda **_k: {"ok": True, "action": "skip"},
    )
    assert run_once()["action"] == "skip"
    assert "disarm" in armed


def test_run_once_publishes_critical_on_crash(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_DEADLINE_SEC", "0")
    publisher = MagicMock()

    def boom(**_k: object) -> dict[str, object]:
        raise RuntimeError("poly_usa_close oom")

    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.arm_deadline_watch",
        lambda *_a, **_k: type("W", (), {"disarm": lambda self: None})(),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.build_pipeline_service",
        lambda: (object(), "test"),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.build_gap_propose_publisher",
        lambda: publisher,
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.arm_memory_pressure_watch",
        lambda *_a, **_k: type("W", (), {"disarm": lambda self: None})(),
    )
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.run_pipeline_gap_propose",
        boom,
    )
    try:
        run_once()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected crash")
    severity, text = publisher.publish.call_args.args
    assert severity == "critical"
    assert text.startswith("[CRITICAL] ")
    assert "crashed before finish" in text
    assert "poly_usa_close oom" in text
    publisher.close.assert_called_once()
