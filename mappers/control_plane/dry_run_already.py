"""Already-live helpers for verify / thin dry-run."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.models import MappingLeaguePayload
from mappers.control_plane.store import LeagueRow
from mappers.shared import FIXTURE_HORIZON_HOURS

NOOP_BLOCKER = "All proposed changes already match current rules."
_BOOK = {"crypto.com": "crypto.com", "optic": "Optic"}


def noop_blockers(*, change_count: int, item_count: int) -> list[str]:
    """Block when every proposed item already matches the tip."""
    if item_count > 0 and change_count == 0:
        return [NOOP_BLOCKER]
    return []


def rule_effect(action: str | None, canonical: str | None) -> tuple[str, str]:
    """Mapping effect: ignore vs map-to-canonical."""
    act = (action or "").strip() or "ignore"
    canon = (canonical or "").strip()
    if act == "ignore":
        return ("ignore", "")
    return (act, canon)


def _league_name(league: str) -> str:
    """Display label without importing entry (avoids a dry-run import cycle)."""
    return league.replace("_", " ").title() if league else "?"


def _book(sportsbook: str) -> str:
    """Display label for a sportsbook id."""
    return _BOOK.get(sportsbook, sportsbook or "unknown")


def _state(effect: tuple[str, str]) -> str:
    """Human mapping state."""
    if effect[0] == "ignore":
        return "ignored"
    return f"mapped as {effect[1]}"


def rule_already_msg(sportsbook: str, source_key: str, league: str, effect: tuple[str, str]) -> str:
    """Warning when a market-rule pin matches the tip."""
    return f"Already live: {_book(sportsbook)} {source_key} on {_league_name(league)} is already {_state(effect)}."


def rule_change_msg(
    sportsbook: str,
    source_key: str,
    league: str,
    before: tuple[str, str],
    after: tuple[str, str],
) -> str:
    """Warning when a market-rule pin changes the tip."""
    return (
        f"{_book(sportsbook)} {source_key} on {_league_name(league)} is {_state(before)}; "
        f"this sets it to {_state(after)}."
    )


def _ex_norm(ex: dict[str, Any]) -> tuple[Any, ...]:
    """Stable exchange compare key."""
    raw = ex.get("settings")
    settings = raw if isinstance(raw, dict) else {}
    return (
        str(ex.get("sportsbook") or ""),
        bool(ex.get("enabled", True)),
        str(ex.get("parser_profile") or ""),
        str(ex.get("source_league_id") or ""),
        tuple(sorted((str(k), str(v)) for k, v in settings.items())),
    )


def resolved_fixture_horizon(hours: float | None, existing: LeagueRow | None) -> float:
    """Keep the tip window when the pin omitted horizon; else mapper default."""
    if hours is not None:
        return float(hours)
    if existing is not None:
        return float(existing.fixture_horizon_hours)
    return FIXTURE_HORIZON_HOURS


def resolved_extra_optic_ids(
    ids: list[str] | None, existing: LeagueRow | None
) -> list[str]:
    """Keep tip extra Optic ids when the pin omitted them."""
    if ids is not None:
        return list(ids)
    if existing is not None:
        return list(existing.extra_optic_league_ids)
    return []


def resolved_output_order(
    order: list[str] | None, existing: LeagueRow | None
) -> list[str]:
    """Keep tip output_order when the pin omitted it."""
    if order is not None:
        return list(order)
    if existing is not None:
        return list(existing.output_order)
    return []


def resolved_enabled(flag: bool | None, existing: LeagueRow | None) -> bool:
    """Keep tip enabled when the pin omitted it."""
    if flag is not None:
        return bool(flag)
    if existing is not None:
        return bool(existing.enabled)
    return True


def _league_effect(
    *,
    league: str,
    sport: str,
    optic_league_id: str,
    extra_optic_league_ids: list[str],
    fixture_source: str,
    fixture_horizon_hours: float,
    enabled: bool,
    output_order: list[str],
    exchanges: list[dict[str, Any]],
) -> tuple[Any, ...]:
    """Fields that change live classify for a league row."""
    return (
        league,
        sport,
        optic_league_id,
        tuple(sorted(extra_optic_league_ids)),
        fixture_source,
        float(fixture_horizon_hours),
        enabled,
        tuple(output_order),
        tuple(sorted(_ex_norm(ex) for ex in exchanges)),
    )


def league_already_live(row: LeagueRow | None, payload: MappingLeaguePayload) -> bool:
    """True when the league pin would not change the tip row."""
    if row is None or payload.clone_market_rules_from or payload.market_rules:
        return False
    current = _league_effect(
        league=row.league,
        sport=row.sport,
        optic_league_id=row.optic_league_id,
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=row.fixture_source,
        fixture_horizon_hours=row.fixture_horizon_hours,
        enabled=row.enabled,
        output_order=list(row.output_order),
        exchanges=list(row.exchanges),
    )
    proposed = _league_effect(
        league=payload.league,
        sport=payload.sport,
        optic_league_id=payload.optic_league_id,
        extra_optic_league_ids=resolved_extra_optic_ids(payload.extra_optic_league_ids, row),
        fixture_source=payload.fixture_source,
        fixture_horizon_hours=resolved_fixture_horizon(payload.fixture_horizon_hours, row),
        enabled=resolved_enabled(payload.enabled, row),
        output_order=resolved_output_order(payload.output_order, row),
        exchanges=[ex.model_dump(mode="json") for ex in payload.exchanges],
    )
    return current == proposed
