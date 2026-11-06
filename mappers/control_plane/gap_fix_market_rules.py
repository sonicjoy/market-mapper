"""Harvest mapping_market_rules from RFQ demand.

Name-match books bind to an Optic market. An unknown Novig type proposes a
tip ignore instead of growing the Python ignore set.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import _infer_leagues, _parse_symbol
from mappers.control_plane.gap_fix_novig_rfq import novig_rule_status
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_inventory_league import LEAGUE_META_KEY, MARKET_TYPE_KEY
from mappers.control_plane.gap_market_bind import live_optic_census
from mappers.control_plane.pin_flow_markets import MarketRuleObservation, draft_and_verify_market_rules
from mappers.exchanges.crypto_com import (
    FIGHT_LINE,
    FIGHT_PROP,
    GAME_LINE,
    GAME_PROP,
    PLAYER_PROP,
    TEAM_PROP,
    crypto_market_rule_source_key_type,
)
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK

logger = logging.getLogger(__name__)

MAX_MARKET_RULES = 16
CatalogueFn = Callable[[str], dict[str, Any]]
FixturesFn = Callable[..., list[dict[str, Any]]]


def harvest_missing_market_rules(
    store: Any,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str, str]],
    *,
    fixtures_fn: FixturesFn | None = None,
    catalogue_fn: CatalogueFn | None = None,
) -> None:
    """RFQ-demand market rules after alias probes; own cap per tick."""
    before = len(pins)
    observations = _observations_from_inventory(
        store,
        items,
        fixtures_fn=fixtures_fn,
        catalogue_fn=catalogue_fn,
    )
    drafted, draft_skipped = draft_and_verify_market_rules(
        store, observations[:MAX_MARKET_RULES * 2],
    )
    skipped.extend(draft_skipped)
    for pin in drafted:
        rules = pin.get("rules") or []
        book_rule = next((r for r in rules if str(r.get("sportsbook") or "") != "optic"), None)
        if book_rule is None:
            continue
        key = (
            str(pin.get("league") or ""),
            str(book_rule.get("sportsbook") or ""),
            str(book_rule.get("source_key_type") or ""),
            str(book_rule.get("source_key") or ""),
        )
        if key in seen or len([p for p in pins if _is_market_pin(p)]) >= MAX_MARKET_RULES:
            continue
        seen.add(key)
        pins.append(pin)
    logger.info(
        "pipeline gap-fix stage=probe book=market_rules pins=%d obs=%d",
        len(pins) - before,
        len(observations),
    )


def _observations_from_inventory(
    store: Any,
    items: list[RfqGapItem],
    *,
    fixtures_fn: FixturesFn | None,
    catalogue_fn: CatalogueFn | None,
) -> list[MarketRuleObservation]:
    out: list[MarketRuleObservation] = []
    census_cache: dict[str, set[str]] = {}
    for item in items:
        obs = _observation_for_item(
            store,
            item,
            fixtures_fn=fixtures_fn,
            catalogue_fn=catalogue_fn,
            census_cache=census_cache,
        )
        if obs is not None:
            out.append(obs)
    out.sort(key=lambda row: -int(row.get("demand") or 0))
    return _dedupe_observations(out)


def _dedupe_observations(rows: list[MarketRuleObservation]) -> list[MarketRuleObservation]:
    """One observation per (league, book, key type, source key); keep highest demand."""
    seen: dict[tuple[str, str, str, str], MarketRuleObservation] = {}
    order: list[tuple[str, str, str, str]] = []
    for row in rows:
        key = (
            str(row.get("league") or ""),
            str(row.get("sportsbook") or ""),
            str(row.get("source_key_type") or ""),
            str(row.get("source_key") or ""),
        )
        prior = seen.get(key)
        if prior is None:
            seen[key] = row
            order.append(key)
            continue
        if int(row.get("demand") or 0) > int(prior.get("demand") or 0):
            seen[key] = row
    return [seen[key] for key in order]


def _observation_for_item(
    store: Any,
    item: RfqGapItem,
    *,
    fixtures_fn: FixturesFn | None,
    catalogue_fn: CatalogueFn | None,
    census_cache: dict[str, set[str]],
) -> MarketRuleObservation | None:
    meta = dict(item.meta or {})
    if item.book == "crypto":
        return _crypto_obs(store, item, meta, catalogue_fn, fixtures_fn, census_cache)
    if item.book == "polymarket":
        return _poly_obs(store, item, meta, fixtures_fn, census_cache)
    if item.book == "prophetx":
        return _px_obs(store, item, meta, fixtures_fn, census_cache)
    if item.book == "novig":
        return _novig_obs(store, item, meta)
    return None


def _crypto_obs(
    store: Any,
    item: RfqGapItem,
    meta: dict[str, str],
    catalogue_fn: CatalogueFn | None,
    fixtures_fn: FixturesFn | None,
    census_cache: dict[str, set[str]],
) -> MarketRuleObservation | None:
    league = str(meta.get("league") or "").strip()
    market_group = str(meta.get("market_group") or meta.get("meta_predict_market_type") or "").strip()
    contract_type = str(meta.get("contract_type") or "").strip()
    cat: dict[str, Any] = {}
    if catalogue_fn is not None and (not contract_type or not market_group or not league):
        try:
            cat = catalogue_fn(item.key)
        except Exception:
            return None
        contract_type = contract_type or str(cat.get("contract_type") or "").strip()
        market_group = market_group or str(
            cat.get("market_type") or cat.get("meta_predict_market_type") or "",
        ).strip()
        league = league or _crypto_league(store, item.key, cat)
    if not league:
        league = _crypto_league(store, item.key, cat)
    if market_group not in {
        GAME_LINE, FIGHT_LINE, PLAYER_PROP, TEAM_PROP, GAME_PROP, FIGHT_PROP,
    }:
        return None
    if not league or not contract_type:
        return None
    live = _cached_census(store, league, fixtures_fn, census_cache)
    source_key_type = crypto_market_rule_source_key_type(market_group)
    return {
        "league": league,
        "sportsbook": "crypto.com",
        "source_key": contract_type,
        "source_key_type": source_key_type,
        "demand": item.demand,
        "market_group": market_group,
        "evidence_refs": [f"gap:{item.key}"],
        "live_optic_market_ids": live,
    }


def _crypto_league(store: Any, symbol: str, cat: dict[str, Any]) -> str:
    parsed = _parse_symbol(symbol)
    token = str((parsed or {}).get("token") or "")
    slugs = _infer_leagues(store, token, None) if token else []
    if len(slugs) == 1:
        return slugs[0]
    meta_league = str(cat.get("league") or cat.get("meta_league") or "").strip()
    if meta_league:
        needle = meta_league.casefold()
        for slug in slugs:
            if slug.casefold() == needle:
                return slug
        rid = getattr(store, "current_rule_set_id", None)
        if rid:
            for row in store.leagues_for(rid):
                if str(row.league or "").casefold() == needle:
                    return str(row.league)
    return slugs[0] if slugs else ""


def _poly_obs(
    store: Any,
    item: RfqGapItem,
    meta: dict[str, str],
    fixtures_fn: FixturesFn | None,
    census_cache: dict[str, set[str]],
) -> MarketRuleObservation | None:
    usa = _usa_source_obs(store, item, meta, fixtures_fn, census_cache)
    if usa is not None:
        return usa
    kind = str(meta.get("kind") or "").strip()
    league = str(meta.get("league") or "").strip()
    platform = str(meta.get("platform") or "").lower()
    if not kind or not league:
        return None
    book = POLY_USA_BOOK if "us" in platform else "polymarket"
    live = _cached_census(store, league, fixtures_fn, census_cache)
    return {
        "league": league,
        "sportsbook": book,
        "source_key": kind,
        "source_key_type": "kind",
        "demand": item.demand,
        "evidence_refs": [f"gap:{item.key}"],
        "live_optic_market_ids": live,
    }


def _usa_source_obs(
    store: Any,
    item: RfqGapItem,
    meta: dict[str, str],
    fixtures_fn: FixturesFn | None,
    census_cache: dict[str, set[str]],
) -> MarketRuleObservation | None:
    """Polymarket US raw sportsMarketType, with up to three example tickers."""
    smt = str(meta.get("sports_market_type") or "").strip()
    if not smt:
        return None
    league = str(meta.get("league") or "").strip() or _league_from_inner(store, item.key)
    if not league:
        return None
    live = _cached_census(store, league, fixtures_fn, census_cache)
    refs = [f"gap:{item.key}"]
    refs.extend(
        f"polymarket_usa:ticker:{ticker}" for ticker in _sample_tickers(meta)[:3]
    )
    line = str(meta.get("line") or "").strip()
    side = str(meta.get("long_description") or meta.get("side") or "").strip()
    if line:
        refs.append(f"polymarket_usa:line:{line}")
    if side:
        refs.append(f"polymarket_usa:side:{side}")
    return {
        "league": league,
        "sportsbook": POLY_USA_BOOK,
        "source_key": smt,
        "source_key_type": "sports_market_type",
        "demand": item.demand,
        "evidence_refs": refs,
        "live_optic_market_ids": live,
    }


def _sample_tickers(meta: dict[str, str]) -> list[str]:
    raw = str(meta.get("market_ticker") or "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _league_from_inner(store: Any, key: str) -> str:
    needle = str(key or "").strip().casefold()
    if not needle or needle == "(null)":
        return ""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return ""
    for row in store.leagues_for(rid):
        if str(row.league or "").casefold() == needle:
            return str(row.league)
    return ""


def _novig_obs(
    store: Any,
    item: RfqGapItem,
    meta: dict[str, str],
) -> MarketRuleObservation | None:
    """Unknown Novig types become a tip ignore. The Python table does not grow."""
    market_type = str(meta.get(MARKET_TYPE_KEY) or "").strip()
    token = str(meta.get(LEAGUE_META_KEY) or "").strip()
    if not market_type or not token:
        return None
    status, _mapped, league = novig_rule_status(
        _league_rows(store), _rule_rows(store), token, market_type,
    )
    if status != "unknown" or not league:
        return None
    return {
        "league": league,
        "sportsbook": "novig",
        "source_key": market_type,
        "source_key_type": "market_type",
        "action": "ignore",
        "demand": item.demand,
        "evidence_refs": [f"gap:{item.key}", f"novig:market_type:{market_type}"],
    }


def _league_rows(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    return list(store.leagues_for(rid))


def _rule_rows(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "market_rules_for"):
        return []
    return list(store.market_rules_for(rid))


def _px_obs(
    store: Any,
    item: RfqGapItem,
    meta: dict[str, str],
    fixtures_fn: FixturesFn | None,
    census_cache: dict[str, set[str]],
) -> MarketRuleObservation | None:
    league = str(meta.get("league") or "").strip()
    market_name = str(meta.get("market_name") or "").strip()
    if not league or not market_name:
        return None
    live = _cached_census(store, league, fixtures_fn, census_cache)
    return {
        "league": league,
        "sportsbook": "px",
        "source_key": market_name,
        "source_key_type": "market_name",
        "demand": item.demand,
        "match_operator": str(meta.get("match_operator") or "exact"),
        "evidence_refs": [f"gap:{item.key}"],
        "live_optic_market_ids": live,
    }


def _cached_census(
    store: Any,
    league: str,
    fixtures_fn: FixturesFn | None,
    cache: dict[str, set[str]],
) -> set[str]:
    if league not in cache:
        cache[league] = live_optic_census(store, league, fixtures_fn)
    return cache[league]


def _is_market_pin(pin: dict[str, Any]) -> bool:
    return str(pin.get("kind") or "") == "mapping_market_rules"
