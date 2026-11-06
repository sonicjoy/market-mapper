"""Alert when gap-propose is killed by CronJob ``activeDeadlineSeconds``.

Propose only runs after harvest. A deadline kill otherwise fails silent and
the next ``*/30`` tick starts with no Review card. The watcher publishes once
when the cap elapses while harvest is still running, and on SIGTERM before
disarm (kube Job DeadlineExceeded / delete / pre-OOM termination).
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

from BigQuery.alerts import AlertPublisher, Severity

logger = logging.getLogger(__name__)

DEFAULT_DEADLINE_SEC = 3600
OUTAGE_SEVERITY: Severity = "critical"
PublishFn = Callable[[AlertPublisher | None, Severity, str], None]


def deadline_sec_from_env() -> int:
    """CronJob cap in seconds. ``0`` disables the watcher (tests)."""
    raw = os.getenv("MAPPING_PIPELINE_GAP_DEADLINE_SEC", str(DEFAULT_DEADLINE_SEC))
    try:
        return max(0, int(str(raw).strip() or "0"))
    except ValueError:
        return DEFAULT_DEADLINE_SEC


def timeout_alert_text(*, deadline_sec: float, elapsed_sec: float) -> str:
    """Slack body when harvest is still running at the CronJob cap."""
    return (
        "Pipeline gap-fix: killed by CronJob timeout "
        f"(activeDeadlineSeconds={int(deadline_sec)}s, ran {elapsed_sec:.0f}s). "
        "Harvest did not propose. Next */30 tick can start (Forbid)."
    )


def sigterm_alert_text(*, elapsed_sec: float) -> str:
    """Slack body when kube terminates the Job before harvest finishes."""
    return (
        "Pipeline gap-fix: terminated before propose "
        f"(SIGTERM after {elapsed_sec:.0f}s). "
        "Check Job status (OOMKilled / DeadlineExceeded / manual delete)."
    )


class DeadlineWatch:
    """One-shot timeout alert; disarm on a normal finish."""

    def __init__(
        self,
        publisher: AlertPublisher | None,
        *,
        deadline_sec: float,
        publish: PublishFn,
        clock: Callable[[], float] = time.monotonic,
        catch_signal: bool = True,
    ) -> None:
        self._publisher = publisher
        self._deadline_sec = deadline_sec
        self._publish = publish
        self._clock = clock
        self._started = clock()
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._alerted = False
        self._prev_term: Any = None
        if deadline_sec > 0:
            threading.Thread(target=self._wait_then_alert, daemon=True).start()
            if catch_signal:
                self._prev_term = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, self._on_term)

    def disarm(self) -> None:
        """Mark harvest finished so the watcher does not alert."""
        self._finished.set()
        if self._prev_term is not None:
            signal.signal(signal.SIGTERM, self._prev_term)
            self._prev_term = None

    def _elapsed(self) -> float:
        return self._clock() - self._started

    def _wait_then_alert(self) -> None:
        if self._finished.wait(timeout=self._deadline_sec):
            return
        self.alert_if_unfinished()

    def _on_term(self, _signum: int, _frame: FrameType | None) -> None:
        self.alert_if_unfinished(trigger="sigterm")
        raise SystemExit(1)

    def alert_if_unfinished(self, *, trigger: str = "timeout") -> None:
        """Publish once when the Job is still in harvest/propose."""
        if self._deadline_sec <= 0 or self._finished.is_set():
            return
        with self._lock:
            if self._alerted:
                return
            self._alerted = True
        elapsed = self._elapsed()
        if trigger == "sigterm":
            text = sigterm_alert_text(elapsed_sec=elapsed)
        else:
            text = timeout_alert_text(
                deadline_sec=self._deadline_sec, elapsed_sec=elapsed,
            )
        logger.error("pipeline gap-fix %s", text)
        self._publish(self._publisher, OUTAGE_SEVERITY, text)


def arm_deadline_watch(
    publisher: AlertPublisher | None,
    publish: PublishFn,
    *,
    deadline_sec: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    catch_signal: bool = True,
) -> DeadlineWatch:
    """Start the cap watcher. ``deadline_sec=0`` is a no-op."""
    seconds = deadline_sec_from_env() if deadline_sec is None else deadline_sec
    return DeadlineWatch(
        publisher,
        deadline_sec=seconds,
        publish=publish,
        clock=clock,
        catch_signal=catch_signal and seconds > 0,
    )
