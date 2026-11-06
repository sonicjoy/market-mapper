"""Hybrid intent scoring for Mapper Chat (V1: entity_alias focus)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mappers.control_plane.chat_catalog import (
    match_league,
    named_sportsbooks,
    slug_from_message,
    wants_all_sportsbooks,
)
from mappers.control_plane.chat_resolve import ResolvedQuery, is_entity_query, resolve_query
from mappers.control_plane.suggest_markets import leagues_for_market_id

_ALIAS_KW = re.compile(
    r"\b(alias(?:es)?|pin|map(?:s|ping|pings)?|ticker|code|optic[_\s-]?id"
    r"|teams?|players?|fighters?|entit(?:y|ies))\b",
    re.I,
)
# Unambiguously alias-only tokens; excludes the verb "map", which also appears
# in market/league questions ("what markets do we map").
_ALIAS_STRONG = re.compile(
    r"\b(alias(?:es)?|pin|ticker|code|optic[_\s-]?id|fighters?|entit(?:y|ies))\b",
    re.I,
)
_LEAGUE_KW = re.compile(r"\b(league|competition|tournament|series)\b", re.I)
_MARKET_KW = re.compile(
    r"\b(market[_\s-]?rules?|markets?|taxonomy|spread|moneyline|total)\b",
    re.I,
)
_AUDIT_KW = re.compile(r"\b(what do we have|show|find|lookup|search|existing|rules?\b)", re.I)
_AUDIT_STRONG = re.compile(
    r"\b(which|list|find|lookup|search|existing|missing"
    r"|coverage|parity|how many|do we (?:have|map|support)"
    r"|don'?t have|do not have|no entities)\b",
    re.I,
)
_AUDIT_WEAK = re.compile(r"\b(what|show)\b", re.I)
_AUDIT_NOUN = re.compile(
    r"\b(alias(?:es)?|pin|map(?:s|ped|ping|pings)?|leagues?|markets?"
    r"|rules?|entities|entity|ticker|coverage|gaps?|unmapped|optic|kalshi"
    r"|teams?|players?|fighters?|code)\b",
    re.I,
)
_COUNT_QUESTION = re.compile(
    r"\b(how many|how much|count of|number of|count the)\b",
    re.I,
)
_IGNORED_KW = re.compile(r"\bignor(?:e|ed|ing|es)\b", re.I)
_LEAGUE_NOUN = re.compile(r"\bleagues?\b", re.I)
# League↔exchange config lives on the Leagues tab, so "which platforms/books
# have X mapped" is a leagues question, not an entities one.
_PLATFORM_NOUN = re.compile(r"\b(platforms?|sportsbooks?|books?|exchanges?)\b", re.I)
_CONFIRM_KW = re.compile(r"^\s*(yes|y|ok|okay|add to cart|confirm|do it)\s*$", re.I)
_SWEEP_VERB = re.compile(r"\b(sweep|harvest)\b", re.I)
_SWEEP_CRYPTO_PAIR = re.compile(
    r"(?:"
    r"\b(?:sweep|harvest)\b.{0,80}\bcrypto"
    r"|\bcrypto.{0,80}\b(?:sweep|harvest)\b"
    r")",
    re.I,
)
_MISSING_CRYPTO_IDS = re.compile(r"\bmissing crypto[_\s-]?ids?\b", re.I)
_FIX_GAPS = re.compile(r"\b(fix|harvest)\s+(the\s+)?gaps\b", re.I)
_PIN_CMD = re.compile(r"\bpin\b", re.I)
_ONBOARD_VERB = re.compile(r"\b(add|onboard|new|create|enable)\b", re.I)
_MAP_LEAGUE = re.compile(
    r"\bmap\b.{0,48}\bleagues?\b|\bleagues?\b.{0,48}\bmap\b",
    re.I,
)
# Gap / coverage dumps look like commands after keyword extraction; keep them off
# the deterministic pin path so the LLM can read the report.
_REPORT_KW = re.compile(
    r"\b(gaps?|events?|reasons?|actionable|unmapped|coverage)\b",
    re.I,
)
_REPORT_LIST = re.compile(r"(?:^|\n)\s*[-*•]\s|\[[a-z0-9_]+\]", re.I)
_LEAGUE_CODE_SKIP = frozenset({"epl", "nba", "mlb", "nfl", "ufc", "atp", "wta"})
# "do we have cs2 mappings?" names a subject that is not on the tip yet; still
# search Rules for it instead of opening an unfiltered table.
_SUBJECT_QUESTION = re.compile(
    r"\bdo (?:we|you) (?:have|map|support)\s+(?:(?:any|a|an|the|some)\s+)?([a-z][a-z0-9_.-]{1,31})\b",
    re.I,
)
_SUBJECT_SKIP = frozenset(
    {
        "alias",
        "aliases",
        "coverage",
        "entities",
        "league",
        "leagues",
        "map",
        "mapping",
        "mappings",
        "maps",
        "market",
        "markets",
        "players",
        "rule",
        "rules",
        "teams",
        "this",
        "that",
        "these",
        "those",
        "ticker",
        "it",
    }
)
# Real pin commands are short ("pin M05 on kalshi for epl"); pastes are longer.
_PIN_CMD_MAX_CHARS = 160


@dataclass(frozen=True)
class IntentScore:
    """Deterministic intent + confidence before optional LLM."""

    intent: str
    confidence: float
    league_hint: str | None = None
    code_hint: str | None = None
    sportsbook_hint: str | None = None
    resolved: ResolvedQuery = ResolvedQuery()


def score_intent(
    message: str,
    *,
    tip_leagues: set[str],
    resolved: ResolvedQuery | None = None,
) -> IntentScore:
    """Score a user message and prefer one artifact kind.

    Action routing only. Unmatched turns resume session focus in dispatch.
    """
    text = message.strip()
    if not text:
        return IntentScore("clarify", 0.2)
    if _CONFIRM_KW.match(text):
        return IntentScore("confirm", 0.99)
    if wants_gap_fix(text):
        return IntentScore("entity_alias", 0.95)
    query = resolved or resolve_query(text, tip_leagues=tip_leagues)
    league = query.league or _match_league(text, tip_leagues)
    book = query.books[0] if query.books else None
    if wants_crypto_sweep(text):
        return IntentScore(
            "entity_alias",
            0.95,
            league_hint=league,
            sportsbook_hint="crypto.com",
            resolved=query,
        )
    pin_cmd = bool(_PIN_CMD.search(text)) and not _looks_like_report(text)
    if _wants_audit(text, pin_cmd=pin_cmd, league=league):
        return _audit_intent(league, text, query)
    onboard = wants_league_onboard(text, tip_leagues=tip_leagues, resolved=query)
    if onboard:
        hint = league or match_league(text, extra=tip_leagues)
        conf = 0.93 if hint else 0.9
        return IntentScore("mapping_league", conf, league_hint=hint, resolved=query)
    if _MARKET_KW.search(text) and not _ALIAS_STRONG.search(text):
        return _market_rules_intent(league, book, query)
    if _ONBOARD_VERB.search(text) and query.market_ids and not _ALIAS_STRONG.search(text):
        return _market_rules_intent(league, book, query)
    if _ALIAS_KW.search(text) or league:
        return _alias_intent(text, league, query)
    if _AUDIT_KW.search(text) and (_AUDIT_NOUN.search(text) or league):
        return _audit_intent(league, text, query)
    # Coverage asks ("is ARS mapped on kalshi") land here; keep the code so the
    # lookup searches that token instead of the whole sentence.
    return IntentScore(
        "clarify", 0.4, league_hint=league, code_hint=_code_hint(text), resolved=query,
    )


def _audit_intent(
    league: str | None, text: str, resolved: ResolvedQuery,
) -> IntentScore:
    return IntentScore(
        "audit", 0.8, league_hint=league, code_hint=_code_hint(text), resolved=resolved,
    )


def _market_rules_intent(
    league: str | None, book: str | None, resolved: ResolvedQuery,
) -> IntentScore:
    conf = 0.92 if league else 0.75
    return IntentScore(
        "mapping_market_rules", conf, league_hint=league, sportsbook_hint=book, resolved=resolved,
    )


def _alias_intent(
    text: str, league: str | None, resolved: ResolvedQuery,
) -> IntentScore:
    # Report pastes often contain a tip league + book name + a count; do not
    # treat them as a confident single-pin command (threshold is 0.9).
    code = _code_hint(text)
    book = _book_hint(text)
    explicit_pin = bool(_PIN_CMD.search(text)) and code and book
    if _looks_like_report(text):
        conf = 0.55
    elif explicit_pin and not league:
        conf = 0.92
    else:
        conf = 0.92 if league and _ALIAS_KW.search(text) else (0.9 if league else 0.75)
    return IntentScore(
        "entity_alias",
        conf,
        league_hint=league,
        code_hint=_code_hint(text),
        sportsbook_hint=_book_hint(text),
        resolved=resolved,
    )


def audit_kind(
    message: str,
    *,
    code_hint: str | None,
    league_hint: str | None,
    page_kind: str | None = None,
) -> str:
    """Pick the Rules tab an audit question is really asking about."""
    if _MARKET_KW.search(message):
        return "market_rules"
    if _PLATFORM_NOUN.search(message):
        return "leagues"
    if _ALIAS_STRONG.search(message) or _names_entity(code_hint, league_hint):
        return "entities"
    # A known league slug ("do we have cs2 mappings?") is a coverage question.
    if _LEAGUE_NOUN.search(message) or league_hint:
        return "leagues"
    if page_kind in {"entities", "leagues", "market_rules"}:
        return page_kind
    return "entities"


def audit_subject(message: str) -> str | None:
    """Rules query term for audit questions naming a subject we do not know yet."""
    found = _SUBJECT_QUESTION.search(message)
    if not found:
        return None
    token = found.group(1)
    return None if token.lower() in _SUBJECT_SKIP else token


def _wants_audit(text: str, *, pin_cmd: bool, league: str | None) -> bool:
    """True for a Rules/coverage question, not bare 'what' / 'show'."""
    if pin_cmd or _looks_like_report(text):
        return False
    if _AUDIT_STRONG.search(text):
        return True
    if not _AUDIT_WEAK.search(text):
        return False
    return bool(_AUDIT_NOUN.search(text) or league or _code_hint(text))


def wants_gap_fix(message: str) -> bool:
    """True for a short Fix-gaps harvest command — not a pasted gap dump."""
    if is_count_question(message) or "\n" in message:
        return False
    return bool(_FIX_GAPS.search(message)) and len(message) <= _PIN_CMD_MAX_CHARS


def wants_crypto_sweep(message: str) -> bool:
    """True for an explicit crypto-id harvest — not a pin, count, or gap paste."""
    if _looks_like_report(message) or is_count_question(message):
        return False
    if _PIN_CMD.search(message) and not _SWEEP_VERB.search(message):
        return False
    if _SWEEP_CRYPTO_PAIR.search(message):
        return True
    return bool(_MISSING_CRYPTO_IDS.search(message))


def is_count_question(message: str) -> bool:
    """True when the user is asking for a quantity (how many / count of / …)."""
    return bool(_COUNT_QUESTION.search(message))


def wants_ignored_filter(message: str) -> bool:
    """True when the question scopes to ignore-action market rules."""
    return bool(_IGNORED_KW.search(message))


def wants_league_onboard(
    message: str,
    *,
    tip_leagues: set[str] | None = None,
    resolved: ResolvedQuery | None = None,
) -> bool:
    """True for add/enable/map-league (not a pin or a pasted gap dump)."""
    if _ALIAS_STRONG.search(message) or _looks_like_report(message):
        return False
    query = resolved or resolve_query(message, tip_leagues=tip_leagues)
    if is_entity_query(message, query):
        return False
    if wants_all_sportsbooks(message) or _MAP_LEAGUE.search(message):
        return True
    if _ONBOARD_VERB.search(message) and _LEAGUE_KW.search(message):
        return True
    if re.search(r"\benable\b", message, re.I) and _LEAGUE_KW.search(message):
        return True
    if _ONBOARD_VERB.search(message):
        if match_league(message, extra=tip_leagues):
            return True
        if _MARKET_KW.search(message):
            return False
        slug = slug_from_message(message, tip_leagues)
        if slug and not leagues_for_market_id(slug):
            return True
    return False


def _names_entity(code_hint: str | None, league_hint: str | None) -> bool:
    """True when the ticker-ish token is something other than the league itself."""
    if not code_hint:
        return False
    return code_hint.lower() != (league_hint or "").lower()


def _match_league(text: str, tip_leagues: set[str]) -> str | None:
    lower = text.lower()
    # Prefer longer slug matches.
    for slug in sorted(tip_leagues, key=len, reverse=True):
        if re.search(rf"\b{re.escape(slug.lower())}\b", lower):
            return slug
    return None


def _code_hint(text: str) -> str | None:
    """First ticker-ish token; reject bare integers (e.g. '45' from '45 events')."""
    for tok in re.findall(r"\b([A-Z0-9]{2,12})\b", text):
        if tok.isdigit() or tok.lower() in _LEAGUE_CODE_SKIP:
            continue
        return tok
    return None


def _looks_like_report(text: str) -> bool:
    """True when the message is a gap/coverage dump rather than a short pin."""
    if "\n" in text:
        return True
    if _REPORT_KW.search(text) and (_REPORT_LIST.search(text) or len(text) > _PIN_CMD_MAX_CHARS):
        return True
    codes = {
        tok
        for tok in re.findall(r"\b([A-Z0-9]{2,12})\b", text)
        if not tok.isdigit() and tok.lower() not in _LEAGUE_CODE_SKIP
    }
    return len(codes) >= 3


def _book_hint(text: str) -> str | None:
    books = named_sportsbooks(text)
    return books[0] if books else None
