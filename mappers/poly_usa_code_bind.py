"""Unique-bind Polymarket US team abbreviations onto Optic sides.

The code is the gateway's typed ``team.abbreviation``. Console harvest uses
``unique_code_side`` / ``code_hits`` so UFC ``ryagan`` / tennis ``jsinxx``
pin when the abbreviation is not the Optic one. Fail-closed: both sides
unique, no steal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mappers.exchanges.polymarket_usa_match import parse_kickoff

_PARTICLES = frozenset({
    "de", "del", "la", "el", "los", "las", "fc", "cf", "cd", "sc", "club",
    "united", "city", "the", "of", "and", "y", "da", "do", "di", "a", "al",
    "csyd", "cs", "ud", "ac", "as", "fk", "if", "bk", "sk", "il", "ca",
})


def words(name: str) -> list[str]:
    """Alphanumeric tokens from a display name."""
    out: list[str] = []
    buf: list[str] = []
    for ch in name.casefold():
        if ch.isalnum():
            buf.append(ch)
            continue
        if buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def initials(tokens: list[str], *, drop_particles: bool) -> str:
    """First letters of tokens, optionally dropping club particles."""
    src = [w for w in tokens if w not in _PARTICLES] if drop_particles else tokens
    return "".join(w[0] for w in src if w)


def code_hits(code: str, abbr: str, name: str) -> int:
    """Score how well a US team abbreviation matches an Optic side (0–2)."""
    if _exact_abbr(code, abbr):
        return 2
    return _fuzzy_code_hits(code, name)


def unique_code_side(
    code: str, home_abbr: str, away_abbr: str, home_name: str, away_name: str,
) -> str:
    """home / away when ``code`` uniquely binds one Optic side, else empty."""
    home_exact, away_exact = _exact_abbr(code, home_abbr), _exact_abbr(code, away_abbr)
    if home_exact and not away_exact:
        return "home"
    if away_exact and not home_exact:
        return "away"
    if home_exact or away_exact:
        return ""
    home_n = _fuzzy_code_hits(code, home_name)
    away_n = _fuzzy_code_hits(code, away_name)
    if home_n > away_n:
        return "home"
    if away_n > home_n:
        return "away"
    return ""


def orient_codes(
    home: str, away: str,
    home_abbr: str, away_abbr: str, home_name: str, away_name: str,
) -> str:
    """same / flip when both US codes uniquely bind opposite Optic sides."""
    home_side = unique_code_side(home, home_abbr, away_abbr, home_name, away_name)
    away_side = unique_code_side(away, home_abbr, away_abbr, home_name, away_name)
    if not home_side or not away_side or home_side == away_side:
        return ""
    return "same" if home_side == "home" else "flip"


def _exact_abbr(code: str, abbr: str) -> bool:
    """True when the US code equals the Optic abbreviation."""
    left, right = code.casefold(), (abbr or "").casefold()
    return bool(left) and bool(right) and left == right


def _fuzzy_code_hits(code: str, name: str) -> int:
    """Name-token / initials score. Does not match a longer code to a shorter abbr."""
    token = code.casefold()
    toks = words(name)
    if not token or not toks:
        return 0
    if any(word.startswith(token) for word in toks if len(token) >= 3):
        return 2
    for drop in (True, False):
        ini = initials(toks, drop_particles=drop)
        if ini == token:
            return 2
        if ini.startswith(token) or (token.startswith(ini) and len(ini) >= 3):
            return 1
    first = next((word for word in toks if word not in _PARTICLES), "")
    if first[:3] == token[:3] and len(token) >= 3:
        return 1
    return 0


def within_hours(raw: str, now: datetime, hours: int) -> bool:
    """True when an ISO kickoff is inside ±hours of ``now``."""
    kick = parse_kickoff(raw)
    if kick is None:
        return False
    clock = now if now.tzinfo else now.replace(tzinfo=UTC)
    return abs((kick - clock).total_seconds()) <= hours * 3600


def day_overlaps_hours(day: str, now: datetime, hours: int) -> bool:
    """True when a YYYY-MM-DD event date overlaps the ±hours window."""
    parts = (day or "")[:10].split("-")
    if len(parts) != 3:
        return False
    try:
        start = datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=UTC)
    except ValueError:
        return False
    clock = now if now.tzinfo else now.replace(tzinfo=UTC)
    lo, hi = clock - timedelta(hours=hours), clock + timedelta(hours=hours)
    return start < hi and (start + timedelta(days=1)) > lo
