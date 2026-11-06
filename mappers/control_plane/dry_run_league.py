"""Thin dry-run for mapping_league proposals."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.dry_run_already import (
    league_already_live,
    noop_blockers,
    resolved_enabled,
    resolved_extra_optic_ids,
    resolved_fixture_horizon,
    resolved_output_order,
)
from mappers.control_plane.entity_types import match_entity_type
from mappers.control_plane.entry import league_label
from mappers.control_plane.models import MappingLeaguePayload
from mappers.control_plane.store import LeagueRow
from mappers.seed.fixture_sources import (
    FIXTURE_SOURCE_SYNTHETIC,
    KNOWN_FIXTURE_SOURCES,
)
from mappers.seed.league_meta import league_settings_from_row, merge_league_meta_into_exchanges
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK
from mappers.seed.profiles import DEFAULT_PROFILES, PARSER_PROFILE_REGISTRY


def _known_profile(league: str, sportsbook: str, profile: str) -> bool:
    """True when profile is registered or a known default."""
    registered = PARSER_PROFILE_REGISTRY.get(league, {}).get(sportsbook)
    if registered == profile:
        return True
    return DEFAULT_PROFILES.get(sportsbook) == profile


def _required_field_blockers(payload: MappingLeaguePayload) -> list[str]:
    """Hard-require league / sport / optic id / exchanges / fixture_source."""
    blockers: list[str] = []
    if not payload.league.strip():
        blockers.append("league slug is required")
    if not payload.sport.strip():
        blockers.append("sport is required")
    if not payload.optic_league_id.strip():
        blockers.append("optic_league_id is required")
    if payload.fixture_source not in KNOWN_FIXTURE_SOURCES:
        blockers.append(f"fixture_source must be one of {sorted(KNOWN_FIXTURE_SOURCES)}")
    if not payload.exchanges:
        blockers.append("at least one exchange is required")
    return blockers


def _profile_blockers(payload: MappingLeaguePayload) -> list[str]:
    """Fail closed when an enabled exchange uses an unknown parser_profile."""
    blockers: list[str] = []
    for ex in payload.exchanges:
        if ex.enabled and not _known_profile(payload.league, ex.sportsbook, ex.parser_profile):
            blockers.append(
                f"needs_code: no known parser_profile {ex.parser_profile!r} for {payload.league}/{ex.sportsbook}"
            )
    return blockers


def _huddle_blockers(payload: MappingLeaguePayload) -> list[str]:
    """Huddle needs its NFL competition uuid to harvest anything."""
    huddle = next(
        (ex for ex in payload.exchanges if ex.sportsbook == "huddle" and ex.enabled),
        None,
    )
    if huddle is None:
        return []
    cid = (
        str(huddle.source_league_id or "").strip()
        or str((huddle.settings or {}).get("competition_id") or "").strip()
    )
    if cid:
        return []
    return ["huddle needs competition_id (source_league_id, e.g. NFL uuid)"]


def _poly_usa_blockers(payload: MappingLeaguePayload) -> list[str]:
    """Polymarket US needs its inner league code to harvest anything."""
    usa = next(
        (ex for ex in payload.exchanges if ex.sportsbook == POLY_USA_BOOK and ex.enabled),
        None,
    )
    if usa is None:
        return []
    code = (
        str(usa.source_league_id or "").strip()
        or str(
            (usa.settings or {}).get("slug_prefix") or "",
        ).strip()
    )
    if code:
        return []
    return ["polymarket_usa needs its inner US league code (source_league_id, e.g. 'cfb' for ncaaf)"]


def _kalshi_exchange_warnings(payload: MappingLeaguePayload) -> list[str]:
    """Kalshi maps from its own typed fields; a tip Kalshi exchange row is inert."""
    if not any(ex.sportsbook == "kalshi" for ex in payload.exchanges):
        return []
    return ["kalshi exchange rows on the tip are ignored: Kalshi maps from its own typed fields"]


def _clone_blockers(payload: MappingLeaguePayload, *, existing: set[str], updating: bool) -> list[str]:
    """Validate clone_market_rules_from against the tip snapshot."""
    blockers: list[str] = []
    clone_from = payload.clone_market_rules_from
    if clone_from and clone_from not in existing:
        blockers.append(f"clone_market_rules_from {clone_from!r} not in snapshot")
    if updating and clone_from:
        blockers.append("clone_market_rules_from is only valid when adding a new league")
    return blockers


def thin_dry_run_league(
    leagues: list[LeagueRow],
    payload: MappingLeaguePayload,
) -> dict[str, Any]:
    """Fail closed on unknown parser profiles; allow update of existing leagues."""
    by_key = {row.league: row for row in leagues}
    updating = payload.league in by_key
    already = league_already_live(by_key.get(payload.league), payload)
    change_count = 0 if already else 1
    blockers: list[str] = []
    warnings: list[str] = [
        "Writes the mapping-rules snapshot. Approve/activate updates live classify from the BQ tip.",
    ]
    if already:
        warnings.append(f"Already live: {league_label(payload.league)} is already on the current rules.")
    elif updating:
        warnings.append(f"Updating existing league {payload.league!r}.")
    blockers.extend(_required_field_blockers(payload))
    blockers.extend(_profile_blockers(payload))
    blockers.extend(_poly_usa_blockers(payload))
    blockers.extend(_huddle_blockers(payload))
    blockers.extend(_clone_blockers(payload, existing=set(by_key), updating=updating))
    blockers.extend(noop_blockers(change_count=change_count, item_count=1))
    warnings.extend(_kalshi_exchange_warnings(payload))
    if payload.fixture_source == FIXTURE_SOURCE_SYNTHETIC:
        warnings.append(
            "Synthetic leagues stay out of mapper LEAGUES; onboard the series "
            "in synthetic/series.toml so the job and snapshot agree."
        )
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "league": payload.league,
        "exchange_count": len(payload.exchanges),
        "updating": updating,
        "change_count": change_count,
        "item_count": 1,
    }


def apply_league_payload(
    leagues: list[LeagueRow],
    payload: MappingLeaguePayload,
) -> list[LeagueRow]:
    """Append a new league or replace an existing league key."""
    existing = next((row for row in leagues if row.league == payload.league), None)
    settings = _merged_league_settings(existing, payload)
    row = LeagueRow(
        league=payload.league,
        sport=payload.sport,
        optic_league_id=payload.optic_league_id,
        extra_optic_league_ids=resolved_extra_optic_ids(payload.extra_optic_league_ids, existing),
        fixture_source=payload.fixture_source,
        fixture_horizon_hours=resolved_fixture_horizon(payload.fixture_horizon_hours, existing),
        enabled=resolved_enabled(payload.enabled, existing),
        output_order=resolved_output_order(payload.output_order, existing),
        exchanges=merge_league_meta_into_exchanges(
            [ex.model_dump(mode="json") for ex in payload.exchanges],
            settings,
        ),
        notes=payload.notes,
        settings=settings,
    )
    out = [lg for lg in leagues if lg.league != payload.league]
    out.append(row)
    return out


def _merged_league_settings(
    existing: LeagueRow | None,
    payload: MappingLeaguePayload,
) -> dict[str, Any]:
    """Keep the live entity_type; new leagues use the match-side default."""
    settings = payload.league_settings()
    if existing is None:
        settings["entity_type"] = match_entity_type(payload.league, sport=payload.sport)
        return settings
    prior = dict(existing.settings or league_settings_from_row(existing))
    merged = dict(prior)
    merged.update(settings)
    raw = str(prior.get("entity_type") or "")
    if raw in ("team", "player", "fighter"):
        merged["entity_type"] = raw
    return merged
