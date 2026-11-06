"""mapping_league payloads for Huddle NFL harvest (enable / competition pin)."""

from __future__ import annotations

from typing import Any, Literal

from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.profiles import DEFAULT_PROFILES
from mappers.vocab.football_huddle import NFL_COMPETITION_ID

HUDDLE_BOOK = "huddle"
HUDDLE_NOTE = "pipeline gap-fix: enable Huddle NFL competition pin"

_ENTITY = frozenset({"team", "player", "fighter"})
_ENFORCE = frozenset({"raise", "warn"})


def huddle_competition_id(row: LeagueRow) -> str | None:
    """Read the pinned Huddle competition uuid from a tip league row."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != HUDDLE_BOOK:
            continue
        cid = str(ex.get("source_league_id") or "").strip()
        if cid:
            return cid
        settings = ex.get("settings") or {}
        if isinstance(settings, dict):
            cid = str(settings.get("competition_id") or "").strip()
            if cid:
                return cid
    return None


def enable_huddle_pin(
    row: LeagueRow,
    competition_id: str = NFL_COMPETITION_ID,
) -> dict[str, Any]:
    """mapping_league payload that enables Huddle with the NFL competition id."""
    settings = dict(getattr(row, "settings", None) or {})
    payload = MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=str(row.optic_league_id),
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=str(row.fixture_source) or "api",
        fixture_horizon_hours=float(row.fixture_horizon_hours or 96.0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=_entity_type(settings),
        alias_enforcement=_alias_enforcement(settings),
        runshop_enabled=bool(settings.get("runshop_enabled")),
        exchanges=_merged_huddle_exchanges(row, competition_id, settings),
        notes=HUDDLE_NOTE,
        evidence_refs=[
            f"gap:huddle:{row.league}:{competition_id}",
            f"optic:league:{row.optic_league_id}",
        ],
    )
    return payload.model_dump(mode="json")


def _merged_huddle_exchanges(
    row: LeagueRow,
    competition_id: str,
    settings: dict[str, Any],
) -> list[ExchangePin]:
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in _huddle_exchange_pins(row, competition_id)],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _huddle_exchange_pins(row: LeagueRow, competition_id: str) -> list[ExchangePin]:
    pins: list[ExchangePin] = []
    seen = False
    for ex in list(row.exchanges or []):
        book = str(ex.get("sportsbook") or "")
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        st = dict(ex.get("settings") or {})
        if book == HUDDLE_BOOK:
            seen = True
            source = competition_id
            enabled = True
            st["competition_id"] = competition_id
        pins.append(_pin_from_dict({
            **ex,
            "enabled": enabled,
            "source_league_id": source,
            "settings": st,
        }))
    if not seen:
        pins.append(
            ExchangePin(
                sportsbook=HUDDLE_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[HUDDLE_BOOK],
                source_league_id=competition_id,
                settings={"competition_id": competition_id},
            ),
        )
    return pins


def _entity_type(settings: dict[str, Any]) -> Literal["team", "player", "fighter"]:
    raw = settings.get("entity_type", "team")
    if raw in _ENTITY:
        return raw  # type: ignore[return-value]
    return "team"


def _alias_enforcement(settings: dict[str, Any]) -> Literal["raise", "warn"]:
    raw = settings.get("alias_enforcement", "raise")
    if raw in _ENFORCE:
        return raw  # type: ignore[return-value]
    return "raise"


def _pin_from_dict(ex: dict[str, Any]) -> ExchangePin:
    return ExchangePin(
        sportsbook=str(ex.get("sportsbook") or ""),
        enabled=bool(ex.get("enabled", True)),
        parser_profile=str(ex.get("parser_profile") or ""),
        source_league_id=ex.get("source_league_id"),
        settings=dict(ex.get("settings") or {}),
    )
