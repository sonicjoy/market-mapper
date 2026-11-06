"""Suggest entity aliases from Optic fixtures/competitors (no LLM)."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from mappers.alias_kinds import alias_value, is_optic_id, optic_pin
from mappers.canonical_codes import fallback_code, toml_section_key
from mappers.control_plane.entity_types import match_entity_type
from mappers.control_plane.gsm_secret import access_secret

_OPTIC_BASE = "https://api.opticodds.com/api/v3/"
_DEFAULT_OPTIC_KEY_NAME = "opticodds_access_key"


def _entity_type_for_sport(sport: str) -> str:
    """Match-side type from Optic sport (tennis → team, not player)."""
    return match_entity_type("", sport=sport)


def _optic_headers() -> dict[str, str]:
    """Resolve Optic API key from env or Secret Manager."""
    api_key = (os.environ.get("OPTICODDS_API_KEY") or os.environ.get("OPTIC_API_KEY") or "").strip()
    if not api_key:
        name = (os.environ.get("OPTICODDS_SECRET_NAME") or _DEFAULT_OPTIC_KEY_NAME).strip()
        project = (os.environ.get("GCP_PROJECT") or "").strip()
        if not project:
            raise RuntimeError("GCP_PROJECT not set; cannot load Optic API key")
        api_key = access_secret(name, project)
    return {"accept": "application/json", "X-Api-Key": api_key}


def fetch_optic_fixtures(
    optic_league_id: str,
    *,
    horizon_hours: float = 96.0,
    headers_factory: Callable[[], dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch active Optic fixtures for one optic league id."""
    headers = (headers_factory or _optic_headers)()
    cutoff = datetime.now(UTC) + timedelta(hours=horizon_hours)
    start_date_before = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "league": optic_league_id,
        "start_date_before": start_date_before,
        "include_sportradar_id": "true",
        "page": "1",
    }
    response = requests.get(
        _OPTIC_BASE + "fixtures/active",
        params=params,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


def competitors_from_fixtures(fixtures: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Dedupe competitors from fixture payloads."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for game in fixtures:
        for side in ("home_competitors", "away_competitors"):
            for comp in game.get(side) or []:
                cid = str(comp.get("id") or "").strip()
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                out.append(
                    {
                        "optic_id": cid,
                        "name": str(comp.get("name") or "").strip() or cid,
                        "abbreviation": str(comp.get("abbreviation") or "").strip(),
                    }
                )
    out.sort(key=lambda c: c["name"].lower())
    return out


def _canonical_key(comp: dict[str, str], used: set[str]) -> str:
    """Optic's abbreviation when it is TOML-safe, else an invented code.

    Quotable abbreviations count as safe so the console proposes the same
    canonical key team_bootstrap would write, not a second entity for it.
    """
    abbr = (comp.get("abbreviation") or "").strip()
    if abbr and toml_section_key(abbr) is not None:
        return abbr
    optic_id = comp["optic_id"]
    try:
        return fallback_code(comp["name"], used, optic_id)
    except ValueError:
        return optic_id.replace("-", "")[:8].upper() or "X"


def _alias_payload(
    comp: dict[str, str],
    *,
    league: str,
    entity_type: str,
    canonical_key: str,
) -> dict[str, Any]:
    return {
        "kind": "entity_alias",
        "league": league.strip(),
        "canonical_key": canonical_key,
        "entity_type": entity_type,
        "canonical_name": comp["name"],
        "aliases": [optic_pin(comp["optic_id"])],
        "reassign": False,
    }


def _existing_optic_ids(store: Any, league: str) -> set[str]:
    """Optic competitor ids already pinned on this league."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return set()
    out: set[str] = set()
    for ent in store.entities_for(rid):
        if ent.league != league or ent.tombstone:
            continue
        for alias in ent.aliases or []:
            if is_optic_id(alias):
                out.add(alias_value(alias))
    return out


def filter_existing_aliases(
    suggestions: list[dict[str, Any]],
    *,
    existing_optic_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Drop competitors whose Optic id is already on the tip."""
    if not existing_optic_ids:
        return suggestions, 0
    kept: list[dict[str, Any]] = []
    skipped = 0
    for item in suggestions:
        payload = dict(item.get("payload") or {})
        aliases = list(payload.get("aliases") or [])
        oid = alias_value(aliases[0]) if aliases else ""
        if oid and oid in existing_optic_ids:
            skipped += 1
            continue
        kept.append(item)
    return kept, skipped


def build_alias_suggestions(
    *,
    league: str,
    sport: str,
    competitors: list[dict[str, str]],
) -> dict[str, Any]:
    """Turn competitors into cart-ready entity_alias suggestion payloads."""
    entity_type = _entity_type_for_sport(sport)
    used = {abbr for comp in competitors if (abbr := (comp.get("abbreviation") or "").strip())}

    suggestions: list[dict[str, Any]] = []
    for comp in competitors:
        canonical_key = _canonical_key(comp, used)
        used.add(canonical_key)
        suggestions.append(
            {
                "id": f"optic|{comp['optic_id']}",
                "label": f"{comp['name']} ({canonical_key}) ← optic:{comp['optic_id']}",
                "selected_default": True,
                "payload": _alias_payload(
                    comp,
                    league=league,
                    entity_type=entity_type,
                    canonical_key=canonical_key,
                ),
            }
        )
    warnings: list[str] = []
    if not suggestions:
        warnings.append("No competitors found in Optic fixtures for this league id / horizon.")
    return {
        "ok": bool(suggestions),
        "warnings": warnings,
        "entity_type": entity_type,
        "count": len(suggestions),
        "suggestions": suggestions,
    }


def _resolve_alias_fixtures(
    optic_league_id: str,
    *,
    horizon_hours: float,
    fixtures: list[dict[str, Any]] | None,
    headers_factory: Callable[[], dict[str, str]] | None,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Load fixtures for alias suggest; None fixtures means hard fail."""
    if not optic_league_id.strip():
        return None, ["optic_league_id is required to suggest aliases."]
    try:
        fx = (
            fixtures
            if fixtures is not None
            else fetch_optic_fixtures(
                optic_league_id.strip(),
                horizon_hours=horizon_hours,
                headers_factory=headers_factory,
            )
        )
    except Exception as exc:  # noqa: BLE001 — soft miss for trader UX
        return None, [f"Optic fetch failed: {exc}"]
    warnings: list[str] = []
    if not fx:
        warnings.append("No active Optic fixtures in horizon — try again closer to kickoff or widen horizon.")
    return fx, warnings


def _finalize_alias_suggestions(
    built: dict[str, Any],
    warnings: list[str],
    *,
    store: Any,
    league: str,
) -> dict[str, Any]:
    """Drop tip aliases and merge warnings into the built payload."""
    suggestions = list(built.get("suggestions") or [])
    if store is not None:
        suggestions, skipped = filter_existing_aliases(
            suggestions,
            existing_optic_ids=_existing_optic_ids(store, league.strip()),
        )
        if skipped:
            warnings.append(f"Skipped {skipped} alias(es) already on this league.")
        built["suggestions"] = suggestions
        built["count"] = len(suggestions)
    built["warnings"] = [*warnings, *built.get("warnings", [])]
    built["ok"] = bool(built.get("suggestions"))
    return built


def suggest_aliases_from_optic(
    *,
    league: str,
    sport: str,
    optic_league_id: str,
    horizon_hours: float = 96.0,
    fixtures: list[dict[str, Any]] | None = None,
    headers_factory: Callable[[], dict[str, str]] | None = None,
    store: Any = None,
) -> dict[str, Any]:
    """Fetch (or use provided) fixtures and suggest alias pins."""
    fx, warnings = _resolve_alias_fixtures(
        optic_league_id,
        horizon_hours=horizon_hours,
        fixtures=fixtures,
        headers_factory=headers_factory,
    )
    if fx is None:
        return {"ok": False, "warnings": warnings, "suggestions": []}
    built = build_alias_suggestions(
        league=league,
        sport=sport,
        competitors=competitors_from_fixtures(fx),
    )
    return _finalize_alias_suggestions(built, warnings, store=store, league=league)
