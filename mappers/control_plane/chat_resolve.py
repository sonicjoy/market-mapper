"""Normalize a Mapper Chat message into books, league, entity, market ids."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fetch.polymarket_usa_gateway import find_us_symbol
from mappers.control_plane.chat_catalog import (
    SPORTS,
    as_league_slug,
    league_slugs,
    match_league,
    named_sportsbooks,
    wants_all_sportsbooks,
)
from mappers.control_plane.chat_tools_dkex_mapping import find_dkex_symbol
from mappers.control_plane.suggest_markets import leagues_for_market_id
from mappers.control_plane.underdog_legacy_ticker import find_udx_ticker
from mappers.exchanges.poly_slug import find_poly_slug
from mappers.vocab.poly_usa_console import llm_prompt_fragment, parsed_source_keys

_SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", re.I)
_ENTITY_LEAD = re.compile(
    r"\b(?:entity|player|fighter|team|alias)\s+"
    r"([A-Za-z][A-Za-z'-]{2,40}(?:\s+[A-Za-z][A-Za-z'-]{1,40}){0,3})\b",
    re.I,
)
_ADD_NAME = re.compile(
    r"\b(?:add|pin|map|find|lookup|search|about)\s+"
    r"([A-Za-z][A-Za-z'-]{2,40}(?:\s+[A-Za-z][A-Za-z'-]{1,40}){0,3})\b",
    re.I,
)
_ENTITY_TAIL = re.compile(
    r"\s+(?:for|on|in|to)\s+([a-z][a-z0-9_]+(?:[\s-][a-z][a-z0-9_]+)*)$",
    re.I,
)
_EMBEDDED_NUM = re.compile(r"\b(\d{6,})\b")
_EMBEDDED_UUID = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.I,
)
_ENABLE = re.compile(r"\b(enable|add|onboard|map)\b", re.I)
_PIN_CMD = re.compile(r"\bpin\b", re.I)
_LEAGUE_NOUN = re.compile(r"\b(league|competition|tournament|series)\b", re.I)
_FOOTBALL_PROP = re.compile(
    r"player_pass|player_rush|player_receiv|player_interception"
    r"|first_touchdown|player_touchdown|player_longest"
    r"|team_total_touchdown|team_total_field_goal",
    re.I,
)
_KX = re.compile(r"\b(KX[A-Z0-9-]+)\b", re.I)
_NX = re.compile(r"\b(NX\.F\.[A-Z0-9.-]+)\b", re.I)
_VS = re.compile(r"\s+vs\.?\s+", re.I)
_HEX16 = re.compile(r"\b([A-F0-9]{16})\b", re.I)
_POLY_CID = re.compile(r"^0x[0-9a-f]{64}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{32,80}$", re.I)
_NUM_ID = re.compile(r"^\d{6,}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_SKIP_NAMES = frozenset(
    {
        "a", "add", "alias", "aliases", "all", "an", "and", "are", "code", "enable",
        "entity", "esport", "esports", "for", "game", "games", "is", "it", "kalshi",
        "league", "leagues", "map", "mapping", "market", "markets", "new", "optic",
        "pin", "player", "please", "moneyline", "polymarket", "rule", "rules",
        "spread", "sportsbook", "sportsbooks", "team", "the", "these", "this",
        "to", "total", "us", "was", "we", "were", "any",
    }
)
_SPORT_NAMES = frozenset({s.casefold() for s in SPORTS} | {"esport"})
_SINGLES = frozenset({"moneyline", "point_spread", "team_total"})

KALSHI = "kalshi"
NX = "nx"
POLY_CID = "poly_cid"
POLY_SLUG = "poly_slug"
US_SYMBOL = "us_symbol"
UDX_TICKER = "udx_ticker"
OPTIC_HEX = "optic_hex"
UUID = "uuid"
NUMERIC = "numeric"
HEX = "hex"


@dataclass(frozen=True)
class SourceId:
    """One pasted exchange or catalogue identifier."""

    kind: str
    value: str


@dataclass(frozen=True)
class ResolvedQuery:
    """Deterministic slots extracted from a trader message."""

    books: tuple[str, ...] = ()
    league: str = ""
    entity_name: str = ""
    market_ids: tuple[str, ...] = ()
    verb: str = ""
    source_ids: tuple[SourceId, ...] = ()
    has_fixture_vs: bool = False


def resolve_query(
    message: str,
    *,
    tip_leagues: set[str] | None = None,
    page_league: str = "",
) -> ResolvedQuery:
    """Books, league, entity name, pasted ids, and exchange symbols."""
    books = tuple(named_sportsbooks(message))
    market_ids = market_ids_from_message(message)
    source_ids = source_ids_from_message(message)
    league = (
        (match_league(message, extra=tip_leagues) or "")
        or _league_tail_from_message(message, tip_leagues)
        or league_from_market_ids(market_ids)
        or page_league.strip()
    )
    entity = entity_name_from_message(message, tip_leagues=tip_leagues)
    return ResolvedQuery(
        books=books,
        league=league,
        entity_name=entity,
        market_ids=market_ids,
        verb=_verb(message, entity, market_ids),
        source_ids=source_ids,
        has_fixture_vs=bool(_VS.search(message)),
    )


def source_ids_from_message(message: str) -> tuple[SourceId, ...]:
    """Kalshi / NX / poly / optic hex ids in mention order."""
    found: list[SourceId] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, value: str) -> None:
        key = (kind, value.upper() if kind == KALSHI else value)
        if key in seen:
            return
        seen.add(key)
        found.append(SourceId(kind=kind, value=value))

    for token in _KX.findall(message):
        _add(KALSHI, token.upper())
    for token in _NX.findall(message):
        _add(NX, token.upper())
    for match in _HEX16.finditer(message):
        _add(OPTIC_HEX, match.group(1).upper())
    for match in _EMBEDDED_NUM.finditer(message):
        _add(NUMERIC, match.group(1))
    for match in _EMBEDDED_UUID.finditer(message):
        _add(UUID, match.group(1))
    other = other_probe_id(message)
    if other:
        kind = _classify_other_id(other)
        if kind:
            _add(kind, other)
    return tuple(found)


def other_probe_id(message: str) -> str:
    """Polymarket/SX hex, numeric PX, Novig UUID, US symbol, or official slug."""
    raw = message.strip()
    if _KX.search(raw) or _NX.search(raw):
        return ""
    if _POLY_CID.fullmatch(raw) or _HEX.fullmatch(raw) or _NUM_ID.fullmatch(raw):
        return raw
    if _UUID.fullmatch(raw):
        return raw
    udx = find_udx_ticker(raw)
    if udx:
        return udx
    return find_us_symbol(raw) or find_poly_slug(raw) or ""


def kalshi_ids(resolved: ResolvedQuery) -> tuple[str, ...]:
    return tuple(s.value for s in resolved.source_ids if s.kind == KALSHI)


def nx_ids(resolved: ResolvedQuery) -> tuple[str, ...]:
    return tuple(s.value for s in resolved.source_ids if s.kind == NX)


def probe_source_id(resolved: ResolvedQuery) -> str:
    """First pasted id for probe_source_mapping (not KX/NX/Optic hex)."""
    skip = frozenset({KALSHI, NX, OPTIC_HEX})
    for sid in resolved.source_ids:
        if sid.kind not in skip:
            return sid.value
    return ""


def has_probe_source(resolved: ResolvedQuery) -> bool:
    """True when resolve_query found a gap-probe symbol."""
    return bool(kalshi_ids(resolved) or nx_ids(resolved) or probe_source_id(resolved))


def has_exchange_symbol(resolved: ResolvedQuery, message: str) -> bool:
    if resolved.source_ids:
        return True
    return bool(
        find_udx_ticker(message)
        or find_dkex_symbol(message)
        or find_us_symbol(message)
        or find_poly_slug(message)
    )


def market_ids_from_message(message: str) -> tuple[str, ...]:
    """Snake_case Optic ids plus a few single-token market names, mention order."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _SNAKE.finditer(message):
        token = match.group(1).strip().lower().replace("-", "_")
        if token not in seen:
            seen.add(token)
            found.append(token)
    lower = message.lower()
    for token in _SINGLES:
        if token in seen:
            continue
        if re.search(rf"\b{re.escape(token)}\b", lower):
            seen.add(token)
            found.append(token)
    return tuple(found)


def league_from_market_ids(market_ids: tuple[str, ...]) -> str:
    """Unique spine league, else nfl when the paste is football player props."""
    unique: list[str] = []
    for mid in market_ids:
        slugs = leagues_for_market_id(mid)
        if len(slugs) != 1:
            continue
        if slugs[0] not in unique:
            unique.append(slugs[0])
    if len(unique) == 1:
        return unique[0]
    if any(_FOOTBALL_PROP.search(mid) for mid in market_ids):
        return "nfl"
    return ""


def entity_name_from_message(
    message: str, *, tip_leagues: set[str] | None = None,
) -> str:
    """Person/club name after entity/add/pin; empty when it is a league slug."""
    if _is_pin_command(message):
        return ""
    lead = _ENTITY_LEAD.search(message)
    name = _clean_name(lead.group(1) if lead else "") or _clean_name(_add_name(message))
    name = _strip_entity_tail(name, tip_leagues)
    if not name:
        return ""
    slugs = {s.casefold() for s in (tip_leagues or set())} | {
        s.casefold() for s in league_slugs()
    }
    if name.casefold().replace(" ", "_") in slugs:
        return ""
    return name


def poly_usa_parser_gaps(market_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Pasted ids Polymarket US Path 2 cannot parse today (needs_code)."""
    parsed = parsed_source_keys()
    return tuple(mid for mid in market_ids if mid not in parsed)


def poly_usa_llm_prompt_fragment() -> str:
    """Poly US wired enums for the LLM system card (from the enum table)."""
    return llm_prompt_fragment()


def is_entity_query(message: str, resolved: ResolvedQuery) -> bool:
    """True when the trader named a person/club to look up or add."""
    if not resolved.entity_name or resolved.market_ids:
        return False
    if resolved.has_fixture_vs:
        return False
    if _is_pin_command(message):
        return False
    if _LEAGUE_NOUN.search(message):
        return False
    if named_sportsbooks(message) and _ENABLE.search(message):
        lead = _ENTITY_LEAD.search(message)
        return bool(lead) and _clean_name(lead.group(1)) == resolved.entity_name
    return True


def _classify_other_id(raw: str) -> str:
    if _POLY_CID.fullmatch(raw):
        return POLY_CID
    if _UUID.fullmatch(raw):
        return UUID
    if _NUM_ID.fullmatch(raw):
        return NUMERIC
    if _HEX.fullmatch(raw):
        return HEX
    if find_us_symbol(raw):
        return US_SYMBOL
    if find_udx_ticker(raw):
        return UDX_TICKER
    if find_poly_slug(raw):
        return POLY_SLUG
    return ""


def _add_name(message: str) -> str:
    found = _ADD_NAME.search(message)
    return found.group(1) if found else ""


def _is_pin_command(message: str) -> bool:
    if not _PIN_CMD.search(message) or not named_sportsbooks(message):
        return False
    return any(
        not tok.isdigit() for tok in re.findall(r"\b([A-Z0-9]{2,12})\b", message)
    )


_LEAGUE_FOR_TAIL = re.compile(
    r"\bfor\s+([a-z][a-z0-9_]+(?:[\s-][a-z][a-z0-9_]+)*)$",
    re.I,
)


def _league_tail_from_message(message: str, tip_leagues: set[str] | None) -> str:
    """League slug after ``for epl`` / ``for nba`` even when not on the tip yet."""
    if wants_all_sportsbooks(message):
        return ""
    match = _LEAGUE_FOR_TAIL.search(message.strip())
    if not match:
        return ""
    tail_text = match.group(1).strip()
    if named_sportsbooks(tail_text):
        return ""
    return as_league_slug(tail_text, extra=tip_leagues) or ""


def _strip_entity_tail(name: str, tip_leagues: set[str] | None) -> str:
    """Drop trailing ``for epl`` / ``on atp`` when the tail is a league slug."""
    text = name.strip()
    match = _ENTITY_TAIL.search(text)
    if not match:
        return text
    tail = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
    slugs = {s.casefold() for s in (tip_leagues or set())} | {
        s.casefold() for s in league_slugs()
    }
    if tail in slugs or match_league(match.group(1), extra=tip_leagues):
        return text[: match.start()].strip()
    return text


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split()).strip(" .,")
    key = name.casefold()
    if not name or key in _SKIP_NAMES or key in _SPORT_NAMES:
        return ""
    return name


def _verb(message: str, entity: str, market_ids: tuple[str, ...]) -> str:
    if _ENABLE.search(message) and market_ids:
        return "enable"
    if entity and _ENABLE.search(message):
        return "add"
    if entity:
        return "lookup"
    return ""
