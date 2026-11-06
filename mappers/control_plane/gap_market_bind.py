"""Bind name-match book keys to live Optic market_ids (spine + unique normalize)."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from enum import Enum
from typing import Any

from mappers.control_plane.dry_run_market_rules import apply_market_rules_payload
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.control_plane.gap_optic_census import CensusFn, cached_optic_market_ids
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.suggest_markets import _BOOK_COLUMNS, _rows_for_league_slug
from mappers.market_types import MarketType
from mappers.seed.overlay_taxonomy import (
    crypto_overlay_applies,
    overlay_crypto,
    overlay_optic,
    overlay_poly,
    overlay_px,
)
from mappers.seed.tip_factories import apply_tip_exchange_settings, build_tip_league

_NAME_MATCH_BOOKS = frozenset({
    "crypto.com", "polymarket", "polymarket_usa", "px",
})
_CRYPTO_LINE_GROUPS = frozenset({"Game Line", "Fight Line"})
_NORM = re.compile(r"[^a-z0-9]+")
logger = logging.getLogger(__name__)


def is_name_match_book(book: str) -> bool:
    """True when this sportsbook uses feed names, not Optic market_id passthrough."""
    return str(book or "").strip().lower() in _NAME_MATCH_BOOKS


def normalize_market_key(text: str) -> str:
    """Case/punctuation-insensitive key for unique name bind."""
    return _NORM.sub("", str(text or "").casefold())


def optic_ids_from_fixtures(fixtures: list[dict[str, Any]]) -> set[str]:
    """Distinct Optic market_id values quoted on live fixture odds."""
    out: set[str] = set()
    for game in fixtures:
        for odd in game.get("odds") or []:
            if not isinstance(odd, dict):
                continue
            mid = str(odd.get("market_id") or "").strip()
            if mid:
                out.add(mid)
    return out


def spine_canonical_for_source(
    *,
    league: str,
    book: str,
    source_key: str,
    market_group: str = "",
) -> str | None:
    """Unique spine canonical for this book cell, ignoring live census."""
    found = _spine_hits(
        league=league,
        book=book,
        source_key=source_key,
        live_ids=None,
        market_group=market_group,
    )
    if len(found) != 1:
        return None
    return str(next(iter(found.values()))[1])


def spine_bind(
    *,
    league: str,
    book: str,
    source_key: str,
    live_ids: set[str],
    market_group: str = "",
) -> tuple[str, str, str] | None:
    """Spine row for book cell + optic_market_id when live. Returns (optic_id, cmt, ref)."""
    found = _spine_hits(
        league=league,
        book=book,
        source_key=source_key,
        live_ids=live_ids,
        market_group=market_group,
    )
    if len(found) == 1:
        return next(iter(found.values()))
    return None


def _spine_hits(
    *,
    league: str,
    book: str,
    source_key: str,
    live_ids: set[str] | None,
    market_group: str = "",
) -> dict[str, tuple[str, str, str]]:
    """Spine optic_id hits for one book cell; optional live census filter."""
    meta = _BOOK_COLUMNS.get(book)
    if meta is None:
        return {}
    _key_type, column = meta
    needle = source_key.strip()
    if not needle:
        return {}
    found: dict[str, tuple[str, str, str]] = {}
    for row in _rows_for_league_slug(league):
        optic_id = str(row.get("optic_market_id") or "").strip()
        cmt = str(row.get("canonical_market_type") or "").strip()
        if not optic_id or not cmt:
            continue
        if live_ids is not None and optic_id not in live_ids:
            continue
        raw = str(row.get(column) or "")
        for cell in _spine_cells(raw, book=book, market_group=market_group):
            if cell == needle:
                found[optic_id] = (optic_id, cmt, f"spine:{column}:{cell}")
                break
    return found


def unique_name_bind(source_key: str, live_ids: set[str]) -> str | None:
    """One live Optic id when normalized source_key matches exactly one census id."""
    if not live_ids:
        return None
    norm = normalize_market_key(source_key)
    if not norm:
        return None
    hits = [mid for mid in live_ids if normalize_market_key(mid) == norm]
    if len(hits) == 1:
        return hits[0]
    # Moneyline ↔ moneyline via enum value strings
    value_hits = [
        mid
        for mid in live_ids
        if normalize_market_key(mid) == norm
        or normalize_market_key(_market_type_value(mid)) == norm
    ]
    if len(value_hits) == 1:
        return value_hits[0]
    return None


def bind_optic_market_id(
    *,
    league: str,
    book: str,
    source_key: str,
    live_ids: set[str],
    market_group: str = "",
) -> tuple[str, str, list[str]] | None:
    """Fail-closed unique bind: spine first, else normalized census. Returns (id, cmt, refs)."""
    spine = spine_bind(
        league=league,
        book=book,
        source_key=source_key,
        live_ids=live_ids,
        market_group=market_group,
    )
    if spine is not None:
        optic_id, cmt, ref = spine
        return optic_id, cmt, [ref, f"optic:market_id:{optic_id}"]
    picked = unique_name_bind(source_key, live_ids)
    if picked is None:
        return None
    cmt = _spine_canonical_for_id(league, picked) or _market_type_value(picked)
    return picked, cmt, [f"optic:market_id:{picked}"]


def market_type_candidates(live_ids: set[str], cfg: Any) -> list[dict[str, str]]:
    """Closed Optic list: live ids that resolve to a MarketType on this league."""
    enum_cls = cfg.MarketType
    table = getattr(getattr(cfg, "OPTIC", None), "table_types", None) or {}
    out: list[dict[str, str]] = []
    for mid in sorted(live_ids):
        mt = table.get(mid)
        if mt is None:
            mt = _enum_for_id(enum_cls, mid)
        if mt is None:
            continue
        out.append({"id": mid, "name": str(getattr(mt, "value", mid))})
    return out


def effective_league_cfg(
    store: Any,
    league: str,
) -> tuple[Any, Any, list[Any]] | None:
    """Tip LeagueConfig with market-rule overlays applied."""
    league_row = tip_league_row(store, league)
    if league_row is None:
        return None
    rid = store.current_rule_set_id
    rules = [
        row
        for row in store.market_rules_for(rid)
        if str(row.league or "") == league and not getattr(row, "tombstone", False)
    ]
    cfg = apply_tip_exchange_settings(build_tip_league(league_row), league_row)
    cfg = replace(
        cfg,
        CRYPTO=overlay_crypto(cfg.CRYPTO, rules, cfg),
        POLYMARKET=overlay_poly(cfg.POLYMARKET, rules, cfg),
        PX=overlay_px(cfg.PX, rules, cfg),
        OPTIC=overlay_optic(cfg.OPTIC, rules, cfg),
    )
    return cfg, league_row, rules


def tip_market_rule(
    rules: list[Any],
    *,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
) -> Any | None:
    """Live tip row for one book source key, if any."""
    for row in rules:
        if (
            str(row.sportsbook or "").lower() == sportsbook.lower()
            and str(row.source_key_type or "") == source_key_type
            and str(row.source_key or "") == source_key
            and not getattr(row, "tombstone", False)
        ):
            return row
    return None


def needs_optic_companion(rules: list[Any], optic_id: str) -> bool:
    """True when tip has other optic maps but not this market_id."""
    optic_rows = [
        row
        for row in rules
        if str(row.sportsbook or "") == "optic"
        and str(row.source_key_type or "") == "market_id"
        and str(row.action or "") == "map"
        and not getattr(row, "tombstone", False)
    ]
    if not optic_rows:
        return False
    return not any(str(row.source_key or "") == optic_id for row in optic_rows)


def overlay_applies(
    cfg: Any,
    *,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    canonical: str,
    market_group: str = "",
) -> bool:
    """True when the book overlay would map this source key after the pin."""
    book = sportsbook.lower()
    mt = _enum_for_value(cfg.MarketType, canonical)
    if mt is None:
        return False
    if book == "crypto.com" and source_key_type in {
        "contract_type", "team_prop_contract_type",
        "game_prop_contract_type", "player_prop_contract_type",
    }:
        return crypto_overlay_applies(
            cfg.CRYPTO,
            source_key_type=source_key_type,
            source_key=source_key,
            market_group=market_group,
        )
    if book == "polymarket" and source_key_type == "kind":  # never polymarket_usa
        poly = cfg.POLYMARKET
        return bool(poly and source_key in (poly.market_types or {}))
    if book == "px" and source_key_type == "market_name":
        px = cfg.PX
        if px is None:
            return False
        exact = px.exact or {}
        if source_key in exact:
            return True
        return any(source_key.endswith(sfx) for sfx, _ in (px.suffix or []))
    return False


def book_enabled(league_row: Any, book: str) -> bool:
    """True when the tip league has this sportsbook enabled."""
    needle = str(book or "").strip().lower()
    for ex in getattr(league_row, "exchanges", None) or []:
        if str(ex.get("sportsbook") or "").lower() != needle:
            continue
        return ex.get("enabled") is not False
    return False


def live_optic_census(
    store: Any,
    league: str,
    fixtures_fn: Any | None = None,
    *,
    census_fn: CensusFn | None = None,
) -> set[str]:
    """Distinct live Optic market_ids for a tip league (fixtures, else BQ census)."""
    league_row = tip_league_row(store, league)
    if league_row is None:
        return set()
    ids = [str(league_row.optic_league_id or "").strip()]
    ids.extend(str(x).strip() for x in (league_row.extra_optic_league_ids or []))
    ids = [oid for oid in ids if oid]
    horizon = optic_horizon_hours(league_row)
    out = _fixture_odds_ids(ids, horizon, fixtures_fn)
    if out:
        return out
    if census_fn is None and fixtures_fn is not None:
        # An injected fixtures_fn owns the odds evidence (tests, replays);
        # only the live path may reach for BigQuery.
        return set()
    fetch = census_fn or fetch_optic_market_ids_default
    try:
        return set(fetch(ids, horizon))
    except Exception as exc:  # noqa: BLE001 — census is optional evidence
        logger.warning("optic census unavailable for %s: %s", league, str(exc)[:160])
        return set()


def _fixture_odds_ids(
    optic_ids: list[str],
    horizon: float,
    fixtures_fn: Any | None,
) -> set[str]:
    out: set[str] = set()
    for oid in optic_ids:
        try:
            fixtures = cached_optic_fixtures(
                oid, horizon_hours=horizon, fetch_fn=fixtures_fn,
            )
        except Exception as exc:  # noqa: BLE001 — one league must not stop the sweep
            logger.debug("optic fixtures unavailable for %s: %s", oid, str(exc)[:160])
            continue
        out |= optic_ids_from_fixtures(fixtures)
    return out


def fetch_optic_market_ids_default(optic_ids: list[str], horizon: float) -> set[str]:
    """BigQuery census adapter matching :data:`CensusFn` (5-minute memo)."""
    return cached_optic_market_ids(optic_ids, horizon_hours=horizon)


def tip_league_row(store: Any, league: str) -> Any | None:
    """Activated-tip league row for this slug, or None."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return None
    return next(
        (
            row
            for row in store.leagues_for(rid)
            if str(row.league or "") == league and not getattr(row, "tombstone", False)
        ),
        None,
    )


def simulate_overlay_applies(
    cfg: Any,
    rules: list[Any],
    *,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    canonical: str,
    market_group: str = "",
    notes: str | None = None,
) -> bool:
    """Overlay check including a hypothetical new map pin."""
    pin = MarketRulePin(
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type=canonical,
        league=cfg.league,
        notes=notes,
    )
    payload = MappingMarketRulesPayload(league=cfg.league, rules=[pin])
    trial_rules = apply_market_rules_payload(list(rules), payload)
    trial = effective_league_cfg_from_parts(cfg, trial_rules)
    return overlay_applies(
        trial,
        sportsbook=sportsbook,
        source_key_type=source_key_type,
        source_key=source_key,
        canonical=canonical,
        market_group=market_group,
    )


def effective_league_cfg_from_parts(cfg: Any, rules: list[Any]) -> Any:
    """Re-overlay one LeagueConfig with trial market rules."""
    return replace(
        cfg,
        CRYPTO=overlay_crypto(cfg.CRYPTO, rules, cfg),
        POLYMARKET=overlay_poly(cfg.POLYMARKET, rules, cfg),
        PX=overlay_px(cfg.PX, rules, cfg),
        OPTIC=overlay_optic(cfg.OPTIC, rules, cfg),
    )


def resolve_market_type(cfg: Any, optic_id: str) -> Any | None:
    """MarketType for a live Optic id on this league, or None (needs_code)."""
    table = getattr(getattr(cfg, "OPTIC", None), "table_types", None) or {}
    if optic_id in table:
        return table[optic_id]
    return _enum_for_id(cfg.MarketType, optic_id)


def _spine_cells(raw: str, *, book: str, market_group: str) -> list[str]:
    """Spine multi-value cells; keep crypto game_line:/game_prop: buckets."""
    if not raw or not raw.strip():
        return []
    out: list[str] = []
    for chunk in raw.replace(",", ";").split(";"):
        cell = chunk.strip()
        if not cell:
            continue
        if book == "crypto.com" and market_group in _CRYPTO_LINE_GROUPS:
            out.append(f"game_line:{cell}")
            out.append(cell)
        elif ":" in cell and cell.split(":", 1)[0] in {
            "game_line", "game_prop", "prop", "team_prop", "exact",
        }:
            out.append(cell)
            out.append(cell.split(":", 1)[1].strip())
        else:
            out.append(cell)
    return out


def _spine_canonical_for_id(league: str, optic_id: str) -> str:
    for row in _rows_for_league_slug(league):
        if str(row.get("optic_market_id") or "").strip() == optic_id:
            return str(row.get("canonical_market_type") or "").strip()
    return ""


def _enum_for_id[E: Enum](enum_cls: type[E], optic_id: str) -> E | None:
    try:
        return enum_cls(optic_id)
    except ValueError:
        return next((mt for mt in enum_cls if mt.value == optic_id), None)


def _enum_for_value[E: Enum](enum_cls: type[E], value: str) -> E | None:
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return next((mt for mt in enum_cls if mt.value == value), None)


def _market_type_value(optic_id: str) -> str:
    try:
        return MarketType(optic_id).value
    except ValueError:
        hit = next((mt for mt in MarketType if mt.value == optic_id), None)
        return hit.value if hit else optic_id
