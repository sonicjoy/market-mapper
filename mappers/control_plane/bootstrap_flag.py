"""Env flag for bootstrap → control-plane cutover (no TOML writes)."""

from __future__ import annotations

import os


def bootstrap_proposals_enabled() -> bool:
    """True when TOML writes are off. Only an explicit flag disables it."""
    raw = (os.environ.get("MAPPING_CP_BOOTSTRAP") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}
