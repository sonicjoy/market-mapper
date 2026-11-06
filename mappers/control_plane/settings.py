"""Runtime settings for the M3a control plane (environment-driven).

Mirrors the mm-trading-dash convention: one process per deploy, configuration
resolved from the environment and cached once. The environment (``test`` vs
``prod``) is inferred from ``GCP_PROJECT``. Test always may append
``rule_set_activated``; prod may when ``MAPPING_CP_ALLOW_ACTIVATE=1``.
Authorization allow-list (who may administer) lives here — never in a
request header — because the plan requires actor identity and role to come
from authentication, not the payload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

_TEST_PROJECT = "marketmaking-test"


def _csv_lower(raw: str) -> frozenset[str]:
    """Parse a comma-separated list into a normalized lowercase set."""
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def _emails(raw: str) -> frozenset[str]:
    """Parse a comma-separated email allow-list into a normalized set."""
    return _csv_lower(raw)


@dataclass(frozen=True)
class Settings:
    """Control-plane settings resolved from the environment."""

    gcp_project: str
    admin_emails: frozenset[str] = field(default_factory=frozenset)
    require_maker_checker: bool = False
    cow_enabled: bool = True
    chat_enabled: bool = False
    catalog_enabled: bool = True
    chat_provider: str = "gemini"
    chat_model: str = "gemini-3.8-flash"
    chat_api_key_secret: str = ""
    chat_tool_rounds: int = 5
    chat_timeout_sec: float = 30.0
    chat_daily_turn_budget: int = 0
    chat_daily_token_budget: int = 0
    chat_topic_gate_enabled: bool = True
    chat_topic_min_score: int = 1
    chat_topic_allow_phrases: frozenset[str] = field(default_factory=frozenset)
    probe_cache_ttl_sec: float = 900.0
    review_window_days: int = 365
    allow_activate_override: bool = False

    @property
    def environment(self) -> str:
        """Deploy environment inferred from the GCP project."""
        return "test" if self.gcp_project == _TEST_PROJECT else "prod"

    @property
    def allow_activate(self) -> bool:
        """Test always; prod only when MAPPING_CP_ALLOW_ACTIVATE=1."""
        return self.environment == "test" or self.allow_activate_override

    @property
    def live_sot(self) -> str:
        """Mapper classify SoT. The activated BQ tip is the only source."""
        return "bq"


def _flag(raw: str | None, *, default: bool) -> bool:
    """Parse a truthy/falsey env flag; empty uses default."""
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process from environment variables."""
    return Settings(
        gcp_project=os.environ["GCP_PROJECT"],
        admin_emails=_emails(os.environ.get("MAPPING_CP_ADMIN_EMAILS", "")),
        # Default off so a single local operator can propose+approve; set
        # MAPPING_CP_REQUIRE_MAKER_CHECKER=1 to enforce distinct checker.
        require_maker_checker=_flag(
            os.environ.get("MAPPING_CP_REQUIRE_MAKER_CHECKER"),
            default=False,
        ),
        # Writes: sparse COW deltas (default). Reads always coalesce tip→root.
        # MAPPING_CP_COW=0 persists a full logical clone per candidate, not a
        # single-layer read of that rule_set_id.
        cow_enabled=_flag(os.environ.get("MAPPING_CP_COW"), default=True),
        # Mapper Chat (M3c). Default off locally; test overlay sets MAPPING_CP_CHAT=1.
        chat_enabled=_flag(os.environ.get("MAPPING_CP_CHAT"), default=False),
        catalog_enabled=_flag(os.environ.get("MAPPING_CP_CATALOG"), default=True),
        chat_provider=(os.environ.get("MAPPING_CP_CHAT_PROVIDER") or "gemini").strip().lower(),
        chat_model=(os.environ.get("MAPPING_CP_CHAT_MODEL") or "gemini-3.8-flash").strip(),
        chat_api_key_secret=(os.environ.get("MAPPING_CP_CHAT_API_KEY_SECRET") or "").strip(),
        chat_tool_rounds=_int(os.environ.get("MAPPING_CP_CHAT_TOOL_ROUNDS"), default=5),
        chat_timeout_sec=_float(os.environ.get("MAPPING_CP_CHAT_TIMEOUT_SEC"), default=30.0),
        chat_daily_turn_budget=_int(os.environ.get("MAPPING_CP_CHAT_DAILY_TURN_BUDGET"), default=0),
        chat_daily_token_budget=_int(
            os.environ.get("MAPPING_CP_CHAT_DAILY_TOKEN_BUDGET"), default=0
        ),
        # Off-topic turns are refused before any LLM call; kill-switch for prod.
        chat_topic_gate_enabled=_flag(
            os.environ.get("MAPPING_CP_CHAT_TOPIC_GATE"), default=True
        ),
        chat_topic_min_score=_int(os.environ.get("MAPPING_CP_CHAT_TOPIC_MIN_SCORE"), default=1),
        chat_topic_allow_phrases=_csv_lower(os.environ.get("MAPPING_CP_CHAT_TOPIC_ALLOW", "")),
        probe_cache_ttl_sec=_float(
            os.environ.get("MAPPING_CP_PROBE_CACHE_TTL_SEC"), default=900.0
        ),
        # Review rehydrates every proposal in this window; bounds queue cost as
        # audit history grows. A card open longer than this is dead anyway.
        review_window_days=_int(
            os.environ.get("MAPPING_CP_REVIEW_WINDOW_DAYS"), default=365
        ),
        allow_activate_override=_flag(
            os.environ.get("MAPPING_CP_ALLOW_ACTIVATE"), default=False
        ),
    )


def _int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default
