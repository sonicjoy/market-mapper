"""Mapper Chat tools — allow-listed BQ reads, probes, proposes, and suggests."""

from __future__ import annotations

import json
from typing import Any

from mappers.control_plane import chat_tools_fixture as fixture
from mappers.control_plane import chat_tools_lookup as lookup
from mappers.control_plane import chat_tools_propose as propose
from mappers.control_plane.chat_console import ConsolePage, read_console_snapshot, show_on_console
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.chat_tools_skill import (
    check_parser_profiles,
    probe_exchange_league,
    stage_pin,
)
from mappers.control_plane.entry import LiveLookup, NullLiveLookup
from mappers.control_plane.suggest_aliases import suggest_aliases_from_optic
from mappers.control_plane.suggest_markets import suggest_market_rules
from mappers.control_plane.sweep_crypto_ids import DEFAULT_HARVEST_DAYS, run_sweep_crypto_ids

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_rules",
        "description": ("Search tip entities, leagues, or market rules. Opens Rules with the same q."),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["entities", "leagues", "market_rules"]},
                "q": {"type": "string"},
                "sportsbook": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["kind", "q"],
        },
    },
    {
        "name": "fixture_coverage",
        "description": (
            "Has this fixture been mapped? Opens Coverage. Paste team vs team, "
            "Optic fixture id, or crypto NX symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {"paste": {"type": "string"}, "league": {"type": "string"}},
            "required": ["paste"],
        },
    },
    {
        "name": "probe_crypto_gap",
        "description": "Read-only crypto.com mapping-gap probe (cap 5 symbols).",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "symbols": {"type": "array", "items": {"type": "string"}},
                "league": {"type": "string"},
            },
        },
    },
    {
        "name": "suggest_aliases",
        "description": "Suggest Optic competitor aliases for a tip league.",
        "parameters": {
            "type": "object",
            "properties": {"league": {"type": "string"}, "horizon_hours": {"type": "number"}},
            "required": ["league"],
        },
    },
    {
        "name": "suggest_markets",
        "description": "Suggest market rules for enabled sportsbooks (read-only spine).",
        "parameters": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "sport": {"type": "string"},
                "optic_league_id": {"type": "string"},
                "sportsbooks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["league"],
        },
    },
    {
        "name": "propose_markets",
        "description": (
            "Stage mapping_market_rules onto the cart (same kernel as Editor). "
            "Do not call for Polymarket US markets the parser cannot parse."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "sportsbook": {"type": "string"},
                "market": {"type": "string"},
                "flip_ignores": {"type": "boolean"},
            },
            "required": ["league", "sportsbook"],
        },
    },
    {
        "name": "check_parser_profiles",
        "description": "needs_code gate: parser profiles registered for a league slug.",
        "parameters": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "sportsbooks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["league"],
        },
    },
    {
        "name": "probe_exchange_league",
        "description": "One live-evidence probe for league onboard on a single book.",
        "parameters": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "sportsbook": {"type": "string"},
                "optic_league_id": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["league", "sportsbook"],
        },
    },
    {
        "name": "stage_pin",
        "description": (
            "Stage an entity_alias add or delete onto the pending cart. "
            "Set remove true to delete a live alias (same verify as Editor)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "league": {"type": "string"},
                "sportsbook": {"type": "string"},
                "code": {"type": "string"},
                "canonical_key": {"type": "string"},
                "canonical_name": {"type": "string"},
                "entity_type": {"type": "string"},
                "alias_kind": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "boolean"},
            },
            "required": ["league", "sportsbook", "code"],
        },
    },
    {
        "name": "read_console",
        "description": ("Return the trader console snapshot (path, tab, entry, rules, coverage, unmapped, cart)."),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "show_on_console",
        "description": (
            "Emit navigate/switch_tab/prefill_form/rules_filter ui_actions. "
            "Paths: /entry Editor, /cart Cart, /review Proposed, /rules Rules, "
            "/coverage Coverage, /unmapped Unmapped Why. "
            "Market tab prefill must set canonical_market_type (the Editor "
            "dropdown); do not put the canonical only in entity_name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "navigate": {"type": "string"},
                "tab": {"type": "string"},
                "prefill": {
                    "type": "object",
                    "properties": {
                        "tab": {"type": "string"},
                        "mode": {"type": "string"},
                        "league": {"type": "string"},
                        "sportsbook": {"type": "string"},
                        "source_key": {"type": "string"},
                        "source_key_type": {"type": "string"},
                        "action": {"type": "string"},
                        "canonical_market_type": {"type": "string"},
                    },
                },
                "rules_kind": {"type": "string"},
                "rules_q": {"type": "string"},
            },
        },
    },
]


class ChatToolContext:
    """Bound store + live lookup + optional session bag for cart tools."""

    def __init__(
        self,
        store: Any,
        live: LiveLookup | None = None,
        bag: ChatSession | None = None,
        page: ConsolePage | None = None,
        evidence_fn: Any = None,
    ) -> None:
        self.store = store
        self.live = live or NullLiveLookup()
        self.bag = bag
        self.page = page or ConsolePage()
        self.evidence_fn = evidence_fn

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one allow-listed tool."""
        fn = self._dispatch().get(name)
        return fn(args) if fn else {"error": f"unknown_tool:{name}"}

    @staticmethod
    def scoped_schemas(names: tuple[str, ...]) -> list[dict[str, Any]]:
        """Schemas for one skill's toolset, so no task sees the whole inventory."""
        wanted = set(names)
        return [row for row in TOOL_SCHEMAS if row["name"] in wanted]

    def _dispatch(self) -> dict[str, Any]:
        out = {}
        out.update(self._lookup_dispatch())
        out.update(self._propose_dispatch())
        out.update(self._probe_dispatch())
        out.update(self._skill_dispatch())
        return out

    def _skill_dispatch(self) -> dict[str, Any]:
        page = self.page
        return {
            "lookup_rules": lambda a: lookup.lookup_rules(
                self.store,
                str(a.get("kind") or "entities"),
                str(a.get("q") or ""),
                sportsbook=str(a["sportsbook"]) if a.get("sportsbook") else None,
                limit=int(a.get("limit") or 20),
            ),
            "check_parser_profiles": lambda a: check_parser_profiles(
                self.store,
                str(a.get("league") or ""),
                list(a.get("sportsbooks") or []) or None,
            ),
            "probe_exchange_league": lambda a: probe_exchange_league(
                self.store,
                str(a.get("league") or ""),
                str(a.get("sportsbook") or ""),
                optic_league_id=str(a.get("optic_league_id") or ""),
                sport=str(a.get("sport") or ""),
            ),
            "stage_pin": self._stage_pin_args,
            "read_console": lambda _a: read_console_snapshot(page),
            "show_on_console": self._show_console,
        }

    def _stage_pin_args(self, a: dict[str, Any]) -> dict[str, Any]:
        """Unpack Chat stage_pin args onto the shared kernel."""
        return stage_pin(
            self,
            league=str(a.get("league") or ""),
            sportsbook=str(a.get("sportsbook") or ""),
            code=str(a.get("code") or ""),
            canonical_key=str(a.get("canonical_key") or ""),
            canonical_name=str(a.get("canonical_name") or ""),
            entity_type=str(a.get("entity_type") or "team"),
            alias_kind=str(a.get("alias_kind") or "code"),
            evidence_refs=list(a.get("evidence_refs") or []),
            remove=bool(a.get("remove")),
        )

    def _show_console(self, a: dict[str, Any]) -> dict[str, Any]:
        """Emit console navigate/prefill actions."""
        actions = show_on_console(
            navigate=a.get("navigate"),
            tab=a.get("tab"),
            prefill=a.get("prefill"),
            rules_kind=a.get("rules_kind"),
            rules_q=a.get("rules_q"),
        )
        return {"ok": True, "ui_actions": actions}

    def _lookup_dispatch(self) -> dict[str, Any]:
        return {
            "fixture_coverage": lambda a: fixture.fixture_coverage(
                self.store, str(a.get("paste") or ""), league=str(a.get("league") or "")
            ),
        }

    def _propose_dispatch(self) -> dict[str, Any]:
        return {
            "propose_league": lambda a: self._propose_league(a),
            "propose_markets": lambda a: self._propose_markets(a),
            "suggest_aliases": lambda a: self._suggest_aliases(str(a.get("league") or ""), a.get("horizon_hours")),
            "sweep_crypto_ids": lambda a: run_sweep_crypto_ids(
                self.store,
                str(a.get("league") or ""),
                days=int(a.get("days") or DEFAULT_HARVEST_DAYS),
            ),
            "suggest_markets": lambda a: self._suggest_markets(a),
        }

    def _probe_dispatch(self) -> dict[str, Any]:
        return {
            "probe_crypto_gap": lambda a: run_probe_crypto_gap(self.store, a),
        }

    def _need_bag(self) -> ChatSession | dict[str, Any]:
        if self.bag is None:
            return {"ok": False, "error": "session bag required"}
        return self.bag

    def _propose_league(self, args: dict[str, Any]) -> dict[str, Any]:
        bag = self._need_bag()
        if isinstance(bag, dict):
            return bag
        return propose.propose_league(
            self.store,
            bag,
            league=str(args.get("league") or ""),
            sportsbook=str(args.get("sportsbook") or ""),
            sport=str(args.get("sport") or ""),
            optic_league_id=str(args.get("optic_league_id") or ""),
        )

    def _propose_markets(self, args: dict[str, Any]) -> dict[str, Any]:
        bag = self._need_bag()
        if isinstance(bag, dict):
            return bag
        return propose.propose_markets(
            self.store,
            bag,
            league=str(args.get("league") or ""),
            sportsbook=str(args.get("sportsbook") or ""),
            market=str(args.get("market") or ""),
            flip_ignores=bool(args.get("flip_ignores")),
        )

    def _suggest_aliases(self, league: str, horizon: Any) -> dict[str, Any]:
        tip = self._league_on_tip(league.strip())
        if tip is None:
            return {"ok": False, "warnings": [f"league not on tip: {league}"], "suggestions": []}
        hours = float(horizon) if horizon is not None else float(tip.fixture_horizon_hours or 96)
        return suggest_aliases_from_optic(
            league=tip.league,
            sport=tip.sport,
            optic_league_id=tip.optic_league_id,
            horizon_hours=hours,
            store=self.store,
        )

    def _suggest_markets(self, args: dict[str, Any]) -> dict[str, Any]:
        league = str(args.get("league") or "").strip()
        tip = self._league_on_tip(league)
        rid = self.store.current_rule_set_id
        tip_leagues = self.store.leagues_for(rid) if rid else []
        books = args.get("sportsbooks")
        if not books and tip is not None:
            books = [e.get("sportsbook") for e in tip.exchanges if e.get("enabled")]
        return suggest_market_rules(
            league=league,
            optic_league_id=str(args.get("optic_league_id") or (tip.optic_league_id if tip else "")),
            sport=str(args.get("sport") or (tip.sport if tip else "")),
            sportsbooks=list(books or ["optic"]),
            tip_leagues=tip_leagues,
            store=self.store,
        )

    def _league_on_tip(self, league: str):
        rid = self.store.current_rule_set_id
        if not rid:
            return None
        key = league.strip().lower()
        for row in self.store.leagues_for(rid):
            if row.league.lower() == key:
                return row
        return None


def tool_result_json(result: dict[str, Any]) -> str:
    """Compact JSON for tool messages (omit bulky ui_actions echoes optionally)."""
    return json.dumps(result, default=str, separators=(",", ":"))
