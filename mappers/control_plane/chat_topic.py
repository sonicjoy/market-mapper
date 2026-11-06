"""On-topic gate for Mapper Chat: refuse cheaply instead of paying for an LLM call.

v1 is soft-only. A false refuse on a real mapping question costs more than
letting a borderline one through, so every gated turn gets the same nudge and
anything with a domain signal — or any live thread — is allowed through.
"""

from __future__ import annotations

import re

from mappers.control_plane.chat_console import ConsolePage, console_has_context
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_resolve import has_exchange_symbol
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.settings import Settings

SOFT_REFUSE_REPLY = (
    "I can help with mapping aliases, leagues, and market rules "
    "(pins, coverage, gap reports). What league or code are you looking at?"
)

_DOMAIN_NOUN = re.compile(
    r"\b(alias(?:es)?|pin(?:s|ned)?|map(?:s|ped|ping|pings)?|leagues?|markets?"
    r"|rules?|taxonomy|spread|moneyline|total|coverage|gaps?|unmapped|parity"
    r"|tip|entities|entity|ticker|optic|kalshi|crypto|crypto_id|sweep|harvest"
    r"|sportsbooks?|platforms?|exchanges?|cart"
    r"|teams?|players?|fighters?"
    r"|propose|proposals?|onboard|fixtures?|competitors?|rfq|snapshot"
    r"|dual[_\s-]?read|rule[_\s-]?set)\b",
    re.I,
)

def is_on_topic(
    message: str,
    *,
    scored: IntentScore,
    bag: ChatSession,
    settings: Settings,
    page: ConsolePage | None = None,
) -> bool:
    """True when a turn is worth answering (domain signal, live thread, or console context)."""
    if not settings.chat_topic_gate_enabled:
        return True
    if in_conversation(bag) or on_mapping_page(page):
        return True
    return topic_score(message, scored, settings) >= max(1, settings.chat_topic_min_score)


def in_conversation(bag: ChatSession) -> bool:
    """A live thread already carries the subject, so terse follow-ups pass."""
    if bag.pending is not None or bag.turns:
        return True
    return bool(bag.last_skill and bag.answered_turns > 0)


def on_mapping_page(page: ConsolePage | None) -> bool:
    """A trader with a league or query already loaded is mid-workflow, not off topic."""
    if page is None:
        return False
    return console_has_context(page)


def topic_score(message: str, scored: IntentScore, settings: Settings) -> int:
    """Count independent mapping-domain signals in a cold-start message."""
    if has_exchange_symbol(scored.resolved, message):
        return max(1, settings.chat_topic_min_score)
    signals = (
        bool(_DOMAIN_NOUN.search(message)),
        bool(scored.league_hint),
        bool(scored.code_hint),
        bool(scored.sportsbook_hint),
        _allowed_phrase(message, settings),
    )
    return sum(1 for hit in signals if hit)


def _allowed_phrase(message: str, settings: Settings) -> bool:
    lower = message.lower()
    return any(phrase in lower for phrase in settings.chat_topic_allow_phrases)
