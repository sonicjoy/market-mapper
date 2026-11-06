"""Kalshi goalscorer ticker and player-code helpers (pure functions).

    KXEPLGOAL-26AUG25ARSCHE-ARSBSAKA7-1
    goal prefix | fixture part | player code

A player code is team abbreviation + first initial + up to five surname
letters + kit number, then the goal line: ``-1`` is anytime (1+), ``-2`` and
``-3`` are 2+ / 3+ goals and are never anytime markets. The fixture part and
team abbreviations come from the game's Kalshi moneyline ticker
(``KXEPLGAME-26AUG25ARSCHE-ARS``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

NAME_PARTICLES = frozenset(
    {"DE", "DA", "DO", "DOS", "DAS", "LO", "LA", "LE", "LES", "VAN", "VON", "DI", "EL", "AL", "DEL", "Y"}
)
# Goal line on an anytime goalscorer ticker (…-ARSBSAKA7-1).
ANYTIME_LINE = "1"
# Initial + surname-prefix match (90) or exact surname (100).
SUGGEST_MIN_SCORE = 90
RANK_MIN_SCORE = 20


# Letters NFKD does not decompose.
_TRANSLIT = str.maketrans(
    {"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ı": "i"}
)


def strip_accents(text: str) -> str:
    """Return text with accents removed (É → E, Ø → O)."""
    nfkd = unicodedata.normalize("NFKD", text.translate(_TRANSLIT))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalise_name(text: str) -> str:
    """Case- and accent-insensitive form used to compare selection names."""
    return " ".join(strip_accents(text).casefold().split())


# legacy: ticker parse — replace with the typed venue field, do not extend
def series(ticker: str) -> str:
    """Series prefix of any Kalshi ticker (KXEPLGOAL, KXEPLGAME, ...)."""
    return ticker.split("-")[0]


# legacy: ticker parse — replace with the typed venue field, do not extend
def fixture_part(ticker: str) -> str:
    """Event segment shared by every market on one match (26AUG25ARSCHE)."""
    parts = ticker.split("-")
    return parts[1] if len(parts) > 1 else ""


# legacy: ticker parse — replace with the typed venue field, do not extend
def ml_team_abbrev(ml_ticker: str) -> str:
    """Team abbreviation at the end of a moneyline ticker."""
    return ml_ticker.split("-")[-1]


def goal_prefix_for_series(ml_series: str) -> str | None:
    """Goalscorer series for a moneyline series (KXEPLGAME → KXEPLGOAL)."""
    return ml_series[: -len("GAME")] + "GOAL" if ml_series.endswith("GAME") else None


# legacy: ticker parse — replace with the typed venue field, do not extend
def player_code(goal_ticker: str) -> str:
    """Player segment of a goal ticker (ARSBSAKA7-1)."""
    return "-".join(goal_ticker.split("-")[2:])


# legacy: ticker parse — replace with the typed venue field, do not extend
def is_anytime(ticker_or_code: str) -> bool:
    """True for a 1+ (anytime) goal ticker or player code; False for 2+ / 3+."""
    return ticker_or_code.rsplit("-", 1)[-1] == ANYTIME_LINE


# legacy: ticker parse — replace with the typed venue field, do not extend
def anytime_code(code: str) -> str:
    """The same player's code on the 1+ line (MUNBFERNA8-3 → MUNBFERNA8-1)."""
    return f"{code.split('-')[0]}-{ANYTIME_LINE}"


# legacy: ticker parse — replace with the typed venue field, do not extend
def line_code(code: str, line: str) -> str:
    """The same player's code on another goal line (ARSBSAKA7-1, "2" → ARSBSAKA7-2)."""
    return f"{code.split('-')[0]}-{line}"


def player_goals_key(selection: str, points: float) -> str:
    """Optic's player_goals grouping key: "Ryan O'Reilly", 1.5 → "ryan_o_reilly:1.5".

    Lower-cased, every run of characters outside a-z / 0-9 / "-" becomes one "_"
    (accented letters included: "Dávid Hancko" → "d_vid_hancko").
    """
    slug = re.sub(r"[^a-z0-9-]+", "_", selection.lower()).strip("_")
    return f"{slug}:{points:g}"


def first_goal_prefix(goal_prefix: str) -> str:
    """First goalscorer series for an anytime goal series (KXUCLGOAL → KXUCLFIRSTGOAL)."""
    return goal_prefix.removesuffix("GOAL") + "FIRSTGOAL"


def anytime_prefix(series_prefix: str) -> str:
    """Anytime goal series for either goal series (KXUCLFIRSTGOAL → KXUCLGOAL)."""
    return series_prefix.removesuffix("FIRSTGOAL") + "GOAL" if series_prefix.endswith("FIRSTGOAL") else series_prefix


def is_first_goal(ticker: str) -> bool:
    """True for a first goalscorer ticker (KXUCLFIRSTGOAL-…)."""
    return series(ticker).endswith("FIRSTGOAL")


def to_anytime(ticker: str) -> str:
    """The same player's 1+ ticker from any of his goal tickers (…-ARSBSAKA7-3 / KX…FIRSTGOAL-…-ARSBSAKA7)."""
    prefix, part, code = series(ticker), fixture_part(ticker), player_code(ticker)
    return build_ticker(anytime_prefix(prefix), part, anytime_code(code))


def to_first_goal(ticker: str) -> str:
    """The same player's first goalscorer ticker from any of his goal tickers."""
    prefix, part, code = series(ticker), fixture_part(ticker), player_code(ticker)
    return build_ticker(first_goal_prefix(anytime_prefix(prefix)), part, code.split("-")[0])


def build_ticker(goal_prefix: str, fixture: str, code: str) -> str:
    """Goal ticker for one player on one fixture."""
    return f"{goal_prefix}-{fixture}-{code}"


def code_team(code: str, team_abbrevs: Iterable[str]) -> str | None:
    """Team abbreviation the code starts with; the longest wins on overlap."""
    base = code.split("-")[0]
    hits = [t for t in team_abbrevs if t and base.startswith(t)]
    return max(hits, key=len) if hits else None


@dataclass(frozen=True)
class CodeParts:
    """A player code split into its components."""

    team: str
    first_initial: str
    surname: str
    kit: str


def parse_code(code: str, team: str | None = None) -> CodeParts | None:
    """Split a player code; team defaults to the first three letters."""
    base = code.split("-")[0]
    team = team or base[:3]
    match = re.fullmatch(r"([A-Z]+?)(\d+)", base[len(team) :])
    if not match or len(match.group(1)) < 2:
        return None
    name, kit = match.groups()
    return CodeParts(team, name[0], name[1:], kit)


def _surname(clean_parts: list[str]) -> str:
    """Last surname word, skipping particles (de, van, ...)."""
    meaningful = [p for p in clean_parts[1:] if p not in NAME_PARTICLES]
    if meaningful:
        return meaningful[-1]
    return clean_parts[-1] if len(clean_parts) > 1 else clean_parts[0][1:]


def score_candidate(first_initial: str, surname_frag: str, name: str) -> int:
    """How well a selection name fits a code's initial + surname fragment (0-100)."""
    clean = strip_accents(name).upper().split()
    if not clean:
        return 0
    surname = _surname(clean)
    frag = surname_frag.upper()
    if surname == frag:
        score = 60
    elif surname.startswith(frag):
        score = 50
    elif frag.startswith(surname):
        score = 35
    elif len(frag) >= 3 and frag[:3] == surname[:3]:
        score = 20
    else:
        return 10 if clean[0][0] == first_initial else 0
    return score + 40 if clean[0][0] == first_initial else score


def rank_candidates(parts: CodeParts, names: Iterable[str], top_n: int = 10) -> list[tuple[str, int]]:
    """Candidate names scoring at least RANK_MIN_SCORE, best first."""
    scored = [(n, score_candidate(parts.first_initial, parts.surname, n)) for n in set(names)]
    ranked = sorted((s for s in scored if s[1] >= RANK_MIN_SCORE), key=lambda s: (-s[1], s[0]))
    return ranked[:top_n]


def suggest(ranked: list[tuple[str, int]]) -> str | None:
    """The single clear best match, or None when there is none or a tie."""
    if not ranked or ranked[0][1] < SUGGEST_MIN_SCORE:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0]
