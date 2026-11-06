"""Cgroup memory pressure watcher for gap-propose."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

from mappers.control_plane.pipeline_gap_memory import (
    MemoryPressureWatch,
    cgroup_memory_ratio,
    memory_pressure_alert_text,
)


def test_memory_pressure_alert_text_mentions_oom() -> None:
    text = memory_pressure_alert_text(0.92)
    assert "memory pressure" in text
    assert "92%" in text
    assert "OOMKilled" in text


def test_watch_alerts_once_when_over_threshold() -> None:
    publish = MagicMock()
    watch = MemoryPressureWatch(
        None,
        publish=publish,
        threshold=0.9,
        poll_sec=60.0,
        ratio_fn=lambda: 0.95,
    )
    watch.alert_if_over_threshold(0.95)
    watch.alert_if_over_threshold(0.96)
    publish.assert_called_once()
    _pub, severity, text = publish.call_args.args
    assert severity == "critical"
    assert "memory pressure" in text
    watch.disarm()
    time.sleep(0.05)


def test_cgroup_memory_ratio_none_when_unlimited(tmp_path, monkeypatch) -> None:
    base = tmp_path / "cgroup"
    base.mkdir()
    (base / "memory.current").write_text("100\n", encoding="utf-8")
    (base / "memory.max").write_text("max\n", encoding="utf-8")
    def fake_path(arg: str) -> Path:
        return base if arg == "/sys/fs/cgroup" else Path(arg)

    monkeypatch.setattr("mappers.control_plane.pipeline_gap_memory.Path", fake_path)
    assert cgroup_memory_ratio() is None
