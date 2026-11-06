"""Shared mapping_league onboard from RFQ demand (fail-closed)."""

from __future__ import annotations

from typing import Any, Literal, cast

from BigQuery.alerts import bool_env
from mappers.control_plane.gap_fix_poly_leagues import (
    clone_source,
    slug_from_optic_id,
)
from mappers.control_plane.harvest_league_ids_common import (
    crypto_settings_from_meta,
    exchange_pin_on_tip,
)
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload
from mappers.control_plane.rows import LeagueRow
from mappers.seed.profiles import DEFAULT_PROFILES

ONBOARD_NOTE = "pipeline gap-fix: onboard league from RFQ demand"


def gap_onboard_enabled() -> bool:
    return bool_env("MAPPING_PIPELINE_GAP_ONBOARD", default=True)


def stamp_gap_harvest_pin(pin: dict[str, Any], *, book: str, key: str) -> None:
    """Record which RFQ key produced this alias pin (gap ledger + Review)."""
    pin["harvest_book"] = book
    pin["harvest_key"] = key
    pin["gap_key"] = key


def try_onboard_league_pin(
    store: Any,
    *,
    optic_id: str,
    sport: str,
    source_token: str,
    book: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
    fixtures: dict[str, list[dict[str, Any]]],
    gap_key: str,
    harvest_book: str,
) -> bool:
    """Draft one mapping_league when Optic league is unique. Return True if pinned.

    A tip row that already owns the Optic league gets this book enabled, never a
    rewritten token: an enabled exchange on that row is left alone.
    """
    slug = slug_from_optic_id(optic_id)
    if not slug:
        skipped.append(_skip(harvest_book, gap_key, "missing_optic"))
        return False
    pin, reason = _draft_league_pin(store, slug, optic_id, sport, book, source_token, rows)
    if pin is None:
        skipped.append(_skip(harvest_book, gap_key, reason))
        return False
    ident = ("mapping_league", slug, optic_id)
    if ident in seen:
        return False
    seen.add(ident)
    pin["harvest_book"] = harvest_book
    pin["harvest_key"] = gap_key
    pin["gap_key"] = gap_key
    pins.append(pin)
    return True


def _draft_league_pin(
    store: Any,
    slug: str,
    optic_id: str,
    sport: str,
    book: str,
    source_token: str,
    rows: list[LeagueRow],
) -> tuple[dict[str, Any] | None, str]:
    """(pin, "") or (None, skip reason). Owner rows get the book enabled, never re-tokened."""
    owners = [r for r in rows if r.optic_league_id == optic_id and not r.tombstone]
    if len(owners) > 1:
        return None, "optic_league_collision"
    if owners:
        wired = exchange_pin_on_tip(owners[0], book)
        if wired is not None:
            same = str(wired.get("source_league_id") or "").casefold() == source_token.casefold()
            return None, "needs_probe" if same else "book_token_conflict"
        pin = _enable_book_on_row(owners[0], book, source_token, sport)
        return (pin, "") if pin is not None else (None, "needs_code")
    if slug.casefold() in {r.league.casefold() for r in rows if not r.tombstone}:
        return None, "slug_collision"
    clone = clone_source(store, sport)
    if not clone:
        return None, "missing_clone_source"
    return _onboard_new(slug, sport, optic_id, book, source_token, clone), ""


def _onboard_new(
    slug: str,
    sport: str,
    optic_id: str,
    book: str,
    source_token: str,
    clone_from: str,
) -> dict[str, Any]:
    exchanges = _exchanges_for_book(book, source_token, optic_id, sport)
    payload = MappingLeaguePayload(
        league=slug,
        sport=sport,
        optic_league_id=optic_id,
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        exchanges=exchanges,
        clone_market_rules_from=clone_from,
        notes=ONBOARD_NOTE,
        evidence_refs=[f"gap:onboard:{book}:{source_token}", f"optic:league:{optic_id}"],
    )
    return payload.model_dump(mode="json")


def _enable_book_on_row(row: LeagueRow, book: str, source_token: str, sport: str) -> dict[str, Any] | None:
    exchanges = list(row.exchanges or [])
    patched = _patch_exchange(exchanges, book, source_token, sport, str(row.optic_league_id))
    if patched is None:
        return None
    payload = MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=str(row.optic_league_id),
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=str(row.fixture_source) or "api",
        fixture_horizon_hours=float(row.fixture_horizon_hours or 96.0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=_entity_type(row),
        exchanges=patched,
        notes=ONBOARD_NOTE,
        evidence_refs=[f"gap:enable:{book}:{source_token}"],
    )
    return payload.model_dump(mode="json")


def _exchanges_for_book(
    book: str,
    source_token: str,
    optic_id: str,
    sport: str,
) -> list[ExchangePin]:
    optic = ExchangePin(
        sportsbook="optic",
        enabled=True,
        parser_profile=DEFAULT_PROFILES.get("optic", "optic_standard_v1"),
        source_league_id=optic_id,
        settings={},
    )
    patched = _patch_exchange([], book, source_token, sport, optic_id)
    if patched is None:
        return []
    return [optic, *patched]


def _patch_exchange(
    exchanges: list[Any],
    book: str,
    source_token: str,
    sport: str,
    optic_id: str,
) -> list[ExchangePin] | None:
    profile = DEFAULT_PROFILES.get(book)
    if not profile:
        return None
    out: list[ExchangePin] = []
    found = False
    for ex in exchanges:
        if str(ex.get("sportsbook") or "").lower() != book:
            out.append(ExchangePin(**ex) if isinstance(ex, dict) else ex)
            continue
        found = True
        settings = dict(ex.get("settings") or {}) if isinstance(ex, dict) else {}
        out.append(
            ExchangePin(
                sportsbook=book,
                enabled=True,
                parser_profile=str(ex.get("parser_profile") or profile),
                source_league_id=source_token,
                settings=_book_settings(book, source_token, sport, settings),
            )
        )
    if not found:
        out.append(
            ExchangePin(
                sportsbook=book,
                enabled=True,
                parser_profile=profile,
                source_league_id=source_token,
                settings=_book_settings(book, source_token, sport, {}),
            )
        )
    return out


def _book_settings(
    book: str,
    source_token: str,
    sport: str,
    base: dict[str, Any],
) -> dict[str, Any]:
    if book == "crypto.com":
        merged = crypto_settings_from_meta(source_token, sport)
        merged.update(base)
        return merged
    if book == "px":
        return {**base, "tournament_id": source_token}
    if book in {"underdog", "dkex", "novig"}:
        return {**base, "league": source_token}
    return dict(base)


def _entity_type(row: LeagueRow) -> Literal["team", "player", "fighter"]:
    raw = str((row.settings or {}).get("entity_type") or "team")
    if raw in {"team", "player", "fighter"}:
        return cast(Literal["team", "player", "fighter"], raw)
    return "team"


def _skip(book: str, key: str, reason: str) -> dict[str, str]:
    return {"book": book, "key": key, "reason": reason}


def is_onboard_pin(pin: dict[str, Any]) -> bool:
    return str(pin.get("kind") or "") == "mapping_league"
