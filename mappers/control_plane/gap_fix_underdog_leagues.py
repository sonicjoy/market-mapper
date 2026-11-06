"""mapping_league payloads for Underdog UDX harvest (enable / venue league pin)."""

from __future__ import annotations

from typing import Any, Literal

from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.profiles import DEFAULT_PROFILES

UNDERDOG_BOOK = "underdog"
UNDERDOG_NOTE = "pipeline gap-fix: enable Underdog UDX venue league pin"

UNDERDOG_VENUE_BY_SLUG: dict[str, str] = {
    "nfl": "NFL",
    "mlb": "MLB",
    "wnba": "WNBA",
    "ncaaf": "NCAAMFB",
    "ncaamfb": "NCAAMFB",
    "cfb": "NCAAMFB",
    "atp": "ATP",
    "atp_challenger": "ATPCHL",
    "wta": "WTA",
    "itf_men": "ITFMEN",
    "itf_women": "ITFWOMEN",
    "mls": "MLS",
    "liga_mx": "LIGAMX",
    "uefa_nations_league": "UNL",
    "international_friendlies": "FIFA",
    "brazil_serie_a": "BRASILA",
    "saudi_pro_league": "SAUDIPRO",
    "argentina_primera_nacional": "ARGNAC",
    "nhl": "NHL",
    "ufc": "UFC",
    # Optic league ids, for venue_token_for_slug's fallback when a tip slug is renamed.
    "international_-_friendlies": "FIFA",
    "brazil_-_serie_a": "BRASILA",
    "saudi_arabia_-_saudi_league": "SAUDIPRO",
    "argentina_-_primera_nacional": "ARGNAC",
}

ENABLED_LEAGUE_SLUGS: tuple[str, ...] = ("nfl", "mlb", "wnba", "ncaaf")

_ENTITY = frozenset({"team", "player", "fighter"})
_ENFORCE = frozenset({"raise", "warn"})


def underdog_venue_token(row: LeagueRow) -> str | None:
    """Read the pinned Underdog venue league token (NFL, MLB, …) from a tip row."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != UNDERDOG_BOOK:
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
    """Map tip slug (or optic id) to Underdog venue league token."""
    slug = league_slug.strip().casefold()
    token = UNDERDOG_VENUE_BY_SLUG.get(slug)
    if token:
        return token
    if optic_league_id:
        return UNDERDOG_VENUE_BY_SLUG.get(optic_league_id.strip().casefold())
    return None


def enable_underdog_pin(row: LeagueRow, venue_token: str | None = None) -> dict[str, Any]:
    """mapping_league payload that enables Underdog with the venue league token."""
    token = (venue_token or venue_token_for_slug(str(row.league), str(row.optic_league_id)) or "").upper()
    if not token:
        raise ValueError(f"no Underdog venue token for league {row.league!r}")
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
        exchanges=_merged_underdog_exchanges(row, token, settings),
        notes=UNDERDOG_NOTE,
        evidence_refs=[
            f"gap:underdog:{row.league}:{token}",
            f"optic:league:{row.optic_league_id}",
            "docs/adding-underdog.md",
        ],
    )
    return payload.model_dump(mode="json")


def _merged_underdog_exchanges(
    row: LeagueRow,
    venue_token: str,
    settings: dict[str, Any],
) -> list[ExchangePin]:
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in _underdog_exchange_pins(row, venue_token)],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _underdog_exchange_pins(row: LeagueRow, venue_token: str) -> list[ExchangePin]:
    pins: list[ExchangePin] = []
    seen = False
    for ex in list(row.exchanges or []):
        book = str(ex.get("sportsbook") or "")
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        st = dict(ex.get("settings") or {})
        if book == UNDERDOG_BOOK:
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
                sportsbook=UNDERDOG_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[UNDERDOG_BOOK],
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
