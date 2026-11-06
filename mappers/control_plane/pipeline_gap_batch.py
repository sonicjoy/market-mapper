"""Group RFQ gap inventory by tip league: one drain card per league, every book on it."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from BigQuery.crypto_gap_config import league_keys_for_prefix
from mappers.control_plane.chat_tools_dkex_mapping import dkex_league_token
from mappers.control_plane.gap_fix_dkex_leagues import DKEX_VENUE_BY_SLUG
from mappers.control_plane.gap_inventory import (
    RfqGapItem,
    series_bucket,
)
from mappers.control_plane.gap_inventory_league import LEAGUE_META_KEY
from mappers.control_plane.underdog_legacy_ticker import venue_token_from_body
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG
from mappers.profiles._builders import exchange_settings
from mappers.seed.poly_usa_exchange import us_league_code

UNKNOWN_LEAGUE = "unknown"
# Keys one league card walks. Raise with worker memory.
CARD_KEYS = 100

_CRYPTO_SPORT = re.compile(r"^NX\.F\.OPT\.([A-Z0-9]+)", re.I)
_Alias = dict[tuple[str, str], str]
LeagueCard = tuple[str, list[RfqGapItem]]


def plan_league_cards(
    store: Any,
    items: list[RfqGapItem],
    *,
    seats: int = CARD_KEYS,
) -> list[LeagueCard]:
    """Every league on the page, hottest first, each seated to at most ``seats`` keys."""
    league_of = league_resolver(store)
    grouped: dict[str, list[RfqGapItem]] = {}
    for item in items:
        grouped.setdefault(league_of(item), []).append(item)
    cards = [(league, seat_items(group, seats)) for league, group in grouped.items()]
    cards.sort(key=lambda card: (-sum(item.demand for item in card[1]), card[0]))
    return cards


def seat_items(items: list[RfqGapItem], seats: int) -> list[RfqGapItem]:
    """Split ``seats`` evenly across books by demand; unused seats go to books with more keys."""
    by_book: dict[str, list[RfqGapItem]] = {}
    for item in sorted(items, key=lambda row: -row.demand):
        by_book.setdefault(item.book, []).append(item)
    taken = dict.fromkeys(by_book, 0)
    active = list(by_book)
    left = seats
    while left > 0 and active:
        share = max(1, left // len(active))
        for book in active:
            take = min(share, len(by_book[book]) - taken[book], left)
            taken[book] += take
            left -= take
        active = [book for book in active if taken[book] < len(by_book[book])]
    seated = [item for book, rows in by_book.items() for item in rows[: taken[book]]]
    return sorted(seated, key=lambda row: -row.demand)


def league_resolver(store: Any) -> Callable[[RfqGapItem], str]:
    """Tip league slug for an inventory key, or ``unknown`` when the tip has no rule for it."""
    rows = _tip_rows(store)
    aliases: _Alias = {}
    for row in rows:
        _alias_row(aliases, row)
    slugs = frozenset(str(getattr(row, "league", "") or "") for row in rows) - {""}

    def league_of(item: RfqGapItem) -> str:
        label = card_league(item, aliases)
        return label if label in slugs else UNKNOWN_LEAGUE

    return league_of


def card_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip league slug when the book token maps to one league, else the series bucket."""
    if item.book == "polymarket":
        return _poly_league(item, aliases)
    if item.book == "crypto":
        return _crypto_league(item)
    if item.book == "underdog":
        return _underdog_league(item, aliases)
    if item.book == "dkex":
        return _dkex_league(item, aliases)
    if item.book == "huddle":
        return _huddle_league(item, aliases)
    if item.book in {"novig", "prophetx"}:
        return _looked_up_league(item, aliases)
    if item.book == "sxbet":
        # attach_league_tokens put the tip slug itself here (sxbet_leagues).
        return str((item.meta or {}).get(LEAGUE_META_KEY) or "") or "sxbet"
    return series_bucket(item.book, item.key)


def _looked_up_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip slug for the league token the planner looked up (Novig league, ProphetX tournament)."""
    looked_up = str((item.meta or {}).get(LEAGUE_META_KEY) or "")
    return (_slug_for(aliases, item.book, looked_up) if looked_up else None) or item.book


def _underdog_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip slug for a UDX ticker. Tip pin wins; else the unique venue-token map."""
    key = item.key.strip().upper()
    body = key[3:] if key.startswith("UDX") else key
    token = venue_token_from_body(body)
    if not token:
        return "underdog"
    pinned = _slug_for(aliases, "underdog", token)
    if pinned:
        return pinned
    return VENUE_TOKEN_TO_LEAGUE_SLUG.get(token, "underdog")


def _dkex_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip slug for a DKEX symbol. Ambiguous static tokens stay off a league card."""
    league = dkex_league_token(item.key)
    if not league:
        return "dkex"
    pinned = _slug_for(aliases, "dkex", league)
    if pinned:
        return pinned
    static = [
        slug for slug, token in DKEX_VENUE_BY_SLUG.items()
        if token.upper() == league.upper()
    ]
    if len(static) == 1:
        return static[0]
    return "dkex"


def _huddle_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip slug when the key matches one competition, or the only Huddle league."""
    listed = _listed_league(item, aliases)
    if listed != item.book:
        return listed
    slugs = {slug for (book, _token), slug in aliases.items() if book == "huddle"}
    if len(slugs) == 1:
        return next(iter(slugs))
    return "huddle"


def _slug_for(aliases: _Alias, book: str, token: str) -> str | None:
    """Slug when this book token is pinned on exactly one tip league."""
    want = token.strip().casefold()
    slugs = {
        slug
        for (alias_book, alias_token), slug in aliases.items()
        if alias_book == book and alias_token.casefold() == want
    }
    if len(slugs) == 1:
        return next(iter(slugs))
    return None


def _listed_league(item: RfqGapItem, aliases: _Alias) -> str:
    """Tip slug when the key starts with one source id of this book."""
    token = item.key.strip().casefold()
    slugs = {
        slug
        for (book, prefix), slug in aliases.items()
        if book == item.book and prefix and token.startswith(prefix)
    }
    if len(slugs) == 1:
        return next(iter(slugs))
    return item.book


def _poly_league(item: RfqGapItem, aliases: _Alias) -> str:
    token = item.key.strip().casefold()
    return aliases.get(("poly", token)) or aliases.get(("us", token)) or f"poly:{token}"


def _crypto_league(item: RfqGapItem) -> str:
    matched = _CRYPTO_SPORT.match(item.key.strip().upper())
    token = matched.group(1) if matched else ""
    if token:
        keys = league_keys_for_prefix(f"NX.F.OPT.{token}")
        if len(keys) == 1:
            return keys[0]
    return series_bucket("crypto", item.key)


def _tip_rows(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    return [row for row in store.leagues_for(rid) if not getattr(row, "tombstone", False)]


def _alias_row(out: _Alias, row: Any) -> None:
    slug = str(getattr(row, "league", "") or "")
    if not slug:
        return
    code = us_league_code(row)
    if code:
        out[("us", code.casefold())] = slug
    for ex in getattr(row, "exchanges", None) or []:
        _alias_exchange(out, slug, ex)


def _alias_exchange(out: _Alias, slug: str, ex: dict[str, Any]) -> None:
    book = str(ex.get("sportsbook") or "").lower()
    if book == "novig":
        token = str(exchange_settings(ex, "novig").get("league") or "").strip()
        if token:
            out[("novig", token.casefold())] = slug
        return
    if book in {"px", "prophetx", "prophet x", "prophet_x"}:
        token = _exchange_token(ex, setting_key="tournament_id", settings_first=True)
        if token:
            out[("prophetx", token.casefold())] = slug
        return
    if book in {"underdog", "dkex"}:
        token = _exchange_token(ex).upper()
        if token:
            out[(book, token)] = slug
        return
    if book == "huddle":
        token = _exchange_token(ex, setting_key="competition_id").casefold()
        if token:
            out[("huddle", token)] = slug
        return
    if book != "polymarket" or ex.get("enabled") is False:
        return
    settings = ex.get("settings") or {}
    if isinstance(settings, dict):
        prefix = str(settings.get("slug_prefix") or "").strip().casefold()
        if prefix:
            out[("poly", prefix)] = slug


def _exchange_token(
    ex: dict[str, Any],
    *,
    setting_key: str = "league",
    settings_first: bool = False,
) -> str:
    """source_league_id or the settings token for this book, in the order the mapper reads them."""
    settings = ex.get("settings") or {}
    setting = str(settings.get(setting_key) or "").strip() if isinstance(settings, dict) else ""
    source = str(ex.get("source_league_id") or "").strip()
    return (setting or source) if settings_first else (source or setting)
