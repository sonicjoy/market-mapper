"""League-level settings stored on the optic exchange row in BigQuery.

``mapping_leagues.settings`` exists in the Terraform schema but is not yet
deployed on every environment. Until the column lands, ``entity_type``,
``alias_enforcement``, and ``runshop_enabled`` round-trip on the optic
exchange ``settings`` blob so proposals and the offline fixture stay aligned.
"""

from __future__ import annotations

from typing import Any

_LEAGUE_META_KEYS = ("entity_type", "alias_enforcement", "runshop_enabled")
_MATCH_SIDE = frozenset({"team", "fighter"})


def invert_entity_type(league: str, settings: dict[str, Any] | None = None) -> str:
    """Classify invert type: explicit settings, else UFC fighter / everyone team.

    Boxing name fallback is intentionally off until retag writes
    ``entity_type=fighter`` — leftover Kalshi codes still live on ``team``.
    """
    raw = str((settings or {}).get("entity_type") or "").strip().lower()
    if raw in _MATCH_SIDE:
        return raw
    return "fighter" if league == "ufc" else "team"


def league_settings_from_exchanges(exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    """Read league meta keys from the optic exchange settings, if present."""
    for ex in exchanges:
        if ex.get("sportsbook") != "optic":
            continue
        settings = ex.get("settings") or {}
        meta = {key: settings[key] for key in _LEAGUE_META_KEYS if key in settings}
        if meta:
            return meta
    return {}


def league_settings_from_row(row: Any) -> dict[str, Any]:
    """Return league settings from the row or its optic exchange pin."""
    direct = dict(getattr(row, "settings", None) or {})
    if direct:
        return direct
    exchanges = getattr(row, "exchanges", None) or []
    return league_settings_from_exchanges(exchanges)


def merge_league_meta_into_exchanges(
    exchanges: list[dict[str, Any]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Copy league meta keys onto the optic exchange settings dict."""
    meta = {key: settings[key] for key in _LEAGUE_META_KEYS if key in settings}
    if not meta:
        return exchanges
    out: list[dict[str, Any]] = []
    found_optic = False
    for ex in exchanges:
        row = dict(ex)
        if row.get("sportsbook") == "optic":
            merged = dict(row.get("settings") or {})
            merged.update(meta)
            row["settings"] = merged
            found_optic = True
        out.append(row)
    if not found_optic:
        out.append(
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
                "settings": dict(meta),
            },
        )
    return out


def runshop_enabled_on_row(row: Any) -> bool:
    """True when runshop is enabled via league meta or a runshop exchange row."""
    if league_settings_from_row(row).get("runshop_enabled"):
        return True
    for ex in getattr(row, "exchanges", None) or []:
        if ex.get("sportsbook") == "runshop" and ex.get("enabled", True):
            return True
    return False
