"""Harvest yield when cgroup memory nears the pod limit."""

from __future__ import annotations

import os
from collections.abc import Callable

from mappers.control_plane.pipeline_gap_memory import cgroup_memory_ratio

DEFAULT_YIELD_RATIO = 0.75


def harvest_yield_ratio() -> float:
    """Cgroup ratio at which harvest stops drafting (before verify)."""
    raw = os.environ.get("MAPPING_PIPELINE_GAP_YIELD_RATIO", "")
    if raw.strip():
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_YIELD_RATIO


def harvest_should_yield(*, ratio_fn: Callable[[], float | None] = cgroup_memory_ratio) -> bool:
    """True when harvest should stop and submit the pins drafted so far."""
    ratio = ratio_fn()
    if ratio is None:
        return False
    return ratio >= harvest_yield_ratio()


def make_yield_checker(
    *,
    ratio_fn: Callable[[], float | None] = cgroup_memory_ratio,
) -> Callable[[], bool]:
    """Return a callable suitable for slot-fill loops."""
    threshold = harvest_yield_ratio()

    def check() -> bool:
        ratio = ratio_fn()
        return ratio is not None and ratio >= threshold

    return check
