"""mapping_league payloads for DKEX harvest (enable / venue league pin)."""

from __future__ import annotations

from typing import Any, Literal

from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.exchanges.dkex import VENUE_TOKEN_BY_SLUG
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.profiles import DEFAULT_PROFILES

DKEX_BOOK = "dkex"
DKEX_NOTE = "pipeline gap-fix: enable DraftKings Exchange venue league pin"

#: Owned by the mapper (mappers/exchanges/dkex.py); re-exported here.
DKEX_VENUE_BY_SLUG = VENUE_TOKEN_BY_SLUG

# Leagues the gap harvester drafts "enable DKEX" and market-rule pins for.
# Soccer is deliberately NOT here yet: adding a slug makes the gap-propose
# cron draft enable cards for it, which is an owner decision.
ENABLED_LEAGUE_SLUGS: tuple[str, ...] = ("nfl", "ncaaf", "mlb", "wnba", "nba")

_ENTITY = frozenset({"team", "player", "fighter"})
_ENFORCE = frozenset({"raise", "warn"})


def dkex_venue_token(row: LeagueRow) -> str | None:
    """Read the pinned DKEX venue league token (NFL, CFB, …) from a tip row."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != DKEX_BOOK:
            continue
        token = str(ex.get("source_league_id") or "").strip()
        if token:
            return token.upper()
        settings = ex.get("settings") or {}
        if isinstance(settings, dict):
            token = str(settings.get("league") or "").strip()
            if token:
                return token.upper()
    return None


def venue_token_for_slug(league_slug: str, optic_league_id: str = "") -> str | None:
    """Map tip slug (or optic id) to DKEX venue league token."""
    slug = league_slug.strip().casefold()
    token = DKEX_VENUE_BY_SLUG.get(slug)
    if token:
        return token
    if optic_league_id:
        return DKEX_VENUE_BY_SLUG.get(optic_league_id.strip().casefold())
    return None


def enable_dkex_pin(row: LeagueRow, venue_token: str | None = None) -> dict[str, Any]:
    """mapping_league payload that enables DKEX with the venue league token."""
    token = (venue_token or venue_token_for_slug(str(row.league), str(row.optic_league_id)) or "").upper()
    if not token:
        raise ValueError(f"no DKEX venue token for league {row.league!r}")
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
        exchanges=_merged_dkex_exchanges(row, token, settings),
        notes=DKEX_NOTE,
        evidence_refs=[
            f"gap:dkex:{row.league}:{token}",
            f"optic:league:{row.optic_league_id}",
            "docs/adding-dkex.md",
        ],
    )
    return payload.model_dump(mode="json")


def _merged_dkex_exchanges(
    row: LeagueRow,
    venue_token: str,
    settings: dict[str, Any],
) -> list[ExchangePin]:
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in _dkex_exchange_pins(row, venue_token)],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _dkex_exchange_pins(row: LeagueRow, venue_token: str) -> list[ExchangePin]:
    pins: list[ExchangePin] = []
    seen = False
    for ex in list(row.exchanges or []):
        book = str(ex.get("sportsbook") or "")
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        st = dict(ex.get("settings") or {})
        if book == DKEX_BOOK:
            seen = True
            source = venue_token
            enabled = True
            st["league"] = venue_token
        pins.append(_pin_from_dict({
            **ex,
            "enabled": enabled,
            "source_league_id": source,
            "settings": st,
        }))
    if not seen:
        pins.append(
            ExchangePin(
                sportsbook=DKEX_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[DKEX_BOOK],
                source_league_id=venue_token,
                settings={"league": venue_token},
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
