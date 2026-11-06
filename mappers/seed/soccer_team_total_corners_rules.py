"""Emit soccer team_total_corners market-rule pins for the BQ tip.

Optic is always pinned. Polymarket / Novig / Kalshi pins follow the
league's enabled exchanges on the target tip. Kalshi TCORNERS is a tip
map row (the Python soccer table does not force it on).
"""

from __future__ import annotations

from mappers.control_plane.console_mapping_clone import rule_row_key
from mappers.control_plane.models import (
    BatchChangesPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.market_types import MarketType
from mappers.pipeline import LeagueConfig
from mappers.sport import Sport

_NOTE = (
    "Soccer team_total_corners: Optic / Polymarket / Novig pins "
    "from the shared soccer taxonomy."
)
_CANONICAL = MarketType.TEAM_TOTAL_CORNERS
_BOOK_PINS: tuple[tuple[str, str, str], ...] = (
    ("polymarket", "kind", "team_total_corners"),
    ("novig", "market_type", "TEAM_TOTAL_CORNERS"),
)


def _pin(
    *,
    league: str,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
) -> MarketRulePin:
    return MarketRulePin(
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type=_CANONICAL.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        match_operator="exact",
        notes=_NOTE,
    )


def soccer_league_slugs(leagues: dict[str, LeagueConfig]) -> tuple[str, ...]:
    """Sorted soccer slugs from the wired league registry."""
    return tuple(
        sorted(
            slug for slug, cfg in leagues.items() if cfg.sport == Sport.SOCCER
        )
    )


def enabled_exchange_books(row: LeagueRow) -> frozenset[str]:
    """Sportsbooks enabled on a tip league row."""
    out: set[str] = set()
    for ex in row.exchanges or []:
        if ex.get("enabled", True) is False:
            continue
        book = str(ex.get("sportsbook") or "").strip()
        if book:
            out.add(book)
    return frozenset(out)


def _books_from_cfg(cfg: LeagueConfig) -> frozenset[str]:
    books: set[str] = set()
    if cfg.POLYMARKET is not None:
        books.add("polymarket")
    if cfg.NOVIG is not None:
        books.add("novig")
    return frozenset(books)


def desired_market_rule_pins(
    league: str,
    cfg: LeagueConfig | None = None,
    *,
    books: frozenset[str] | None = None,
) -> list[MarketRulePin]:
    """Pins for one soccer league's team_total_corners wiring."""
    active = books if books is not None else (
        _books_from_cfg(cfg) if cfg is not None else frozenset()
    )
    pins = [
        _pin(
            league=league,
            sportsbook="optic",
            source_key_type="market_id",
            source_key="team_total_corners",
        ),
    ]
    pins.extend(
        _pin(league=league, sportsbook=book, source_key_type=key_type, source_key=key)
        for book, key_type, key in _BOOK_PINS
        if book in active
    )
    return pins


def missing_market_rule_pins(
    league: str,
    tip_rules: list[MarketRuleRow],
    *,
    cfg: LeagueConfig | None = None,
    books: frozenset[str] | None = None,
) -> list[MarketRulePin]:
    """Pins absent from the live tip (map rows only)."""
    have = {
        f"rule:{row.league}:{row.sportsbook}:{row.source_key_type}:{row.source_key}"
        for row in tip_rules
        if row.league == league
        and row.enabled
        and not row.tombstone
        and row.action == "map"
    }
    return [
        pin
        for pin in desired_market_rule_pins(league, cfg, books=books)
        if rule_row_key(league, pin) not in have
    ]


def _payload_for_pins(pins: list[MarketRulePin], leagues: list[str]) -> BatchChangesPayload:
    if not pins:
        return BatchChangesPayload()
    groups = [
        MappingMarketRulesPayload(
            league=league,
            rules=[pin for pin in pins if pin.league == league],
        )
        for league in leagues
        if any(pin.league == league for pin in pins)
    ]
    return BatchChangesPayload(market_rules=groups)


def build_soccer_team_total_corners_payload(
    tip_rules: list[MarketRuleRow],
    leagues: dict[str, LeagueConfig],
) -> BatchChangesPayload:
    """Batch payload for every missing soccer team_total_corners pin."""
    pins: list[MarketRulePin] = []
    slugs = soccer_league_slugs(leagues)
    for league in slugs:
        pins.extend(
            missing_market_rule_pins(league, tip_rules, cfg=leagues.get(league))
        )
    return _payload_for_pins(pins, list(slugs))


def build_soccer_team_total_corners_payload_from_tip(
    tip_rules: list[MarketRuleRow],
    tip_leagues: list[LeagueRow],
) -> BatchChangesPayload:
    """Missing pins for enabled soccer leagues on the target tip."""
    soccer_rows = [
        row for row in tip_leagues
        if (row.sport or "").strip().lower() == "soccer" and row.enabled
    ]
    pins: list[MarketRulePin] = []
    for row in soccer_rows:
        pins.extend(
            missing_market_rule_pins(
                row.league,
                tip_rules,
                books=enabled_exchange_books(row),
            )
        )
    return _payload_for_pins(pins, sorted({row.league for row in soccer_rows}))
