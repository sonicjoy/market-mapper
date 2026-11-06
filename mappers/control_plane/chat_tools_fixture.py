"""Fixture coverage tool: vs-string / id / symbol → tip side mapping."""

from __future__ import annotations

import re
from typing import Any

from mappers.alias_kinds import is_optic_id
from mappers.control_plane import chat_tools_probe as probe
from mappers.control_plane.chat_console import coverage_href, show_on_console
from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap

_VS = re.compile(r"\s+vs\.?\s+", re.I)
_HEX16 = re.compile(r"^[A-Fa-f0-9]{16}$")
_CRYPTO = re.compile(r"^NX\.", re.I)


def fixture_coverage(store: Any, paste: str, *, league: str = "") -> dict[str, Any]:
    """Resolve a fixture paste and report each side mapped vs missing on tip."""
    raw = (paste or "").strip()
    if not raw:
        return {"ok": False, "error": "empty_fixture"}
    kind, resolved = _resolve(store, raw, league.strip())
    sides = list(resolved.get("sides") or [])
    tip_sides = [_tip_side(store, side, league.strip() or resolved.get("league") or "") for side in sides]
    missing = [s for s in tip_sides if not s.get("mapped")]
    league_slug = str(resolved.get("league") or league or "")
    fixture_id = str(resolved.get("fixture_id") or "")
    return {
        "ok": True,
        "paste_kind": kind,
        "resolved": {k: v for k, v in resolved.items() if k != "sides"},
        "sides": tip_sides,
        "all_mapped": bool(tip_sides) and not missing,
        "missing": missing,
        "offer_pin_sides": missing,
        "ui_actions": show_on_console(
            navigate=coverage_href(league=league_slug, fixture=fixture_id),
        ),
        "message": _summary(tip_sides, missing),
    }


def _resolve(store: Any, raw: str, league: str) -> tuple[str, dict[str, Any]]:
    if _HEX16.match(raw):
        return "optic_fixture_id", _from_optic_id(raw)
    if _CRYPTO.match(raw):
        return "crypto_symbol", _from_crypto(store, raw, league)
    if _VS.search(raw):
        return "vs_string", _from_vs(raw, league)
    return "opaque", {"sides": [{"name": raw, "id": ""}], "league": league}


def _from_optic_id(fixture_id: str) -> dict[str, Any]:
    hit = probe.probe_optic_fixture(fixture_id)
    home = str(hit.get("home") or "")
    away = str(hit.get("away") or "")
    return {
        "fixture_id": fixture_id,
        "seen": bool(hit.get("seen")),
        "sides": [{"name": home, "id": ""}, {"name": away, "id": ""}],
        "start_date": hit.get("start_date"),
    }


def _from_crypto(store: Any, symbol: str, league: str) -> dict[str, Any]:
    out = run_probe_crypto_gap(store, {"symbol": symbol, "league": league or None})
    rows = list(out.get("results") or out.get("probes") or [])
    row = rows[0] if rows else out
    optic = row.get("optic") or {}
    return {
        "symbol": symbol,
        "league": row.get("league") or league,
        "sides": [
            {"name": str(optic.get("home") or ""), "id": str(optic.get("home_id") or "")},
            {"name": str(optic.get("away") or ""), "id": str(optic.get("away_id") or "")},
        ],
    }


def _from_vs(raw: str, league: str) -> dict[str, Any]:
    parts = _VS.split(raw, maxsplit=1)
    left = parts[0].strip() if parts else raw
    right = parts[1].strip() if len(parts) > 1 else ""
    return {
        "league": league,
        "sides": [{"name": left, "id": ""}, {"name": right, "id": ""}],
    }


def _tip_side(store: Any, side: dict[str, Any], league: str) -> dict[str, Any]:
    name = str(side.get("name") or "").strip()
    oid = str(side.get("id") or "").strip()
    hit = _find_entity(store, name=name, optic_id=oid, league=league)
    return {
        "name": name,
        "optic_id": oid,
        "mapped": hit is not None,
        "league": (hit or {}).get("league") or league,
        "canonical_key": (hit or {}).get("canonical_key"),
        "canonical_name": (hit or {}).get("canonical_name"),
    }


def _find_entity(
    store: Any, *, name: str, optic_id: str, league: str
) -> dict[str, Any] | None:
    rid = store.current_rule_set_id
    if not rid:
        return None
    league_l = league.lower()
    name_l = name.lower()
    for ent in store.entities_for(rid):
        if league_l and ent.league.lower() != league_l:
            continue
        if optic_id and any(is_optic_id(a, optic_id) for a in ent.aliases):
            return _ent_dict(ent)
        if name_l and (
            name_l == (ent.canonical_name or "").lower()
            or name_l == ent.canonical_key.lower()
            or any(name_l == str(a.get("alias_value") or "").lower() for a in ent.aliases)
        ):
            return _ent_dict(ent)
    return None


def _ent_dict(ent: Any) -> dict[str, Any]:
    return {
        "league": ent.league,
        "canonical_key": ent.canonical_key,
        "canonical_name": ent.canonical_name or ent.canonical_key,
    }


def _summary(sides: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    if not sides:
        return "Could not resolve fixture sides."
    if not missing:
        names = ", ".join(f"`{s.get('canonical_key') or s.get('name')}`" for s in sides)
        return f"Both sides mapped on tip: {names}."
    miss = ", ".join(f"`{s.get('name') or s.get('optic_id')}`" for s in missing)
    return f"Unmapped side(s): {miss}. Call offer_pin per side to stage pins."
