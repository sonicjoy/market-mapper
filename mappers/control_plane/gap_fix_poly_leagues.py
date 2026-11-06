"""mapping_league payloads for Polymarket US harvest (enable US / onboard)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from mappers.control_plane.chat_profiles import all_platform_exchanges
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.poly_usa_exchange import POLY_BOOK, POLY_USA_BOOK, us_league_code
from mappers.seed.profiles import DEFAULT_PROFILES

POLY_NOTE = "pipeline gap-fix: Polymarket try-to-fix"
_SLUG_RE = re.compile(r"_+")
_ENTITY = frozenset({"team", "player", "fighter"})
_ENFORCE = frozenset({"raise", "warn"})


def slug_from_optic_id(optic_id: str) -> str:
    """Tip league slug from an Optic league id (``a_-_b`` → ``a_b``)."""
    text = optic_id.strip().casefold().replace("_-_", "_").replace("-", "_")
    return _SLUG_RE.sub("_", text).strip("_")


def enable_us_pin(row: LeagueRow, us_code: str) -> dict[str, Any]:
    """mapping_league payload that enables polymarket_usa and pins its inner code."""
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
        exchanges=_merged_exchanges(row, us_code, settings),
        notes=POLY_NOTE,
        evidence_refs=_league_refs(str(row.league), us_code, str(row.optic_league_id)),
    )
    return payload.model_dump(mode="json")


def disable_us_pin(row: LeagueRow) -> dict[str, Any]:
    """mapping_league payload that turns off a wrong polymarket_usa inner."""
    settings = dict(getattr(row, "settings", None) or {})
    optic = str(row.optic_league_id)
    payload = MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=optic,
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=str(row.fixture_source) or "api",
        fixture_horizon_hours=float(row.fixture_horizon_hours or 96.0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=_entity_type(settings),
        alias_enforcement=_alias_enforcement(settings),
        runshop_enabled=bool(settings.get("runshop_enabled")),
        exchanges=_usa_disabled_exchanges(row, settings),
        notes=POLY_NOTE,
        evidence_refs=[
            f"gap:usa-inner:{row.league}:clear",
            f"optic:league:{optic}",
            "reason:no_optic_book",
        ],
    )
    return payload.model_dump(mode="json")


def onboard_pin(
    slug: str,
    sport: str,
    optic_id: str,
    us_code: str,
    clone: str,
) -> dict[str, Any]:
    """New mapping_league with Optic + Polymarket US only."""
    payload = MappingLeaguePayload(
        league=slug,
        sport=sport,
        optic_league_id=optic_id,
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        exchanges=_onboard_exchanges(optic_id, us_code),
        clone_market_rules_from=clone,
        notes=POLY_NOTE,
        evidence_refs=_league_refs(slug, us_code, optic_id),
    )
    return payload.model_dump(mode="json")


def enable_official_pin(row: LeagueRow, prefix: str) -> dict[str, Any]:
    """mapping_league payload that sets official Polymarket slug_prefix."""
    settings = dict(getattr(row, "settings", None) or {})
    optic = str(row.optic_league_id)
    payload = MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=optic,
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=str(row.fixture_source) or "api",
        fixture_horizon_hours=float(row.fixture_horizon_hours or 96.0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=_entity_type(settings),
        alias_enforcement=_alias_enforcement(settings),
        runshop_enabled=bool(settings.get("runshop_enabled")),
        exchanges=_merged_official(row, prefix, settings),
        notes=POLY_NOTE,
        evidence_refs=_official_refs(str(row.league), prefix, optic),
    )
    return payload.model_dump(mode="json")


def onboard_official_pin(
    slug: str,
    sport: str,
    optic_id: str,
    prefix: str,
    clone: str,
) -> dict[str, Any]:
    """New mapping_league with Optic + official Polymarket slug_prefix."""
    payload = MappingLeaguePayload(
        league=slug,
        sport=sport,
        optic_league_id=optic_id,
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        exchanges=_onboard_official_exchanges(optic_id, prefix),
        clone_market_rules_from=clone,
        notes=POLY_NOTE,
        evidence_refs=_official_refs(slug, prefix, optic_id),
    )
    return payload.model_dump(mode="json")


def official_slug_prefix(row: LeagueRow) -> str:
    """Enabled official Polymarket slug_prefix, or empty."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != POLY_BOOK:
            continue
        if ex.get("enabled") is False:
            continue
        settings = ex.get("settings") or {}
        if not isinstance(settings, dict):
            continue
        pfx = str(settings.get("slug_prefix") or "").strip()
        if pfx:
            return pfx
    return ""


def optic_ids_if_all_wired(
    rows: list[LeagueRow], prefixes: Sequence[str],
) -> list[str] | None:
    """Optic league ids when every prefix is already on the tip; else None."""
    keys = {p.strip().casefold() for p in prefixes if p and p.strip()}
    if not keys:
        return []
    wired: set[str] = set()
    ids_by: dict[str, list[str]] = {}
    for row in rows:
        for pfx in _poly_wire_keys(row):
            wired.add(pfx)
            bucket = ids_by.setdefault(pfx, [])
            for oid in _row_optic_ids(row):
                if oid not in bucket:
                    bucket.append(oid)
    if not keys <= wired:
        return None
    return _unique_ids(keys, ids_by)


def _poly_wire_keys(row: LeagueRow) -> set[str]:
    """US inner and official slug_prefix this tip row already publishes."""
    out: set[str] = set()
    code = us_league_code(row).casefold()
    if code:
        out.add(code)
    pfx = official_slug_prefix(row).casefold()
    if pfx:
        out.add(pfx)
    return out


def _row_optic_ids(row: LeagueRow) -> list[str]:
    """Primary Optic id plus extras."""
    ids = [str(row.optic_league_id or "").strip()]
    ids.extend(str(x).strip() for x in (row.extra_optic_league_ids or []))
    return [oid for oid in ids if oid]


def _unique_ids(keys: set[str], ids_by: dict[str, list[str]]) -> list[str]:
    """Deduped Optic ids covering ``keys``, first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for oid in ids_by.get(key, []):
            if oid not in seen:
                seen.add(oid)
                out.append(oid)
    return out


def patch_official_prefix(pin: dict[str, Any], prefix: str) -> None:
    """Set official slug_prefix on an in-harvest mapping_league pin."""
    optic = str(pin.get("optic_league_id") or "")
    pin["exchanges"] = [
        p.model_dump(mode="json")
        for p in _exchanges_with_official(list(pin.get("exchanges") or []), optic, prefix)
    ]
    refs = list(pin.get("evidence_refs") or [])
    extra = _official_refs(str(pin.get("league") or ""), prefix, optic)
    pin["evidence_refs"] = list(dict.fromkeys([*refs, *extra]))


def patch_us_code(pin: dict[str, Any], us_code: str) -> None:
    """Set polymarket_usa inner code on an in-harvest mapping_league pin."""
    pin["exchanges"] = [
        p.model_dump(mode="json")
        for p in _pins_with_us(list(pin.get("exchanges") or []), us_code)
    ]
    refs = list(pin.get("evidence_refs") or [])
    extra = _league_refs(
        str(pin.get("league") or ""), us_code, str(pin.get("optic_league_id") or ""),
    )
    pin["evidence_refs"] = list(dict.fromkeys([*refs, *extra]))


def clone_source(store: Any, sport: str) -> str:
    """Same-sport tip league, preferring one that already has market_rules."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return ""
    same = [
        r.league for r in store.leagues_for(rid)
        if r.sport == sport and not r.tombstone
    ]
    if not same:
        return ""
    if hasattr(store, "market_rules_for"):
        ruled = {mr.league for mr in store.market_rules_for(rid)}
        for slug in same:
            if slug in ruled:
                return slug
    return same[0]


def sport_for(
    optic_id: str,
    rows: list[LeagueRow],
    fixtures: dict[str, list[dict[str, Any]]],
) -> str:
    """Sport from a tip row, else fixture rows, else soccer."""
    for row in rows:
        if row.optic_league_id == optic_id and row.sport:
            return str(row.sport)
    sports = {
        str(fx.get("sport") or "")
        for fx in fixtures.get(optic_id) or []
        if fx.get("sport")
    }
    sports.discard("")
    if len(sports) == 1:
        return next(iter(sports))
    return "soccer"


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


def _league_refs(league: str, us_code: str, optic_id: str) -> list[str]:
    return [f"gap:usa-inner:{league}:{us_code}", f"optic:league:{optic_id}"]


def _official_refs(league: str, prefix: str, optic_id: str) -> list[str]:
    return [f"gap:poly-prefix:{prefix}", f"optic:league:{optic_id}", f"league:{league}"]


def _official_settings(optic_id: str, prefix: str) -> dict[str, Any]:
    return {
        "slug_prefix": prefix,
        "optic_league_id": optic_id,
        "question_style": "mlb_suffix",
    }


def _merged_official(
    row: LeagueRow, prefix: str, settings: dict[str, Any],
) -> list[ExchangePin]:
    """Copy tip exchanges and set official Polymarket slug_prefix."""
    merged = merge_league_meta_into_exchanges(
        [
            pin.model_dump(mode="json")
            for pin in _exchanges_with_official(list(row.exchanges or []), str(row.optic_league_id), prefix)
        ],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _onboard_official_exchanges(optic_id: str, prefix: str) -> list[ExchangePin]:
    """Default chat pins with Optic + official Polymarket evidenced."""
    raw = all_platform_exchanges(
        optic_league_id=optic_id,
        evidence_books=["optic", POLY_BOOK],
    )
    return [_onboard_official_book(ex, optic_id, prefix) for ex in raw]


def _onboard_official_book(ex: dict[str, Any], optic_id: str, prefix: str) -> ExchangePin:
    """One onboard exchange; official slug_prefix only on polymarket."""
    book = str(ex["sportsbook"])
    source = ex.get("source_league_id")
    settings = dict(ex.get("settings") or {})
    enabled = bool(ex.get("enabled"))
    if book == POLY_BOOK:
        source = optic_id
        settings.update(_official_settings(optic_id, prefix))
        enabled = True
    return ExchangePin(
        sportsbook=book,
        enabled=enabled,
        parser_profile=str(ex.get("parser_profile") or DEFAULT_PROFILES.get(book) or ""),
        source_league_id=source,
        settings=settings,
    )


def _exchanges_with_official(
    exchanges: list[dict[str, Any]],
    optic_id: str,
    prefix: str,
) -> list[ExchangePin]:
    """Copy exchanges and set/add an enabled official Polymarket pin."""
    pins: list[ExchangePin] = []
    seen = False
    extra = _official_settings(optic_id, prefix)
    for ex in exchanges:
        book = str(ex.get("sportsbook") or "")
        settings = dict(ex.get("settings") or {})
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        if book == POLY_BOOK:
            seen = True
            settings.update(extra)
            source = source or optic_id
            enabled = True
        pins.append(_pin_from_dict({
            **ex, "enabled": enabled, "source_league_id": source, "settings": settings,
        }))
    if not seen:
        pins.append(
            ExchangePin(
                sportsbook=POLY_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[POLY_BOOK],
                source_league_id=optic_id,
                settings=extra,
            ),
        )
    return pins


def _merged_exchanges(
    row: LeagueRow, us_code: str, settings: dict[str, Any],
) -> list[ExchangePin]:
    """Copy tip exchanges, pin US inner, merge league meta onto optic."""
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in _exchange_pins_with_us(row, us_code)],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _onboard_exchanges(optic_id: str, us_code: str) -> list[ExchangePin]:
    """Default chat pins with Optic + polymarket_usa evidenced."""
    raw = all_platform_exchanges(
        optic_league_id=optic_id,
        evidence_books=["optic", POLY_USA_BOOK],
    )
    return [_onboard_exchange(ex, us_code) for ex in raw]


def _onboard_exchange(ex: dict[str, Any], us_code: str) -> ExchangePin:
    """One onboard exchange; US inner code only on polymarket_usa."""
    book = str(ex["sportsbook"])
    source = ex.get("source_league_id")
    settings = dict(ex.get("settings") or {})
    if book == POLY_USA_BOOK:
        source = us_code
        settings["slug_prefix"] = us_code
    return ExchangePin(
        sportsbook=book,
        enabled=bool(ex.get("enabled")),
        parser_profile=str(ex.get("parser_profile") or DEFAULT_PROFILES.get(book) or ""),
        source_league_id=source,
        settings=settings,
    )


def _exchange_pins_with_us(row: LeagueRow, us_code: str) -> list[ExchangePin]:
    """Copy tip exchanges and set/add the polymarket_usa inner code."""
    return _pins_with_us(list(row.exchanges or []), us_code)


def _pins_with_us(exchanges: list[dict[str, Any]], us_code: str) -> list[ExchangePin]:
    """Copy exchanges and enable polymarket_usa with this inner code."""
    pins: list[ExchangePin] = []
    usa_seen = False
    for ex in exchanges:
        book = str(ex.get("sportsbook") or "")
        settings = dict(ex.get("settings") or {})
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        if book == POLY_USA_BOOK:
            usa_seen = True
            source = us_code
            settings["slug_prefix"] = us_code
            enabled = True
        pins.append(_pin_from_dict({
            **ex, "enabled": enabled, "source_league_id": source, "settings": settings,
        }))
    if not usa_seen:
        pins.append(
            ExchangePin(
                sportsbook=POLY_USA_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[POLY_USA_BOOK],
                source_league_id=us_code,
                settings={"slug_prefix": us_code},
            ),
        )
    return pins


def _usa_disabled_exchanges(
    row: LeagueRow, settings: dict[str, Any],
) -> list[ExchangePin]:
    """Copy tip exchanges with polymarket_usa disabled and inner cleared."""
    pins: list[ExchangePin] = []
    for ex in list(row.exchanges or []):
        book = str(ex.get("sportsbook") or "")
        st = dict(ex.get("settings") or {})
        source = ex.get("source_league_id")
        enabled = ex.get("enabled", True)
        if book == POLY_USA_BOOK:
            enabled = False
            source = None
            st.pop("slug_prefix", None)
        pins.append(_pin_from_dict({
            **ex, "enabled": enabled, "source_league_id": source, "settings": st,
        }))
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in pins],
        settings,
    )
    return [_pin_from_dict(ex) for ex in merged]


def _pin_from_dict(ex: dict[str, Any]) -> ExchangePin:
    """Build an ExchangePin from a tip or merged exchange dict."""
    return ExchangePin(
        sportsbook=str(ex.get("sportsbook") or ""),
        enabled=bool(ex.get("enabled", True)),
        parser_profile=str(ex.get("parser_profile") or ""),
        source_league_id=ex.get("source_league_id"),
        settings=dict(ex.get("settings") or {}),
    )
