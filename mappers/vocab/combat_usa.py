"""Polymarket US ticker suffixes for UFC fight props (Path 2).

Official Poly maps English questions; US RFQ legs are ``astatc-ufc-…``
suffixes. Only like-for-like Optic buckets are recognized:

- ``gtd-yes`` / ``gtd-no`` → ``fight_goes_distance``
- ``mof-ko`` → ``game_win_by_kotko`` (Optic ``win_by_ko_tko``)
- ``mof-sub`` / ``mof-dec`` → ``method_of_finish`` grouping_key
- ``mov-f{1,2}-{ko,sub,dec}`` → ``method_of_victory``; ``ko`` is Optic
  ``KO/TKO`` (``ko_tko``), never Kalshi ``ko_tko_dq``

``rof-before-rN`` ("ends before round N") is not Optic ``total_rounds``.
The suffix is recognized here, then classified from the tip
``ticker_suffix`` row. A missing row, an ignore, or an unknown canonical
stays unparsed. Round of victory (``rov-``) is Optic ``round_betting``
passthrough, not this parser.

``match_operator=prefix`` is honored only by ``_row_matches_suffix``.
PX honors ``suffix`` and keeps the longer suffix. Kalshi, Optic,
crypto.com, and Polymarket kind overlays match the exact ``source_key``.
A prefix row and a longer exact row can both exist; ``_suffix_rule``
takes the longer key, then the lower priority.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mappers.fight_props import METHOD_DECISION, METHOD_KO_TKO, METHOD_SUBMISSION
from mappers.market_types import MarketType
from mappers.shared import normalize_line

FightBet = tuple[str, str | None, float | None, str, str | None]
_ResolveEntity = Callable[[str], str | None]

ROF_BEFORE_SOURCE_KEY = "rof-before-r"
ROF_BEFORE_KEY_TYPE = "ticker_suffix"
ROF_BEFORE_MATCH = "prefix"
ROF_BEFORE_NOTES = (
    "Polymarket US rof-before-rN is not Optic total_rounds. "
    "Ignored until Optic to_start_round_N is confirmed."
)

_GTD_RE = re.compile(r"^gtd-(?P<side>yes|no)$")
_MOF_RE = re.compile(r"^mof-(?P<tag>ko|sub|dec)$")
_MOV_RE = re.compile(r"^mov-(?P<slot>f[12])-(?P<tag>ko|sub|dec)$")
_ROF_RE = re.compile(r"^rof-before-r(?P<round>[1-9]\d?)$")
_KNOWN_CANONICALS = frozenset(item.value for item in MarketType)
_YES_NO = {"yes": "no", "no": "yes"}
_MOV_GROUPING = {
    "ko": METHOD_KO_TKO,
    "sub": METHOD_SUBMISSION,
    "dec": METHOD_DECISION,
}


# legacy: ticker parse — replace with the typed venue field, do not extend
def parse_us_fight_bet(
    suffix: str,
    market_types: Mapping[str, MarketType],
    home_code: str,
    away_code: str,
    resolve_entity: _ResolveEntity,
    tip_suffix_rules: Sequence[Any] = (),
) -> FightBet | None:
    """Map one US fight-prop suffix onto a canonical bet, or None.

    ``rof-before-rN`` returns immediately from the tip row. Other suffixes
    keep the go-the-distance / method recognizers.
    """
    text = (suffix or "").casefold()
    if _ROF_RE.fullmatch(text):
        return _rof_before_bet(text, tip_suffix_rules)
    return (
        _us_gtd(text, market_types)
        or _us_mof(text, market_types)
        or _us_mov(text, market_types, home_code, away_code, resolve_entity)
    )


def _rof_before_bet(text: str, rules: Sequence[Any]) -> FightBet | None:
    """Apply the tip row. Absent, ignore, or unknown canonical stays unparsed."""
    match = _ROF_RE.fullmatch(text)
    row = _suffix_rule(text, rules)
    if match is None or row is None or str(getattr(row, "action", "") or "") != "map":
        return None
    canonical = str(getattr(row, "canonical_market_type", "") or "")
    side = _yes_side(row)
    if canonical not in _KNOWN_CANONICALS or side is None:
        return None
    return canonical, None, _line_from_row(match.group("round"), row), side, None


def _suffix_rule(text: str, rules: Sequence[Any]) -> Any | None:
    """Longest matching tip key, then the lower priority."""
    matches = [row for row in rules if _row_matches_suffix(text, row)]
    if not matches:
        return None
    matches.sort(key=_suffix_rank)
    return matches[0]


def _suffix_rank(row: Any) -> tuple[int, int]:
    key = str(getattr(row, "source_key", "") or "")
    return (-len(key), int(getattr(row, "priority", 0) or 0))


def _row_matches_suffix(text: str, row: Any) -> bool:
    """True when this tip row is a live ticker-suffix match for ``text``."""
    if not getattr(row, "enabled", True) or getattr(row, "tombstone", False):
        return False
    if str(getattr(row, "source_key_type", "") or "") != ROF_BEFORE_KEY_TYPE:
        return False
    book = str(getattr(row, "sportsbook", "") or "")
    if book and book != "polymarket_usa":
        return False
    key = str(getattr(row, "source_key", "") or "").casefold()
    if not key:
        return False
    operator = str(getattr(row, "match_operator", "") or "exact")
    if operator == "prefix":
        return text.startswith(key)
    if operator == "suffix":
        return text.endswith(key)
    return text == key


def _yes_side(row: Any) -> str | None:
    """Venue Yes side from the row. ``side_swap`` flips yes and no only."""
    raw = getattr(row, "yes_side", None)
    if raw is None:
        return None
    side = str(raw).strip().lower()
    if not side:
        return None
    if getattr(row, "side_swap", None):
        return _YES_NO.get(side, side)
    return side


def _line_from_row(round_text: str, row: Any) -> float | None:
    """Round N plus ``line_offset``. Null offset means no line."""
    offset = getattr(row, "line_offset", None)
    if offset is None:
        return None
    return normalize_line(int(round_text) + float(offset))


def _typed(market_types: Mapping[str, MarketType], key: str) -> MarketType | None:
    return market_types.get(key)


def _us_gtd(
    suffix: str, market_types: Mapping[str, MarketType],
) -> FightBet | None:
    match = _GTD_RE.fullmatch(suffix)
    mt = _typed(market_types, "go_the_distance")
    if match is None or mt is None:
        return None
    return mt.value, None, None, match.group("side"), None


def _us_mof(
    suffix: str, market_types: Mapping[str, MarketType],
) -> FightBet | None:
    match = _MOF_RE.fullmatch(suffix)
    if match is None:
        return None
    tag = match.group("tag")
    if tag == "ko":
        mt = _typed(market_types, "game_win_by_kotko")
        if mt is None:
            return None
        return mt.value, None, None, "yes", None
    mt = _typed(market_types, "method_of_finish")
    if mt is None:
        return None
    grouping = METHOD_SUBMISSION if tag == "sub" else METHOD_DECISION
    return mt.value, None, None, "yes", grouping


def _us_mov(
    suffix: str,
    market_types: Mapping[str, MarketType],
    home_code: str,
    away_code: str,
    resolve_entity: _ResolveEntity,
) -> FightBet | None:
    match = _MOV_RE.fullmatch(suffix)
    mt = _typed(market_types, "method_of_victory")
    if match is None or mt is None:
        return None
    grouping = _MOV_GROUPING[match.group("tag")]
    code = home_code if match.group("slot") == "f1" else away_code
    entity = resolve_entity(code)
    if entity is None:
        return None
    return mt.value, entity, None, "yes", grouping
