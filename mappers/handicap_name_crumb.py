"""Polymarket labels that are market selections, not entities."""

from __future__ import annotations

import re

_LINE = re.compile(r"\(\s*[+-]\d+(?:\.\d+)?\s*\)")
_OU_LINE = re.compile(r"^(?:over|under|o/?u)\s*[+-]?\d+(?:\.\d+)?$", re.I)
_SCORE = re.compile(r"^\d+\s*[:\-]\s*\d+$")
_NAKED_LINE = re.compile(r"^[+-]\d+(?:\.\d+)?$")
_SELECTION_LITERALS = frozenset({
    "yes", "no", "yes.", "no.",
    "over", "under",
    "draw", "tie", "push", "void",
    "odd", "even",
    "winner", "home", "away",
    "any other score", "any other",
})
_QUESTION_LEAD = (
    "set handicap",
    "map handicap",
    "game handicap",
    "puck line",
    "run line",
    "spread:",
    "exact score",
    "correct score",
    "completed match",
    "both teams to score",
)
_QUESTION_MARKERS = ("to score",)
# Same guard as mappers.vocab.esports_markets: Optic has no per-map moneyline.
_ESPORTS_MAP_WINNER = re.compile(r"\b(?:game|map)\s*\d+\s+winner\b", re.I)


def is_handicap_name_crumb(value: str) -> bool:
    """True for ``Mihalka (-1.5)`` / ``DV1 (+1.5)`` style labels."""
    return bool(_LINE.search(value or ""))


def is_selection_alias(value: str) -> bool:
    """True when the label is a market outcome, not a team/player name."""
    text = (value or "").strip()
    if not text:
        return False
    if is_handicap_name_crumb(text):
        return True
    low = text.casefold()
    if low in _SELECTION_LITERALS:
        return True
    if "to score" in low:
        return True
    return bool(_OU_LINE.fullmatch(text) or _SCORE.fullmatch(text) or _NAKED_LINE.fullmatch(text))


def bare_label(value: str) -> str:
    """Strip a ``(-1.5)`` line crumb from a display label."""
    return _LINE.sub("", value or "").strip()


def is_handicap_question(question: str) -> bool:
    """True when the question is a handicap market, not a vs-name."""
    return is_selection_question(question)


def is_esports_map_winner(question: str) -> bool:
    """True for per-map/game winner titles the live matcher rejects."""
    return bool(_ESPORTS_MAP_WINNER.search(question or ""))


def is_selection_question(question: str) -> bool:
    """True when the question is a selection market, not a vs-name overlay."""
    text = (question or "").strip()
    if not text:
        return False
    if is_esports_map_winner(text):
        return True
    folded = text.casefold()
    if any(folded.startswith(lead) for lead in _QUESTION_LEAD):
        return True
    if any(f": {lead}" in folded for lead in _QUESTION_LEAD):
        return True
    return any(marker in folded for marker in _QUESTION_MARKERS)
