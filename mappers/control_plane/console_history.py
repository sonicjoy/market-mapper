"""Console rule history (on/off windows) — kept small for size guard."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.models import ValidationFailedError


def build_rule_history(
    store: Any,
    *,
    kind: str,
    natural_key: str | None = None,
    league: str | None = None,
    entity_type: str | None = None,
    canonical_key: str | None = None,
    sportsbook: str | None = None,
    source_key_type: str | None = None,
    source_key: str | None = None,
) -> dict[str, Any]:
    """On/off windows for one rule natural key."""
    table_kind = {
        "entities": "entity",
        "entity": "entity",
        "leagues": "league",
        "league": "league",
        "market_rules": "market_rule",
        "market_rule": "market_rule",
    }.get(kind, kind)
    key = _resolve_key(
        table_kind,
        natural_key=natural_key,
        league=league,
        entity_type=entity_type,
        canonical_key=canonical_key,
        sportsbook=sportsbook,
        source_key_type=source_key_type,
        source_key=source_key,
    )
    windows = store.rule_history(table_kind=table_kind, natural_key=key)
    return {
        "table_kind": table_kind,
        "natural_key": key,
        "windows": [
            {
                "effective_from": w.effective_from,
                "effective_to": w.effective_to,
                "enabled": w.enabled,
                "league": w.league,
            }
            for w in windows
        ],
    }


def _resolve_key(
    table_kind: str,
    *,
    natural_key: str | None,
    league: str | None,
    entity_type: str | None,
    canonical_key: str | None,
    sportsbook: str | None,
    source_key_type: str | None,
    source_key: str | None,
) -> str:
    if natural_key:
        return natural_key
    if table_kind == "entity":
        if not (league and entity_type and canonical_key):
            raise ValidationFailedError(
                "entity history needs league, entity_type, canonical_key",
                reason_code="bad_history_key",
                dry_run={},
            )
        return f"{league}|{entity_type}|{canonical_key}"
    if table_kind == "league":
        if not league:
            raise ValidationFailedError(
                "league history needs league",
                reason_code="bad_history_key",
                dry_run={},
            )
        return league
    if table_kind == "market_rule":
        if not (sportsbook and source_key_type and source_key):
            raise ValidationFailedError(
                "market_rule history needs sportsbook, source_key_type, source_key",
                reason_code="bad_history_key",
                dry_run={},
            )
        return f"{league or ''}|{sportsbook}|{source_key_type}|{source_key}"
    raise ValidationFailedError(
        "natural_key required",
        reason_code="bad_history_key",
        dry_run={},
    )
