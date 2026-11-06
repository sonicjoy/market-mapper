"""League / Sport / sportsbook tokens for Mapper Chat slug resolution."""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.chat_profiles import CHAT_SPORTSBOOKS
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.suggest_markets import spine_league_slugs

SPORTS: tuple[str, ...] = (
    "soccer",
    "football",
    "basketball",
    "baseball",
    "hockey",
    "tennis",
    "mma",
    "boxing",
    "esports",
    "cricket",
)
SPORTSBOOKS: tuple[str, ...] = CHAT_SPORTSBOOKS
_SPORT_ALIAS = {"esport": "esports"}
_TENNIS_TOKENS = frozenset({"itf", "atp", "wta", "tennis", "challenger"})
_BOOK_ALIAS = {
    "crypto": "crypto.com",
    "poly us": "polymarket_usa",
    "poly_us": "polymarket_usa",
    "polyusa": "polymarket_usa",
    "polymarket us": "polymarket_usa",
    "polymarket usa": "polymarket_usa",
    "polymarket (usa)": "polymarket_usa",
    "polymarket (us)": "polymarket_usa",
    "udx": "underdog",
    "dkex": "dkex",
    "railbird": "dkex",
}
_LEAGUE_NOUNS = frozenset(
    {
        "league",
        "leagues",
        "competition",
        "competitions",
        "tournament",
        "tournaments",
    }
)
_FILLER = frozenset(
    {
        "a", "add", "adding", "all", "also", "an", "and", "at", "be", "books",
        "called", "can", "could", "create", "creating", "did", "do", "does",
        "enable", "enabled", "every", "exchanges", "for", "from", "i", "in",
        "into", "is", "it", "just", "let", "lets", "like", "map", "mapping",
        "mappings", "me", "my", "name", "named", "need", "needs", "new",
        "next", "now", "of", "on", "onboard", "onboarding", "or", "our",
        "platforms", "please", "pls", "series", "set", "setup", "should",
        "slug", "soon", "sportsbooks", "start", "support", "thanks", "that",
        "the", "there", "this", "to", "today", "up", "us", "want", "wanted",
        "wants", "we", "with", "would", "you",
    }
)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_ALL_BOOKS = re.compile(
    r"\b(?:all|every)\s+(?:the\s+)?(?:sportsbooks?|books?|exchanges?|platforms?)\b",
    re.I,
)
_MAX_SLUG_WORDS = 3


def tip_league_row(store: Any | None, slug: str) -> LeagueRow | None:
    """One activated-tip league row by slug."""
    if store is None or not slug.strip():
        return None
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return None
    key = slug.strip().lower()
    for row in store.leagues_for(rid):
        if row.league.lower() == key and not row.tombstone:
            return row
    return None


def league_slugs(store: Any | None = None) -> frozenset[str]:
    """League slugs on the activated tip."""
    if store is None:
        return frozenset()
    from mappers.control_plane.chat_tip_cache import tip_league_slugs

    return frozenset(tip_league_slugs(store))


def match_league(
    text: str,
    store: Any | None = None,
    extra: set[str] | None = None,
) -> str | None:
    """Longest tip slug mentioned in ``text`` (underscores = spaces)."""
    lower = text.lower()
    slugs = set(league_slugs(store))
    if extra:
        slugs |= {s.lower() for s in extra}
    for slug in sorted(slugs, key=len, reverse=True):
        if _slug_mentioned(slug, lower):
            return slug
    return None


def match_sport(text: str) -> str | None:
    """Listed sport value (plus ``esport`` → ``esports``)."""
    lower = text.lower()
    if re.search(r"\besports?\b", lower):
        return "esports"
    for sport in SPORTS:
        if sport in lower:
            return sport
    return None


def named_sportsbooks(text: str) -> list[str]:
    """Sportsbooks from the console list that appear in ``text`` (mention order)."""
    lower = text.lower()
    hits: list[tuple[int, int, str]] = []
    for book in SPORTSBOOKS:
        aliases = [book, *[k for k, v in _BOOK_ALIAS.items() if v == book]]
        for alias in aliases:
            pattern = rf"(?<![\w.]){re.escape(alias.lower())}(?![\w.])"
            for match in re.finditer(pattern, lower):
                hits.append((match.start(), len(match.group(0)), book))
    hits.sort(key=lambda item: (item[0], -item[1]))
    found: list[str] = []
    seen: set[str] = set()
    occupied = -1
    for start, length, book in hits:
        if start < occupied or book in seen:
            continue
        seen.add(book)
        found.append(book)
        occupied = start + length
    return found


def wants_all_sportsbooks(text: str) -> bool:
    """True when the trader asked for every book / platform."""
    return bool(_ALL_BOOKS.search(text))


def sport_for_slug(slug: str, store: Any | None = None) -> str:
    """Sport from the tip row, else token heuristics in the slug."""
    row = tip_league_row(store, slug)
    if row and row.sport:
        return row.sport
    tokens = set(slug.lower().split("_"))
    if tokens & _TENNIS_TOKENS:
        return "tennis"
    for tok in tokens:
        if tok in _SPORT_ALIAS:
            return _SPORT_ALIAS[tok]
        if tok in SPORTS:
            return tok
    return ""


def optic_id_for(slug: str, store: Any | None = None) -> str:
    """Optic league id from the activated tip; empty if unknown."""
    row = tip_league_row(store, slug)
    if row is None:
        return ""
    return str(row.optic_league_id or "")


def as_league_slug(
    text: str,
    store: Any | None = None,
    extra: set[str] | None = None,
) -> str | None:
    """Strict league slug, or None.

    A slug is real when the tip or ``optic_spine.csv`` knows it, when it tails a
    catalogue slug (``serie a`` → ``brazil_serie_a``), or when the trader typed
    an explicit snake_case slug for a league we have not onboarded yet
    (``lacrosse_pll``). Prose never becomes a league, so ``why not?`` and
    ``the new season`` return None and the skill re-asks instead of sweeping a
    league nobody onboarded.
    """
    raw = text.strip()
    if not raw:
        return None
    known = named_league(raw, store, extra)
    if known:
        return known
    tokens = _TOKEN_RE.findall(raw.lower())
    if not tokens or len(tokens) > _MAX_SLUG_WORDS:
        return None
    slug = "_".join(tokens)
    if not _SLUG_RE.match(slug) or slug in _LEAGUE_NOUNS:
        return None
    if "_" in raw:
        return slug  # the trader typed an explicit slug: serie_a, lacrosse_pll
    # Multi-word only: a lone "cup" / "one" / "women" tails a catalogue slug too,
    # and those are ordinary English long before they are leagues.
    return slug if "_" in slug and _tails_catalog_slug(slug) else None


def named_league(
    text: str,
    store: Any | None = None,
    extra: set[str] | None = None,
) -> str | None:
    """Longest tip, spine, or cached-tip slug mentioned anywhere in ``text``."""
    lower = text.lower()
    for slug in sorted(_known_slugs(store, extra), key=len, reverse=True):
        if _slug_mentioned(slug, lower):
            return slug
    return None


def _known_slugs(store: Any | None, extra: set[str] | None) -> frozenset[str]:
    from mappers.control_plane.chat_tip_cache import cached_tip_league_slugs

    slugs = set(spine_league_slugs()) | cached_tip_league_slugs() | set(league_slugs(store))
    if extra:
        slugs |= {s.lower() for s in extra}
    return frozenset(slugs)


def _tails_catalog_slug(slug: str) -> bool:
    """``serie_a`` is the tail of ``brazil_serie_a`` / ``ecuador_serie_a``."""
    tail = f"_{slug}"
    return any(known.endswith(tail) for known in spine_league_slugs())


def league_followup(
    message: str,
    store: Any | None = None,
    extra: set[str] | None = None,
) -> str | None:
    """Terse league slug from a slot follow-up; None for confirm/noise/prose."""
    from mappers.control_plane.chat_confirm_words import is_no, is_yes

    text = message.strip()
    if not text or is_yes(text) or is_no(text):
        return None
    # "try epl instead" names a real league after a word the filler list misses,
    # so scan the whole reply before falling back to leading-token stripping.
    known = named_league(text, store, extra)
    if known:
        return known
    tokens = [tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _LEAGUE_NOUNS]
    while tokens and tokens[0] in _FILLER:
        tokens.pop(0)
    if not tokens:
        return None
    return as_league_slug(" ".join(tokens[:_MAX_SLUG_WORDS]), store, extra)


def slug_from_message(
    message: str,
    extra_leagues: set[str] | None = None,
    *,
    store: Any | None = None,
) -> str | None:
    """Listed slug if named, else leftover name words around the league noun."""
    known = match_league(message, store, extra_leagues)
    if known:
        return known
    tokens = _TOKEN_RE.findall(message.lower())
    noun_at = next((i for i, tok in enumerate(tokens) if tok in _LEAGUE_NOUNS), None)
    if noun_at is None:
        return _as_slug(_meaningful_run(tokens))
    after = _meaningful_run(tokens[noun_at + 1 :])
    if after:
        return _as_slug(after)
    before = _meaningful_run(list(reversed(tokens[:noun_at])))
    if before:
        words = list(reversed(before))
        if not match_sport(message):
            words.append(_singular(tokens[noun_at]))
        return _as_slug(words)
    return None


def _slug_mentioned(slug: str, lower: str) -> bool:
    if re.search(rf"\b{re.escape(slug)}\b", lower):
        return True
    for variant in {slug.replace("_", " "), slug.replace("_", "-")} - {slug}:
        if re.search(rf"\b{re.escape(variant)}\b", lower):
            return True
    return False


def _skip_tokens() -> frozenset[str]:
    books = {part for book in SPORTSBOOKS for part in book.replace(".", " ").split()}
    return _FILLER | _LEAGUE_NOUNS | set(SPORTS) | books | set(_SPORT_ALIAS) | set(_BOOK_ALIAS)


def _meaningful_run(tokens: list[str]) -> list[str]:
    """Skip listed filler / sport / book words, then take name-like tokens."""
    skip = _skip_tokens()
    run: list[str] = []
    for tok in tokens:
        if tok in skip:
            if run:
                break
            continue
        run.append(tok)
        if len(run) == _MAX_SLUG_WORDS:
            break
    return run


def _as_slug(words: list[str]) -> str | None:
    slug = "_".join(words).strip("_")
    return slug if _SLUG_RE.match(slug) else None


def _singular(noun: str) -> str:
    return noun[:-1] if noun.endswith("s") else noun
