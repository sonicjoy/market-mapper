"""Shared eval harness: run a turn and read back its structured log line.

`path` and `outcome` are only observable through `mapping_chat_turn`, so the
suites assert against the captured record rather than the reply prose.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from mappers.control_plane import chat_optic_name
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_skills import onboard_league, probe_gap
from mappers.control_plane.models import ChatRequest, ChatResponse
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_LOGGER_NAME = "mapping.control_plane.chat"


@dataclass
class TurnRecord:
    """One turn plus the events it emitted."""

    response: ChatResponse
    turn: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def path(self) -> str:
        return str(self.turn.get("path") or "")

    @property
    def outcome(self) -> str:
        return str(self.turn.get("outcome") or "")

    @property
    def verdict(self) -> str:
        return str(self.turn.get("verdict") or "")

    @property
    def ui_action_types(self) -> list[str]:
        return [str(a.get("type") or "") for a in self.response.ui_actions]

    def prefill(self) -> dict[str, Any]:
        for action in self.response.ui_actions:
            if action.get("type") == "prefill_form":
                return dict(action.get("fields") or {})
        return {}

    def prefill_tab(self) -> str:
        for action in self.response.ui_actions:
            if action.get("type") == "prefill_form":
                return str(action.get("tab") or "")
        return ""


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if isinstance(payload, dict):
            self.events.append(payload)


@contextmanager
def capture_chat_events() -> Iterator[_Capture]:
    handler = _Capture()
    logger = logging.getLogger(_LOGGER_NAME)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def settings(**kwargs: Any) -> Settings:
    base: dict[str, Any] = {
        "gcp_project": "marketmaking-test",
        "chat_enabled": True,
        "chat_provider": "fake",
        "chat_model": "fake",
    }
    base.update(kwargs)
    return Settings(**base)


def _league(slug: str, sport: str, optic: str, tournament_id: str) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
                "source_league_id": optic,
            },
            {
                "sportsbook": "px",
                "enabled": True,
                "parser_profile": "px_generic_v1",
                "source_league_id": tournament_id,
                "settings": {"tournament_id": tournament_id},
            },
        ],
    )


def _rule(source_key: str, action: str, market: str | None) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"mr-{source_key.lower()}",
        league="atp",
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key=source_key,
        action=action,
        canonical_market_type=market,
        priority=100,
        enabled=True,
        confidence="manual",
    )


def eval_store() -> InMemoryStore:
    """Small rule set shared by every suite so fixtures stay authorable."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="atp",
                entity_type="player",
                canonical_key="SINNER",
                canonical_name="Jannik Sinner",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "E0133F3BCA247846",
                    },
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "SIN"},
                ],
            ),
            EntityRow(
                league="epl",
                entity_type="team",
                canonical_key="ARSENAL",
                canonical_name="Arsenal",
                aliases=[
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "ARS"}
                ],
            ),
        ],
        leagues=[
            _league("atp", "tennis", "atp", "1001"),
            _league("epl", "soccer", "england_-_premier_league", "1002"),
            _league("mlb", "baseball", "mlb", "1003"),
        ],
        market_rules=[
            _rule("GAME", "map", "moneyline"),
            _rule("SPREAD", "ignore", "point_spread"),
        ],
        activate=True,
    )
    return store


@contextmanager
def _stubbed(stubs: dict[str, Any]) -> Iterator[None]:
    """Replace live probes with fixture rows so suites stay offline."""
    patches = []
    if "crypto_probe" in stubs:
        row = stubs["crypto_probe"]
        patches.append(
            patch.object(probe_gap, "run_probe_crypto_gap", lambda *a, **k: {"ok": True, "results": [row]})
        )
    if "mapping_probe" in stubs:
        row = stubs["mapping_probe"]
        patches.append(
            patch.object(
                probe_gap,
                "probe_source_mapping",
                lambda *a, **k: {"ok": True, "results": [row]},
            )
        )
    if "book_probes" in stubs:
        rows = list(stubs["book_probes"])
        patches.append(patch.object(onboard_league, "probe_all_books_parallel", lambda *a, **k: rows))
    if "parser_gate" in stubs:
        gate = stubs["parser_gate"]
        patches.append(patch.object(onboard_league, "check_parser_profiles", lambda *a, **k: gate))
    if "optic_fixtures" in stubs:
        rows = list(stubs["optic_fixtures"])
        patches.append(
            patch.object(chat_optic_name, "cached_optic_fixtures", lambda *_a, **_k: rows)
        )
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


def run_turn(
    message: str,
    *,
    page: dict[str, Any] | None = None,
    conversation_id: str = "eval",
    store: InMemoryStore | None = None,
    bag_pending: dict[str, Any] | None = None,
    stubs: dict[str, Any] | None = None,
    **settings_kwargs: Any,
) -> TurnRecord:
    """Run one turn and return the response alongside its emitted events."""
    bag = session_bag().get_or_create(conversation_id)
    if bag_pending:
        from mappers.control_plane.chat_pending import pending_from_dict

        bag.pending = pending_from_dict(dict(bag_pending))
    with capture_chat_events() as cap, _stubbed(dict(stubs or {})):
        response = handle_chat_turn(
            ChatRequest(
                message=message,
                conversation_id=conversation_id,
                page_context=dict(page or {}),
            ),
            settings=settings(**settings_kwargs),
            store=store or eval_store(),
        )
    turns = [e for e in cap.events if e.get("event_type") == "mapping_chat_turn"]
    steps = [e for e in cap.events if e.get("event_type") == "mapping_chat_step"]
    return TurnRecord(response=response, turn=turns[-1] if turns else {}, steps=steps)


def load_fixture(name: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    return list(raw or [])
