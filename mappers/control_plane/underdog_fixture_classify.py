"""Underdog gap-proposer drafts and CSV alias classification helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal

from mappers.canonical_codes import names_fit
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.console_mapping_clone import rule_row_key
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.gap_fix_underdog_leagues import (
    UNDERDOG_BOOK,
    enable_underdog_pin,
    underdog_venue_token,
    venue_token_for_slug,
)
from mappers.control_plane.models import MappingLeaguePayload, MarketRulePin
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.underdog_fixture_harvest import (
    ClassifiedLeague,
    ClassifiedMarketRule,
    HarvestEnvReport,
    ParsedHeader,
    parse_udx_header,
)
from mappers.control_plane.underdog_legacy_ticker import (
    UnderdogTicker,
    _selection_line,
    parse_ticker,
    udx_player_code,
)
from mappers.control_plane.underdog_legacy_vocab import market_type_for_venue
from mappers.control_plane.underdog_team_catalog import (
    entity_has_underdog_code,
    resolve_team_entity,
    team_catalog,
)
from mappers.seed.underdog_market_rules import (
    SOURCE_KEY_TYPE,
    format_product_period_key,
    missing_market_rule_pins,
)
from mappers.team_side import team_side

_SKIP_SELECTIONS = frozenset({
    "DRAW", "TIE", "RFI", "DIST", "DEC", "BTTS", "MOV", "MOVFINISH",
})


def harvest_underdog_gaps(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    """Draft Underdog league, market-rule, and team-code pins with empty RFQ inventory."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return
    league_rows = [
        row for row in store.leagues_for(rid)
        if not row.tombstone and venue_token_for_slug(str(row.league))
    ]
    entities = store.entities_for(rid)
    tip_rules = store.market_rules_for(rid)
    catalog = team_catalog()
    for row in league_rows:
        slug = str(row.league)
        token = venue_token_for_slug(slug) or ""
        _append_league_pin(row, token, pins, seen)
        _append_market_rule_pins(slug, token, tip_rules, pins, seen)
        _append_catalog_aliases(slug, catalog.get(slug) or {}, entities, pins, skipped, seen)


def _append_league_pin(
    row: LeagueRow,
    token: str,
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    actual = underdog_venue_token(row) or ""
    enabled = any(
        str(ex.get("sportsbook") or "") == UNDERDOG_BOOK and ex.get("enabled", True)
        for ex in (row.exchanges or [])
    )
    if enabled and (not actual or actual == token.upper()):
        return
    key = (str(row.league), UNDERDOG_BOOK, f"league:{token}")
    if key in seen:
        return
    seen.add(key)
    pins.append(enable_underdog_pin(row, venue_token=token))


def _append_market_rule_pins(
    slug: str,
    venue: str,
    tip_rules: list[MarketRuleRow],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    missing = missing_market_rule_pins(slug, tip_rules)
    if not missing:
        return
    key = (slug, UNDERDOG_BOOK, "market_rules")
    if key in seen:
        return
    seen.add(key)
    pins.append({
        "kind": "mapping_market_rules",
        "league": slug,
        "rules": [pin.model_dump(mode="json") for pin in missing],
        "evidence_refs": [f"gap:udx:{venue}:{slug}"],
    })


def _append_catalog_aliases(
    slug: str,
    codes: dict[str, str],
    entities: list[EntityRow],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
) -> None:
    league_entities = [e for e in entities if str(e.league) == slug]
    for code, venue_name in sorted(codes.items()):
        key = (slug, UNDERDOG_BOOK, code)
        if key in seen:
            continue
        entity = resolve_team_entity(league_entities, code, venue_name)
        if entity is None:
            skipped.append({"book": UNDERDOG_BOOK, "league": slug, "code": code, "reason": "unresolvable"})
            continue
        if entity_has_underdog_code(entity, code):
            continue
        seen.add(key)
        pins.append(alias_payload(
            slug,
            str(entity.canonical_key),
            str(entity.canonical_name or venue_name),
            str(entity.entity_type or "team"),
            [{"sportsbook": UNDERDOG_BOOK, "alias_kind": "code", "alias_value": code}],
            [f"gap:udx:{slug}:{code}", "docs/adding-underdog.md"],
        ))


def build_league_payloads(
    store: Any,
    report: HarvestEnvReport,
    *,
    leagues: Sequence[str] | None = None,
) -> list[MappingLeaguePayload]:
    """``mapping_league`` payloads when Underdog is off or token mismatches."""
    allowed = set(leagues) if leagues else None
    rid = store.current_rule_set_id
    if not rid:
        return []
    by_slug = {row.league: row for row in store.leagues_for(rid)}
    out: list[MappingLeaguePayload] = []
    for item in report.leagues:
        if item.status not in {"underdog_off", "wrong_token"}:
            continue
        if allowed is not None and item.league not in allowed:
            continue
        row = by_slug.get(item.league)
        if row is None:
            continue
        payload = enable_underdog_pin(row, venue_token=item.expected_token)
        out.append(MappingLeaguePayload.model_validate(payload))
    return out


def _alias_target(
    store: Any,
    header: ParsedHeader,
    slug: str,
    catalog: dict[str, dict[str, str]],
) -> tuple[str, Literal["team", "player", "fighter"], str]:
    """Return (code, entity_type, optional player_token) to pin, if any."""
    selection_u = header.selection.strip().upper()
    if selection_u in _SKIP_SELECTIONS:
        return "", "team", ""
    code, _line = _selection_line(header.selection)
    code_u = (code or "").strip().upper()
    product = header.product.upper()
    venue = header.venue.upper()
    side_type = _side_type(store, slug, venue)

    if product in {"MATCHWIN", "FIGHTWIN"}:
        if not code_u or not code_u.isalpha():
            return "", side_type, ""
        return code_u, side_type, ""

    if product == "GAMEWIN":
        if not code_u or not code_u.isalpha():
            return "", "team", ""
        return code_u, "team", ""

    if product in {"SPREAD", "TEAMTOTAL"} and code_u and code_u.isalpha():
        if venue in {"ATP", "ATPCHL", "WTA", "ITFMEN", "ITFWOMEN"}:
            return code_u, side_type, ""
        return code_u, "team", ""

    parsed = _parse_team_ticker(header.raw, slug, catalog)
    if parsed and parsed.player_token:
        token = parsed.player_token.strip().upper()
        if token.isalpha() and len(token) >= 4:
            return token, "player", token
    return "", "team", ""


def _parse_team_ticker(
    ticker: str,
    slug: str,
    catalog: dict[str, dict[str, str]],
) -> UnderdogTicker | None:
    header = parse_udx_header(ticker)
    codes = frozenset(catalog.get(slug, {}))
    if header is None or not codes:
        return None
    return parse_ticker(ticker, codes, sport=header.venue)


def _resolve_code_entity(
    league: str,
    code: str,
    entity_type: Literal["team", "player", "fighter"],
    entities: list[EntityRow],
    fixture: dict[str, Any] | None,
    *,
    player_token: str,
    venue_name: str,
) -> EntityRow | None:
    code_u = code.strip().upper()
    typed = [
        e for e in entities
        if e.enabled and not e.tombstone and (e.entity_type or "team") == entity_type
    ]
    side_name = _fixture_side_name(venue_name, fixture)
    if entity_type != "player" and side_name:
        named = [
            ent for ent in typed
            if names_fit(side_name, str(ent.canonical_name or ""), player=False)
        ]
        if len(named) == 1:
            return named[0]
        return None

    token = player_token or code_u
    side_names = _code_side_names(token, fixture)
    matches = [
        ent for ent in typed
        if _entity_matches_side(ent, side_names)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None
    return None


def _underdog_code_owner(
    entities: list[EntityRow],
    code: str,
    resolved: EntityRow,
) -> EntityRow | None:
    """Another tip entity that already holds this Underdog code."""
    for ent in entities:
        if ent is resolved or ent.tombstone or not ent.enabled:
            continue
        if entity_has_underdog_code(ent, code):
            return ent
    return None


def _side_type(
    store: Any,
    slug: str,
    venue: str,
) -> Literal["team", "player", "fighter"]:
    if venue == "UFC":
        return "fighter"
    raw = match_entity_type_for_league(store, slug)
    if raw == "fighter":
        return "fighter"
    return "team"


def _fixture_side_name(venue_name: str, fixture: dict[str, Any] | None) -> str:
    """Optic display name the venue's own name for this code fits, or "" unless exactly one.

    Never the ticker blob slot: UDX lists some events the other way round.
    """
    if fixture is None or not venue_name:
        return ""
    home = str(fixture.get("home") or "")
    away = str(fixture.get("away") or "")
    return team_side(
        venue_name, home=home, away=away, home_name=home, away_name=away,
    ) or ""


def _code_side_names(code: str, fixture: dict[str, Any] | None) -> list[str]:
    """Fixture sides whose Underdog player code is this token. Empty if not unique."""
    if fixture is None:
        return []
    names = [str(fixture.get("home") or ""), str(fixture.get("away") or "")]
    hits = [name for name in names if name and udx_player_code(name) == code]
    if len(hits) != 1:
        return []
    return hits


def _entity_matches_side(
    entity: EntityRow,
    fixture_names: Iterable[str],
) -> bool:
    name = str(entity.canonical_name or "")
    return any(
        fx_name and names_fit(name, fx_name, player=True)
        for fx_name in fixture_names
    )


def _touch_league(
    slug: str,
    venue: str,
    league_rows: dict[str, LeagueRow],
    out: dict[str, ClassifiedLeague],
) -> None:
    if slug in out:
        return
    row = league_rows.get(slug)
    if row is None or row.tombstone:
        out[slug] = ClassifiedLeague(league=slug, status="missing_slug")
        return
    expected = venue_token_for_slug(slug) or venue
    actual = underdog_venue_token(row) or ""
    underdog_on = any(
        str(ex.get("sportsbook") or "") == UNDERDOG_BOOK and ex.get("enabled", True)
        for ex in (row.exchanges or [])
    )
    if not underdog_on:
        out[slug] = ClassifiedLeague(
            league=slug,
            status="underdog_off",
            expected_token=expected,
            actual_token=actual,
        )
        return
    if actual and expected and actual != expected.upper():
        out[slug] = ClassifiedLeague(
            league=slug,
            status="wrong_token",
            expected_token=expected,
            actual_token=actual,
        )
        return
    out[slug] = ClassifiedLeague(league=slug, status="ok", expected_token=expected)


def _touch_market_rule(
    slug: str,
    header: ParsedHeader,
    tip_rules: list[MarketRuleRow],
    out: dict[tuple[str, str], ClassifiedMarketRule],
) -> None:
    source_key = format_product_period_key(header.product, header.period)
    key = (slug, source_key)
    if key in out:
        return
    out[key] = ClassifiedMarketRule(
        league=slug,
        source_key=source_key,
        status=_rule_status(slug, header, source_key, tip_rules),
        product=header.product,
        period=header.period,
        venue=header.venue,
    )


def _rule_status(
    slug: str,
    header: ParsedHeader,
    source_key: str,
    tip_rules: list[MarketRuleRow],
) -> Literal["propose", "already_ruled", "needs_code"]:
    mt = market_type_for_venue(header.venue, header.product, header.period)
    if mt is None:
        return "needs_code"
    pin = MarketRulePin(
        league=slug, sportsbook=UNDERDOG_BOOK, rule_kind="taxonomy",
        source_key_type=SOURCE_KEY_TYPE, source_key=source_key, action="map",
        canonical_market_type=mt.value,
    )
    missing = {rule_row_key(slug, item) for item in missing_market_rule_pins(slug, tip_rules)}
    if rule_row_key(slug, pin) in missing:
        return "propose"
    return "already_ruled"

