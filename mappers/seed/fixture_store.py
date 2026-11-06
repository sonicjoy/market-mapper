"""Offline legacy-tip fixture loader for tests and local runs without BigQuery."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.seed.sot import SotSnapshot


def fixture_path() -> Path | None:
    """Return the offline fixture path only when ``MAPPING_SOT_FIXTURE`` is set.

    The test fixture file ships in the repo, so a "file exists" fallback would
    make every VM checkout classify from git instead of the activated BQ tip.
    Pytest sets the env in ``tests/conftest.py``.
    """
    raw = (os.environ.get("MAPPING_SOT_FIXTURE") or "").strip()
    return Path(raw) if raw else None


def _entity_row(raw: dict[str, Any]) -> EntityRow:
    aliases = [
        {
            "sportsbook": alias.get("sportsbook"),
            "alias_kind": alias.get("alias_kind"),
            "alias_value": alias.get("alias_value"),
            "enabled": alias.get("enabled", True),
        }
        for alias in raw.get("aliases") or []
    ]
    return EntityRow(
        league=str(raw["league"]),
        entity_type=str(raw["entity_type"]),
        canonical_key=str(raw["canonical_key"]),
        canonical_name=raw.get("canonical_name"),
        aliases=aliases,
        enabled=bool(raw.get("enabled", True)),
        notes=raw.get("notes"),
        tombstone=bool(raw.get("tombstone", False)),
    )


def _league_row(raw: dict[str, Any]) -> LeagueRow:
    exchanges = []
    for ex in raw.get("exchanges") or []:
        exchanges.append({
            "sportsbook": ex.get("sportsbook"),
            "enabled": ex.get("enabled", True),
            "parser_profile": ex.get("parser_profile"),
            "settings": dict(ex.get("settings") or {}),
            "source_league_id": ex.get("source_league_id"),
        })
    return LeagueRow(
        league=str(raw["league"]),
        sport=str(raw["sport"]),
        optic_league_id=str(raw.get("optic_league_id") or ""),
        extra_optic_league_ids=list(raw.get("extra_optic_league_ids") or []),
        fixture_source=str(raw.get("fixture_source") or "optic"),
        fixture_horizon_hours=float(raw.get("fixture_horizon_hours") or 96),
        enabled=bool(raw.get("enabled", True)),
        output_order=list(raw.get("output_order") or []),
        exchanges=exchanges,
        notes=raw.get("notes"),
        tombstone=bool(raw.get("tombstone", False)),
        settings=dict(raw.get("settings") or {}),
    )


def _optional_float(value: Any) -> float | None:
    """Missing or blank line offset stays null."""
    if value is None or value == "":
        return None
    return float(value)


def _optional_text(value: Any) -> str | None:
    """Missing or blank yes-side stays null."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    """Missing side-swap stays null so it is not a flip."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        return None
    return bool(value)


def _market_rule_row(raw: dict[str, Any]) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=str(raw["rule_id"]),
        league=raw.get("league"),
        sportsbook=str(raw["sportsbook"]),
        rule_kind=str(raw.get("rule_kind") or "taxonomy"),
        source_key_type=str(raw["source_key_type"]),
        source_key=str(raw["source_key"]),
        action=str(raw["action"]),
        canonical_market_type=raw.get("canonical_market_type"),
        priority=int(raw.get("priority") or 100),
        enabled=bool(raw.get("enabled", True)),
        confidence=str(raw.get("confidence") or "id_verified"),
        match_operator=str(raw.get("match_operator") or "exact"),
        notes=raw.get("notes"),
        tombstone=bool(raw.get("tombstone", False)),
        line_offset=_optional_float(raw.get("line_offset")),
        yes_side=_optional_text(raw.get("yes_side")),
        side_swap=_optional_bool(raw.get("side_swap")) if "side_swap" in raw else None,
        official_description=_optional_text(raw.get("official_description")),
        citation_url=_optional_text(raw.get("citation_url")),
        rule_group_id=_optional_text(raw.get("rule_group_id")),
        market_family=_optional_text(raw.get("market_family")),
        settlement_note=_optional_text(raw.get("settlement_note")),
    )


def load_fixture(path: Path | None = None) -> SotSnapshot:
    """Load a coalesced tip snapshot from a JSON fixture file."""
    target = path or fixture_path()
    if target is None or not target.is_file():
        raise FileNotFoundError(
            "No SoT fixture found — set MAPPING_SOT_FIXTURE"
        )
    doc = json.loads(target.read_text(encoding="utf-8"))
    return SotSnapshot(
        rule_set_id=str(doc["rule_set_id"]),
        entities=[_entity_row(row) for row in doc.get("entities") or []],
        market_rules=[_market_rule_row(row) for row in doc.get("market_rules") or []],
        leagues=[_league_row(row) for row in doc.get("leagues") or []],
    )


def write_fixture(snap: SotSnapshot, path: Path) -> None:
    """Persist a SotSnapshot to JSON for offline tests."""
    payload = {
        "rule_set_id": snap.rule_set_id,
        "entities": [asdict(row) for row in snap.entities],
        "market_rules": [asdict(row) for row in snap.market_rules],
        "leagues": [asdict(row) for row in snap.leagues],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
