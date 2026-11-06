"""Legacy Underdog UDX ticker grammar, for the tip-era control-plane tooling only.

The mapper (``mappers/exchanges/underdog*.py``) reads typed fields and never
parses a ticker. RFQ legs reach the gap tools as a bare ticker with no
catalogue row, so these tools still need this grammar. Do not import it from
the mapper path; delete it with the tip workflow.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG

_ET = ZoneInfo("America/New_York")
_PERIODS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_DATE_RE = re.compile(
    r"(?P<yy>\d{2})(?P<mon>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"(?P<dd>\d{2})(?P<hhmm>\d{4})"
)
# NCAAF team totals write a one-letter marker ahead of the line ("A13.5"); the
# side is then read from the sentence's YES team, never from the marker.
_LINE_RE = re.compile(r"^(?P<code>[A-Za-z]+)?(?P<line>\d+(?:\.\d+)?)$")
_VENUE_TOKENS = tuple(sorted(VENUE_TOKEN_TO_LEAGUE_SLUG, key=len, reverse=True))
_UDX_SPORT_ALT = "|".join(re.escape(token) for token in _VENUE_TOKENS)
_UDX_TOKEN = re.compile(
    rf"\b(UDX(?:{_UDX_SPORT_ALT})[A-Z0-9]*_[A-Za-z0-9]+_[A-Za-z0-9.]+)\b",
)
_PLAYER_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")
_PLAYER_CODE_LEN = 7

_WIN_PRODUCTS = frozenset({"GAMEWIN", "MATCHWIN", "FIGHTWIN"})

Pairs = Mapping[str, tuple[str, str] | None]


@dataclass(frozen=True)
class UnderdogTicker:
    """One parsed single-leg UDX ticker."""

    sport: str
    product: str
    period: str
    away: str
    home: str
    start: datetime
    player_token: str
    selection: str
    raw: str




def find_udx_ticker(text: str) -> str:
    """First Underdog UDX ticker in ``text``, if any."""
    stripped = (text or "").strip()
    match = _UDX_TOKEN.fullmatch(stripped)
    if match is not None:
        return match.group(1)
    found = _UDX_TOKEN.search(stripped)
    return found.group(1) if found is not None else ""




def udx_player_code(display_name: str) -> str:
    """Underdog player code: first initial + family name, cut to 7 characters."""
    parts = [part for part in _PLAYER_TOKEN_RE.sub(" ", display_name).split() if part]
    if not parts:
        return ""
    code = parts[0] if len(parts) == 1 else f"{parts[0][0]}{parts[-1]}"
    return code.upper()[:_PLAYER_CODE_LEN]


def venue_token_from_body(body: str) -> str:
    """Longest venue token at the start of a UDX ticker body (after ``UDX``)."""
    best = ""
    for token in _VENUE_TOKENS:
        if body.startswith(token) and len(token) > len(best):
            best = token
    return best










def split_teams(blob: str, codes: frozenset[str]) -> tuple[str, str] | None:
    """Split concatenated away+home codes. Two valid splits are refused."""
    hits = [
        (blob[:i], blob[i:])
        for i in range(2, len(blob) - 1)
        if blob[:i] in codes and blob[i:] in codes
    ]
    if len(hits) != 1:
        return None
    return hits[0]


def split_by_selection(blob: str, selection: str) -> tuple[str, str] | None:
    """Split when the selection names one side and there is no sibling evidence."""
    code, _line = _selection_line(selection)
    if not code.isalpha() or len(code) < 2:
        return None
    prefix = suffix = None
    rest = blob[len(code):]
    if blob.startswith(code) and rest.isalpha() and len(rest) >= 2:
        prefix = (code, rest)
    head = blob[: -len(code)]
    if blob.endswith(code) and head.isalpha() and len(head) >= 2:
        suffix = (head, code)
    if prefix and suffix and prefix != suffix:
        return None
    return prefix or suffix


def _period_of(token: str) -> tuple[str, str]:
    for period in _PERIODS:
        if token.endswith(period) and len(token) > len(period):
            return token[: -len(period)], period
    if token[-1:] in {"3", "5", "7"} and token[:-1].isalpha():
        return token[:-1], token[-1]
    return token, ""


def _start(match: re.Match[str]) -> datetime:
    year = 2000 + int(match.group("yy"))
    hour = int(match.group("hhmm")[:2])
    minute = int(match.group("hhmm")[2:])
    return datetime(
        year, _MONTHS[match.group("mon")], int(match.group("dd")),
        hour, minute, tzinfo=_ET,
    )


def _sport_of(body: str, sport: str) -> str:
    """Venue token from the tip exchange settings, else longest body prefix.

    A longer known token wins over the tip one: ``ATP`` must not claim
    ``UDXATPCHL...`` tickers.
    """
    venue = sport.strip().upper()
    if not venue:
        return venue_token_from_body(body)
    if not body.startswith(venue) or len(venue_token_from_body(body)) > len(venue):
        return ""
    return venue


def is_venue_ticker(ticker: str, sport: str) -> bool:
    """True when ``ticker`` belongs to the tip venue token ``sport`` (``ATP`` is not ``ATPCHL``)."""
    return ticker.startswith("UDX") and bool(_sport_of(ticker[3:], sport))


def _ticker_parts(
    ticker: str, sport: str,
) -> tuple[str, str, str, str, re.Match[str], str] | None:
    """(venue, product, period, event, date match, selection) of one UDX ticker."""
    if not ticker.startswith("UDX"):
        return None
    body = ticker[3:]
    found_sport = _sport_of(body, sport)
    if not found_sport or "_" not in body:
        return None
    head, selection = body[len(found_sport):].rsplit("_", 1)
    product_token, _, event = head.partition("_")
    product, period = _period_of(product_token)
    found = _DATE_RE.search(event)
    if found is None or not product.isalnum():
        return None
    return found_sport, product, period, event, found, selection


def sibling_pairs(tickers: Iterable[str], sport: str = "") -> dict[str, tuple[str, str] | None]:
    """Event key (team blob + start) -> (away, home) from that event's own win markets.

    Kalshi's rule: the two moneyline selections of one event concatenate to
    the glued team blob, in away+home order. ``None`` marks an event whose
    win selections do not rebuild the blob (tennis and UFC glue surname
    stems and select by person code), so no team split is guessed for it.
    An event with fewer than two non-draw win selections proves nothing and
    is left out.
    """
    picks: dict[str, set[str]] = {}
    for ticker in tickers:
        parts = _ticker_parts(ticker, sport)
        if parts is None:
            continue
        _venue, product, _period, event, found, selection = parts
        if product in _WIN_PRODUCTS and found.end() == len(event):
            picks.setdefault(event, set()).add(selection)
    out: dict[str, tuple[str, str] | None] = {}
    for key, selections in picks.items():
        selections.discard("DRAW")
        if len(selections) < 2:
            continue
        found = _DATE_RE.search(key)
        blob = key[: found.start()] if found else ""
        hits = [(a, b) for a in selections for b in selections if a != b and a + b == blob]
        out[key] = hits[0] if len(hits) == 1 else None
    return out


def pair_codes(pairs: Pairs) -> frozenset[str]:
    """Every team code the sibling pairs proved, for events with no open win market."""
    return frozenset(code for pair in pairs.values() if pair for code in pair)


def parse_ticker(
    ticker: str, codes: frozenset[str], *, sport: str = "", pairs: Pairs | None = None,
) -> UnderdogTicker | None:
    """Parse one UDX ticker. ``sport`` is the tip venue token.

    Team split order: sibling pair for this event, then ``codes``, then the
    selection itself — the last only when no sibling evidence exists.
    """
    parts = _ticker_parts(ticker, sport)
    if parts is None:
        return None
    found_sport, product, period, event, found, selection = parts
    blob = event[: found.start()]
    key = event[: found.end()]
    known = pairs or {}
    teams = known.get(key) or split_teams(blob, codes)
    if teams is None and key not in known:
        teams = split_by_selection(blob, selection)
    away, home = teams if teams else ("", "")
    return UnderdogTicker(
        sport=found_sport, product=product, period=period, away=away, home=home,
        start=_start(found), player_token=event[found.end():],
        selection=selection, raw=ticker,
    )




def _selection_line(selection: str) -> tuple[str, float | None]:
    match = _LINE_RE.fullmatch(selection)
    if match is None:
        return selection, None
    code = match.group("code") or ""
    return code, float(match.group("line"))








