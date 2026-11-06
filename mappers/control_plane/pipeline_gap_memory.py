"""Cgroup memory pressure alert before gap-propose is OOMKilled.

SIGKILL from the kube memory limit cannot run Python handlers. Poll cgroup
usage and publish once when the container nears its limit so ops see a
critical page even when the process dies before harvest finishes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from BigQuery.alerts import Severity

if TYPE_CHECKING:
    from BigQuery.alerts import AlertPublisher

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.90
DEFAULT_POLL_SEC = 30.0
OUTAGE_SEVERITY: Severity = "critical"
PublishFn = Callable[["AlertPublisher | None", Severity, str], None]


def cgroup_memory_ratio() -> float | None:
    """Current cgroup memory / limit, or None when unlimited or unreadable."""
    base = Path("/sys/fs/cgroup")
    try:
        current = int((base / "memory.current").read_text().strip())
        max_raw = (base / "memory.max").read_text().strip()
    except (OSError, ValueError):
        return None
    if max_raw == "max":
        return None
    try:
        limit = int(max_raw)
    except ValueError:
        return None
    if limit <= 0:
        return None
    return current / limit


def memory_pressure_alert_text(ratio: float) -> str:
    """Slack body when cgroup usage crosses the pressure threshold."""
    return (
        "Pipeline gap-fix: memory pressure "
        f"({ratio * 100:.0f}% of cgroup limit). "
        "OOMKilled is likely before propose — raise limits or ship harvest fixes."
    )


class MemoryPressureWatch:
    """One-shot near-OOM alert; disarm on a normal finish."""

    def __init__(
        self,
        publisher: AlertPublisher | None,
        *,
        publish: PublishFn,
        threshold: float = DEFAULT_THRESHOLD,
        poll_sec: float = DEFAULT_POLL_SEC,
        ratio_fn: Callable[[], float | None] = cgroup_memory_ratio,
    ) -> None:
        self._publisher = publisher
        self._publish = publish
        self._threshold = threshold
        self._poll_sec = poll_sec
        self._ratio_fn = ratio_fn
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._alerted = False
        threading.Thread(target=self._poll, daemon=True).start()

    def disarm(self) -> None:
        """Mark harvest finished so the watcher does not alert."""
        self._finished.set()

    def alert_if_over_threshold(self, ratio: float) -> None:
        """Publish once when ``ratio`` is at or above the threshold."""
        if self._finished.is_set() or ratio < self._threshold:
            return
        with self._lock:
            if self._alerted:
                return
            self._alerted = True
        text = memory_pressure_alert_text(ratio)
        logger.error("pipeline gap-fix %s", text)
        self._publish(self._publisher, OUTAGE_SEVERITY, text)

    def _poll(self) -> None:
        while not self._finished.wait(timeout=self._poll_sec):
            ratio = self._ratio_fn()
            if ratio is None:
                continue
            self.alert_if_over_threshold(ratio)


def arm_memory_pressure_watch(
    publisher: AlertPublisher | None,
    publish: PublishFn,
) -> MemoryPressureWatch:
    """Start cgroup polling; skips publish when limits are unreadable."""
    return MemoryPressureWatch(publisher, publish=publish)
